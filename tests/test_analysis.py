from datetime import date

import pandas as pd
import pytest

from ic_auctions import analysis as a
from ic_auctions.data import clean

HEADER = (
    "Published DateTime,Notes,Auction ID,Auction Lot ID,Buy Sell,Volume Required,"
    "Qualified IC,Start Time,End Time,Bid Deadline,Default Price,Clearing Price,"
    "Best Price,VWA Price,Cleared Volume,Total Bid Volume,IFA1 Volume,BN Volume,"
    "NEMO Volume,IFA2 Volume,EL Volume,VKL Volume,System Flag\n"
)


def row(lot, side, start, clearing, cleared, ifa1="", bn="", required=100, qualified="IFA1/BN"):
    start = pd.Timestamp(start)
    return (
        f"2024-01-01T00:00:00,,A,{lot},{side},{required},{qualified},{start.isoformat()},"
        f"{(start + pd.Timedelta(hours=1)).isoformat()},2024-01-01T00:00:00,50,"
        f"{clearing},{clearing},{clearing},{cleared},200,{ifa1},{bn},,,,,\n"
    )


@pytest.fixture
def lots():
    return clean(HEADER + "".join([
        row("buy1", "Buy", "2024-01-01 10:00", 100, 100, ifa1=100),
        row("buy2", "BUY", "2024-01-01 11:00", 300, "", ifa1=100, bn=200, required=300),
        row("unfilled", "Buy", "2024-01-01 12:00", 0, 0),
        row("sell1", "Sell", "2024-01-02 10:00", -20, 50, bn=50, qualified="BN"),
    ]))


def everything(**changes):
    values = dict(first_date=date(2024, 1, 1), last_date=date(2024, 1, 31),
                  hours=range(24), weekdays=range(7), sides=("Buy", "Sell"),
                  interconnectors=("IFA1", "BN", "NEMO", "IFA2", "EL", "VKL"))
    return a.Filters(**{**values, **changes})


def test_direction_case_normalised_and_blank_cleared_volume_rebuilt(lots):
    assert set(lots["side"]) == {"Buy", "Sell"}
    assert lots.set_index("lot_id").at["buy2", "cleared_mw"] == 300


def test_unfilled_zero_price_does_not_count_as_a_price(lots):
    frame = a.trades(lots, ("IFA1", "BN"), individual=False)
    buy = a.summarise(frame[frame.side == "Buy"], "clearing_price", "Minimum", "D")
    assert buy["value"].tolist() == [100]
    assert buy["lots"].tolist() == [2]


def test_volume_weighted_mean_differs_from_mean(lots):
    frame = a.trades(lots, ("IFA1", "BN"), individual=False)
    buy = frame[frame.side == "Buy"]
    weighted = a.summarise(buy, "clearing_price", "Volume-weighted mean", "D")
    plain = a.summarise(buy, "clearing_price", "Mean", "D")
    assert weighted["value"].iloc[0] == pytest.approx(250)
    assert plain["value"].iloc[0] == pytest.approx(200)


def test_individual_view_weights_by_each_interconnectors_own_volume(lots):
    frame = a.trades(lots[lots.side == "Buy"], ("IFA1", "BN"), individual=True)
    out = a.summarise(frame, "clearing_price", "Volume-weighted mean", "ALL")
    prices = out.set_index("interconnector")["value"]
    assert prices["IFA1"] == pytest.approx(200)
    assert prices["BritNed"] == pytest.approx(300)


def test_maximum_records_the_delivery_hour_of_the_peak(lots):
    frame = a.trades(lots[lots.side == "Buy"], ("IFA1", "BN"), individual=False)
    out = a.summarise(frame, "clearing_price", "Maximum", "D")
    assert out["value"].iloc[0] == 300
    assert out["extreme_at"].iloc[0] == pd.Timestamp("2024-01-01 11:00")


def test_filters_by_hour_direction_and_eligibility(lots):
    assert set(a.select_lots(lots, everything(hours=[11]))["lot_id"]) == {"buy2"}
    assert set(a.select_lots(lots, everything(sides=["Sell"]))["lot_id"]) == {"sell1"}
    assert a.select_lots(lots, everything(interconnectors=["NEMO"])).empty


def test_subset_of_interconnectors_only_counts_their_volume(lots):
    frame = a.trades(lots[lots.side == "Buy"], ("BN",), individual=False)
    assert frame["volume_mw"].tolist() == [200]


def test_scorecard_win_rate_and_share(lots):
    card = a.scorecard(lots[lots.side == "Buy"], ("IFA1", "BN"))
    ifa1 = card.set_index("Interconnector").loc["IFA1"]
    assert ifa1["Lots won"] == 2
    assert ifa1["Win rate"] == pytest.approx(2 / 3)
    assert ifa1["Volume share"] == pytest.approx(0.5)
