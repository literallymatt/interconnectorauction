# GB interconnector auctions

An interactive dashboard for NESO's
[Interconnector Requirement and Auction Summary](https://www.neso.energy/data-portal/interconnector-requirement-and-auction-summary-data)
data. It downloads the latest data straight from the NESO portal, with no API key.

## Run it

Needs [uv](https://docs.astral.sh/uv/) (or install the dependencies in `pyproject.toml` with Python 3.10+).

```bash
uv run streamlit run app.py
```

Tests: `uv run pytest`

## What you can control

| Control | Options |
|---|---|
| Delivery dates | Last 7/30/90 days, last 12 months, this year, all, custom range |
| Delivery hours | All day, peaks, daytime, overnight, or any set of hours |
| Days of week | Any combination |
| Direction | Buy, Sell, or both (shown side by side, never blended) |
| Interconnectors | Any of IFA1, BritNed, Nemo Link, IFA2, ElecLink, Viking Link |
| Show | Aggregate, or by interconnector |
| Price | Clearing, volume-weighted average, best, default |
| Statistic | Maximum, minimum, mean, volume-weighted mean, median |
| Per | Individual lot, day, week, month, quarter, year, whole selected period |

The tabs cover prices over time, cleared volume, an interconnector scorecard
(eligibility, win rate, share, prices), delivery-hour heatmaps, and the underlying
lots. Tables can be exported as CSV.

## How the numbers are built

- **Unfilled lots are left out of price statistics.** They publish a price of £0, which is not a real price.
- **Buy and sell lots stay separate.** Their prices run in opposite commercial directions, so averaging them is meaningless.
- **Interconnector prices are lot prices.** NESO publishes one set of prices per lot, so an interconnector's price is that of the lots where it won volume. Interconnectors that share a lot show the same price, and volume-weighted figures use each interconnector's own volume.
- **Cleared volume** is NESO's reported lot total, or the sum of the per-interconnector volumes where that is blank. On about 130 lots the two disagree or no split exists, so the aggregate view (lot totals) can differ slightly from the sum of the interconnector view.
- **Volumes in MWh** treat each lot as a one-hour block, which virtually all lots are.
- **Delivery date and time** come from each lot's start time, as NESO publishes it.

## Layout

- `ic_auctions/data.py`: download and cleaning, with the last good copy kept in `.cache/`
- `ic_auctions/analysis.py`: filters and aggregations, free of UI code
- `app.py`: the Streamlit interface
