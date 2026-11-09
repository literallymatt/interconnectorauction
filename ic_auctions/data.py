"""Fetch the NESO interconnector auction dataset and turn it into a clean table."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

RESOURCE_ID = "6a928369-bed3-445f-af8a-69cdb2cc5089"
DUMP_URL = f"https://api.neso.energy/datastore/dump/{RESOURCE_ID}"
PORTAL_URL = (
    "https://www.neso.energy/data-portal/"
    "interconnector-requirement-and-auction-summary-data"
)
CACHE_PATH = Path(__file__).resolve().parent.parent / ".cache" / "auctions.csv"

# Dataset code -> display name. The order also fixes each interconnector's colour.
INTERCONNECTORS = {
    "IFA1": "IFA1",
    "BN": "BritNed",
    "NEMO": "Nemo Link",
    "IFA2": "IFA2",
    "EL": "ElecLink",
    "VKL": "Viking Link",
}

_RENAME = {
    "Published DateTime": "published",
    "Notes": "notes",
    "Auction ID": "auction_id",
    "Auction Lot ID": "lot_id",
    "Volume Required": "required_mw",
    "Qualified IC": "qualified",
    "Start Time": "start",
    "End Time": "end",
    "Bid Deadline": "deadline",
    "Default Price": "default_price",
    "Clearing Price": "clearing_price",
    "Best Price": "best_price",
    "VWA Price": "vwa_price",
    "Cleared Volume": "reported_cleared_mw",
    "Total Bid Volume": "bid_mw",
    "System Flag": "system_flag",
}


@dataclass(frozen=True)
class Dataset:
    lots: pd.DataFrame
    fetched_at: datetime
    stale_reason: str | None = None  # set when serving the on-disk copy


def clean(csv_text: str) -> pd.DataFrame:
    """Normalise the raw CSV into one row per auction lot.

    `cleared_mw` is the reported lot total, falling back to the sum of the
    per-interconnector volumes because the reported figure is blank on many
    older lots. `traded` marks lots that actually cleared: unfilled lots
    publish a price of 0, which is not a real price.
    """
    raw = pd.read_csv(io.StringIO(csv_text))
    df = raw.rename(columns=_RENAME)
    df["side"] = raw["Buy Sell"].str.strip().str.title()
    for column in ("published", "start", "end", "deadline"):
        df[column] = pd.to_datetime(df[column])

    df = df.rename(columns={f"{ic} Volume": ic for ic in INTERCONNECTORS})
    df[list(INTERCONNECTORS)] = df[list(INTERCONNECTORS)].fillna(0.0)
    interconnector_total = df[list(INTERCONNECTORS)].sum(axis=1)
    reported = df["reported_cleared_mw"].fillna(0.0)
    df["cleared_mw"] = reported.where(reported > 0, interconnector_total)

    df["traded"] = (df["cleared_mw"] > 0) & df["clearing_price"].notna()
    df["date"] = df["start"].dt.normalize()
    df["hour"] = df["start"].dt.hour
    df["weekday"] = df["start"].dt.day_of_week
    df["qualified_set"] = df["qualified"].str.split("/").map(frozenset)
    df["notes"] = df["notes"].astype("object").fillna("")
    return df.drop(columns="Buy Sell").sort_values("start", ignore_index=True)


def load(timeout: float = 60) -> Dataset:
    """Download the latest data, falling back to the last good copy on failure."""
    fetched_at = datetime.now(timezone.utc)
    try:
        response = requests.get(DUMP_URL, timeout=timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        lots = clean(response.text)
    except (requests.RequestException, ValueError, KeyError) as error:
        if not CACHE_PATH.exists():
            raise
        modified = datetime.fromtimestamp(CACHE_PATH.stat().st_mtime, timezone.utc)
        lots = clean(CACHE_PATH.read_text(encoding="utf-8"))
        return Dataset(lots, modified, stale_reason=str(error))

    CACHE_PATH.parent.mkdir(exist_ok=True)
    CACHE_PATH.write_text(response.text, encoding="utf-8")
    return Dataset(lots, fetched_at)
