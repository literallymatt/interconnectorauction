"""Filtering and aggregation. Free of any UI code so it can be unit-tested."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date

import pandas as pd

from .data import INTERCONNECTORS

AGGREGATE_LABEL = "All selected"

PRICE_MEASURES = {
    "Clearing price": "clearing_price",
    "Volume-weighted average price": "vwa_price",
    "Best price": "best_price",
    "Default price": "default_price",
}
STATISTICS = ["Maximum", "Minimum", "Mean", "Volume-weighted mean", "Median"]
PERIODS = {
    "Individual lot (hourly)": None,
    "Day": "D",
    "Week": "W",
    "Month": "M",
    "Quarter": "Q",
    "Year": "Y",
    "Whole selected period": "ALL",
}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass(frozen=True)
class Filters:
    first_date: date
    last_date: date
    hours: Collection[int]
    weekdays: Collection[int]
    sides: Collection[str]
    interconnectors: Collection[str]


def select_lots(lots: pd.DataFrame, filters: Filters) -> pd.DataFrame:
    """Lots delivering in the window that any chosen interconnector could trade."""
    chosen = frozenset(filters.interconnectors)
    mask = (
        lots["date"].between(pd.Timestamp(filters.first_date),
                             pd.Timestamp(filters.last_date))
        & lots["hour"].isin(list(filters.hours))
        & lots["weekday"].isin(list(filters.weekdays))
        & lots["side"].isin(list(filters.sides))
        & lots["qualified_set"].map(lambda qualified: bool(qualified & chosen))
    )
    return lots[mask]


def trades(lots: pd.DataFrame, interconnectors: Collection[str],
           individual: bool) -> pd.DataFrame:
    """Traded volume, as one row per lot or one per lot and interconnector.

    Prices are published per lot, so an interconnector's price is the price of
    each lot in which it won volume, weighted by the volume it won.
    """
    chosen = [ic for ic in INTERCONNECTORS if ic in set(interconnectors)]
    traded = lots[lots["traded"]]
    if individual:
        keep = [c for c in traded.columns if c not in INTERCONNECTORS]
        long = traded.melt(id_vars=keep, value_vars=chosen,
                           var_name="ic", value_name="volume_mw")
        long["interconnector"] = long["ic"].map(INTERCONNECTORS)
        return long[long["volume_mw"] > 0].drop(columns="ic")

    out = traded.copy()
    # With every interconnector chosen, use the lot total: 36 lots report a
    # cleared volume with no per-interconnector split.
    out["volume_mw"] = (out["cleared_mw"] if len(chosen) == len(INTERCONNECTORS)
                        else out[chosen].sum(axis=1))
    out["interconnector"] = AGGREGATE_LABEL
    return out[out["volume_mw"] > 0]


def add_bucket(frame: pd.DataFrame, freq: str | None) -> pd.DataFrame:
    """Attach `bucket`, the start of the period each delivery hour falls in."""
    out = frame.copy()
    if freq is None:
        out["bucket"] = out["start"]
    elif freq == "ALL":
        out["bucket"] = out["start"].min().normalize()
    else:
        out["bucket"] = out["start"].dt.to_period(freq).dt.start_time
    return out


def _weighted_mean(frame: pd.DataFrame, price: str, groups: list[str]) -> pd.Series:
    weighted = (frame[price] * frame["volume_mw"]).groupby(
        [frame[g] for g in groups]).sum()
    return weighted / frame.groupby(groups)["volume_mw"].sum()


def apply_statistic(frame: pd.DataFrame, price: str, statistic: str,
                    groups: list[str]) -> pd.Series:
    if statistic == "Volume-weighted mean":
        return _weighted_mean(frame, price, groups)
    method = {"Maximum": "max", "Minimum": "min",
              "Mean": "mean", "Median": "median"}[statistic]
    return getattr(frame.groupby(groups)[price], method)()


def summarise(frame: pd.DataFrame, price: str, statistic: str,
              freq: str | None) -> pd.DataFrame:
    """One row per direction, interconnector and period."""
    columns = ["side", "interconnector", "bucket", "value", "lots",
               "volume_mwh", "extreme_at"]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    groups = ["side", "interconnector", "bucket"]
    bucketed = add_bucket(frame, freq)
    grouped = bucketed.groupby(groups)
    result = pd.DataFrame({
        "value": apply_statistic(bucketed, price, statistic, groups),
        "lots": grouped["lot_id"].nunique(),
        "volume_mwh": grouped["volume_mw"].sum(),  # lots are 1-hour blocks
    })
    if statistic in ("Maximum", "Minimum"):
        pick = grouped[price].idxmax() if statistic == "Maximum" else grouped[price].idxmin()
        result["extreme_at"] = bucketed.loc[pick, "start"].to_numpy()
    else:
        result["extreme_at"] = pd.NaT
    return result.reset_index()[columns]


def profile(frame: pd.DataFrame, price: str, statistic: str, axis: str) -> pd.DataFrame:
    """Delivery hour by weekday, month or year, as a matrix for a heatmap."""
    out = frame.copy()
    if axis == "Year":
        out["column"] = out["start"].dt.year
        order = sorted(out["column"].unique())
    elif axis == "Month":
        out["column"] = out["start"].dt.month
        order = list(range(1, 13))
    else:
        out["column"] = out["weekday"]
        order = list(range(7))
    values = apply_statistic(out, price, statistic, ["hour", "column"]).unstack("column")
    return values.reindex(index=range(24), columns=order)


def scorecard(lots: pd.DataFrame, interconnectors: Collection[str]) -> pd.DataFrame:
    """How often each interconnector was eligible, won, and at what price."""
    rows = []
    for side, side_lots in lots.groupby("side"):
        traded = side_lots[side_lots["traded"]]
        side_total = sum(traded[ic].sum() for ic in interconnectors)
        for ic in (ic for ic in INTERCONNECTORS if ic in set(interconnectors)):
            eligible = side_lots["qualified_set"].map(lambda q: ic in q)
            won = traded[traded[ic] > 0]
            volume = won[ic].sum()
            rows.append({
                "Direction": side,
                "Interconnector": INTERCONNECTORS[ic],
                "Lots eligible": int(eligible.sum()),
                "Lots won": len(won),
                "Win rate": len(won) / eligible.sum() if eligible.sum() else None,
                "Cleared MWh": volume,
                "Volume share": volume / side_total if side_total else None,
                "VW avg clearing £/MWh": (
                    (won["clearing_price"] * won[ic]).sum() / volume if volume else None),
                "Max clearing £/MWh": won["clearing_price"].max(),
                "Min clearing £/MWh": won["clearing_price"].min(),
            })
    return pd.DataFrame(rows)


def fill_rate(lots: pd.DataFrame) -> float | None:
    """Share of the requirement that cleared, across all lots offered."""
    required = lots["required_mw"].sum()
    return float(lots["cleared_mw"].sum() / required) if required else None
