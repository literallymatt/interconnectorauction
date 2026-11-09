"""Streamlit dashboard for NESO interconnector auctions. Run: streamlit run app.py"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ic_auctions import analysis as a
from ic_auctions import data as d

st.set_page_config(page_title="GB interconnector auctions", page_icon="⚡", layout="wide")

# Fixed per interconnector, so a colour never changes when filters change.
COLOURS = dict(zip(
    d.INTERCONNECTORS.values(),
    ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"],
))
COLOURS[a.AGGREGATE_LABEL] = "#2a78d6"
SEQUENTIAL = [[0, "#e6f0fb"], [0.5, "#2a78d6"], [1, "#0d3a73"]]
DIVERGING = [[0, "#b8431a"], [0.5, "#efeeea"], [1, "#2a78d6"]]
GRID = "rgba(0,0,0,0.08)"
HOUR_PRESETS = {
    "All day": list(range(24)),
    "Evening peak (16–19)": [16, 17, 18],
    "Morning peak (07–10)": [7, 8, 9],
    "Daytime (07–23)": list(range(7, 23)),
    "Overnight (23–07)": [23, 0, 1, 2, 3, 4, 5, 6],
}


@st.cache_data(ttl=timedelta(minutes=30), show_spinner="Downloading NESO auction data…")
def load_dataset() -> d.Dataset:
    return d.load()


def date_window(lots: pd.DataFrame):
    earliest, latest = lots["date"].min().date(), lots["date"].max().date()
    preset = st.selectbox("Delivery dates", [
        "Last 7 days", "Last 30 days", "Last 90 days", "Last 12 months",
        "This year", "All available", "Custom range"], index=2)
    days = {"Last 7 days": 6, "Last 30 days": 29, "Last 90 days": 89, "Last 12 months": 364}
    if preset in days:
        return max(earliest, latest - timedelta(days=days[preset])), latest
    if preset == "This year":
        return latest.replace(month=1, day=1), latest
    if preset == "All available":
        return earliest, latest
    chosen = st.date_input("Date range", value=(latest - timedelta(days=30), latest),
                           min_value=earliest, max_value=latest)
    if len(chosen) == 2:
        return chosen
    st.caption("Pick an end date to complete the range.")
    return chosen[0], chosen[0]


def sidebar(lots: pd.DataFrame):
    with st.sidebar:
        st.header("Delivery window")
        first, last = date_window(lots)

        preset = st.selectbox("Delivery hours", [*HOUR_PRESETS, "Custom hours"])
        hours = HOUR_PRESETS.get(preset)
        if hours is None:
            hours = st.pills("Hour starting", list(range(24)), default=list(range(24)),
                             selection_mode="multi", format_func=lambda h: f"{h:02d}")
        weekdays = st.pills("Days of week", list(range(7)), default=list(range(7)),
                            selection_mode="multi", format_func=a.WEEKDAYS.__getitem__)

        st.header("Lots")
        direction = st.segmented_control("Direction", ["Both", "Buy", "Sell"], default="Both")
        sides = ["Buy", "Sell"] if direction in ("Both", None) else [direction]
        interconnectors = st.pills(
            "Interconnectors", list(d.INTERCONNECTORS), default=list(d.INTERCONNECTORS),
            selection_mode="multi", format_func=d.INTERCONNECTORS.__getitem__)

        st.header("Measure")
        view = st.segmented_control("Show", ["Aggregate", "By interconnector"],
                                    default="Aggregate")
        price_label = st.selectbox("Price", list(a.PRICE_MEASURES))
        statistic = st.selectbox("Statistic", a.STATISTICS)
        period = st.selectbox("Per", list(a.PERIODS), index=1)

        st.divider()
        if st.button("Check for new data", width="stretch"):
            load_dataset.clear()
            st.rerun()

    filters = a.Filters(first, last, hours, weekdays, sides, interconnectors)
    return filters, view != "Aggregate", price_label, statistic, period


def base_layout(fig: go.Figure, title: str, y_title: str, legend: bool, height: int = 340):
    fig.update_layout(
        title=dict(text=title, font=dict(size=15)),
        height=height, margin=dict(l=10, r=10, t=64, b=10),
        showlegend=legend, plot_bgcolor="white",
        legend=dict(orientation="h", y=1.02, x=0, yanchor="bottom", title=None,
                    traceorder="normal"),
        hoverlabel=dict(bgcolor="white", font_color="#0b0b0b"),
    )
    fig.update_xaxes(showgrid=False, linecolor="rgba(0,0,0,0.25)")
    fig.update_yaxes(title=y_title, gridcolor=GRID, zerolinecolor="rgba(0,0,0,0.3)")


def regular_buckets(series: pd.DataFrame, buckets: pd.DatetimeIndex) -> pd.DataFrame:
    """Insert empty periods so a line breaks where no lots traded."""
    return series.set_index("bucket").reindex(buckets).rename_axis("bucket").reset_index()


def all_buckets(frame: pd.DataFrame, freq: str) -> pd.DatetimeIndex:
    span = frame["bucket"].min(), frame["bucket"].max()
    return pd.period_range(*span, freq=freq).to_timestamp()


def price_chart(side: str, summary: pd.DataFrame, freq: str | None, title: str):
    fig = go.Figure()
    series_names = [n for n in COLOURS if n in set(summary["interconnector"])]
    for name in series_names:
        series = summary[summary["interconnector"] == name].sort_values("bucket")
        if freq == "ALL":
            continue
        if freq is not None:
            series = regular_buckets(series, all_buckets(summary, freq))
        fig.add_trace(go.Scatter(
            x=series["bucket"], y=series["value"], name=name,
            mode="markers" if freq is None else "lines+markers",
            connectgaps=False,
            line=dict(color=COLOURS[name], width=2),
            marker=dict(color=COLOURS[name], size=8 if freq is None else 6,
                        line=dict(color="white", width=1)),
            customdata=series[["lots", "volume_mwh"]],
            hovertemplate=(f"{name}: £%{{y:,.2f}}/MWh · %{{customdata[0]:.0f}} lots · "
                           "%{customdata[1]:,.0f} MWh<extra></extra>"),
        ))
    if freq == "ALL":
        ordered = summary.sort_values("value")
        fig.add_trace(go.Bar(
            y=ordered["interconnector"], x=ordered["value"], orientation="h",
            marker=dict(color=[COLOURS[n] for n in ordered["interconnector"]],
                        cornerradius=4),
            text=[f"£{v:,.2f}" for v in ordered["value"]], textposition="auto",
            hovertemplate="%{y}: £%{x:,.2f}/MWh<extra></extra>",
        ))
        base_layout(fig, f"{side} · {title}", "", False, 110 + 44 * len(ordered))
        fig.update_xaxes(title="£/MWh", showgrid=True, gridcolor=GRID)
        fig.update_yaxes(showgrid=False)
    else:
        base_layout(fig, f"{side} · {title}", "£/MWh", len(series_names) > 1)
        fig.update_layout(hovermode="closest" if freq is None else "x unified")
    return fig


def volume_chart(side: str, frame: pd.DataFrame, freq: str | None):
    if freq in (None, "ALL"):
        freq = "D"  # hourly bars are unreadable, and one bar says nothing over time
    summary = a.summarise(frame, "clearing_price", "Mean", freq)
    fig = go.Figure()
    names = [n for n in COLOURS if n in set(summary["interconnector"])]
    for name in names:
        series = summary[summary["interconnector"] == name]
        fig.add_trace(go.Bar(
            x=series["bucket"], y=series["volume_mwh"], name=name,
            marker=dict(color=COLOURS[name], line=dict(color="white", width=1)),
            hovertemplate=f"{name}: %{{y:,.0f}} MWh<extra></extra>",
        ))
    base_layout(fig, f"{side} · cleared volume", "MWh", len(names) > 1)
    fig.update_layout(barmode="stack", hovermode="x unified")
    return fig


def heatmap(side: str, frame: pd.DataFrame, price: str, statistic: str, axis: str, title: str):
    matrix = a.profile(frame, price, statistic, axis)
    labels = {"Day of week": a.WEEKDAYS, "Month": a.MONTHS}.get(
        axis, [str(c) for c in matrix.columns])
    has_negative = matrix.min().min() < 0
    limit = max(abs(matrix.quantile(0.98).max()), abs(matrix.quantile(0.02).min()), 1)
    fig = go.Figure(go.Heatmap(
        z=matrix.to_numpy(), x=labels, y=[f"{h:02d}:00" for h in matrix.index],
        colorscale=DIVERGING if has_negative else SEQUENTIAL,
        zmin=-limit if has_negative else None, zmax=limit, xgap=2, ygap=2,
        colorbar=dict(title="£/MWh", thickness=12),
        hovertemplate="%{x}, %{y}: £%{z:,.2f}/MWh<extra></extra>",
    ))
    base_layout(fig, f"{side} · {title}", "Delivery hour", False, 560)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return fig


def show_chart(fig: go.Figure, key: str) -> None:
    st.plotly_chart(fig, width="stretch", key=key, config={"displaylogo": False})


def download(frame: pd.DataFrame, name: str, key: str) -> None:
    st.download_button("Download CSV", frame.to_csv(index=False), name, "text/csv", key=key)


def headline(selected: pd.DataFrame, frame: pd.DataFrame, price: str, statistic: str,
             price_label: str, sides: list[str]) -> None:
    short = "VWA" if price == "vwa_price" else price_label.split()[0].lower()
    label = f"{statistic} {short}, £/MWh"
    for side in sides:
        side_lots = selected[selected["side"] == side]
        side_frame = frame[frame["side"] == side]
        columns = st.columns(5)
        columns[0].markdown(f"**{side}**")
        columns[1].metric("Lots traded", f"{side_frame['lot_id'].nunique():,}")
        columns[2].metric("Cleared", f"{side_frame['volume_mw'].sum() / 1000:,.1f} GWh")
        rate = a.fill_rate(side_lots)
        columns[3].metric("Requirement filled", f"{rate:.0%}" if rate is not None else "–")
        if side_frame.empty:
            columns[4].metric(label, "–")
            continue
        pooled = side_frame.assign(side_group=side)
        value = a.apply_statistic(pooled, price, statistic, ["side_group"]).iloc[0]
        columns[4].metric(label, f"£{value:,.2f}")


def main() -> None:
    st.title("GB interconnector auctions")
    try:
        dataset = load_dataset()
    except Exception as error:  # nothing to show at all without data
        st.error(f"Could not download the NESO data: {error}")
        st.stop()

    lots = dataset.lots
    filters, individual, price_label, statistic, period = sidebar(lots)
    price, freq = a.PRICE_MEASURES[price_label], a.PERIODS[period]

    st.caption(
        f"[NESO data portal]({d.PORTAL_URL}) · {len(lots):,} lots, delivery "
        f"{lots['start'].min():%d %b %Y} to {lots['start'].max():%d %b %Y} · "
        f"checked {dataset.fetched_at:%d %b %Y %H:%M} UTC · refreshes every 30 minutes"
    )
    if dataset.stale_reason:
        st.warning(f"Showing the last saved copy; the download failed: {dataset.stale_reason}")
    if not (filters.hours and filters.weekdays and filters.interconnectors):
        st.info("Choose at least one delivery hour, weekday and interconnector.")
        st.stop()

    selected = a.select_lots(lots, filters)
    frame = a.trades(selected, filters.interconnectors, individual)
    sides = [s for s in ("Buy", "Sell") if s in filters.sides]
    if frame.empty:
        st.info("No lots traded in this selection. Try widening the filters.")
        st.stop()

    headline(selected, a.trades(selected, filters.interconnectors, False),
             price, statistic, price_label, sides)
    scope = "over the whole selected period" if freq == "ALL" else f"per {period.lower()}"
    title = f"{statistic.lower()} {price_label.lower()} {scope}"
    if freq is None:
        title = f"{price_label.lower()} by delivery hour"
    summary = a.summarise(frame, price, statistic, freq)

    tabs = st.tabs(["Prices", "Volumes", "Interconnectors", "Time of day", "Lots"])
    with tabs[0]:
        for side in sides:
            part = summary[summary["side"] == side]
            if part.empty:
                st.info(f"No {side.lower()} lots traded in this selection.")
                continue
            show_chart(price_chart(side, part, freq, title), f"price-{side}")
        table = summary.rename(columns={
            "side": "Direction", "interconnector": "Interconnector", "bucket": "Period start",
            "value": f"{statistic} £/MWh", "lots": "Lots", "volume_mwh": "Cleared MWh",
            "extreme_at": "Delivery hour of extreme",
        })
        if statistic not in ("Maximum", "Minimum"):
            table = table.drop(columns="Delivery hour of extreme")
        with st.expander("Data table"):
            st.dataframe(table, hide_index=True, width="stretch")
            download(table, "interconnector_prices.csv", "dl-prices")

    with tabs[1]:
        for side in sides:
            part = frame[frame["side"] == side]
            if not part.empty:
                show_chart(volume_chart(side, part, freq), f"volume-{side}")
        if freq is None or freq == "ALL":
            st.caption("Volumes are shown per day for this period setting.")

    with tabs[2]:
        card = a.scorecard(selected, filters.interconnectors)
        st.dataframe(card, hide_index=True, width="stretch", column_config={
            "Win rate": st.column_config.NumberColumn(format="percent"),
            "Volume share": st.column_config.NumberColumn(format="percent"),
            "Cleared MWh": st.column_config.NumberColumn(format="localized"),
            "VW avg clearing £/MWh": st.column_config.NumberColumn(format="%.2f"),
            "Max clearing £/MWh": st.column_config.NumberColumn(format="%.2f"),
            "Min clearing £/MWh": st.column_config.NumberColumn(format="%.2f"),
        })
        download(card, "interconnector_scorecard.csv", "dl-card")
        st.caption("NESO publishes prices per lot, so an interconnector's price is the "
                   "price of the lots in which it won volume.")

    with tabs[3]:
        axis = st.radio("Compare delivery hours across",
                        ["Day of week", "Month", "Year"], horizontal=True)
        pooled = a.trades(selected, filters.interconnectors, False)
        columns = st.columns(len(sides))
        for column, side in zip(columns, sides):
            part = pooled[pooled["side"] == side]
            with column:
                if part.empty:
                    st.info(f"No {side.lower()} lots traded.")
                else:
                    show_chart(heatmap(side, part, price, statistic, axis,
                                       f"{statistic.lower()} {price_label.lower()}"),
                               f"heat-{side}")

    with tabs[4]:
        codes = list(d.INTERCONNECTORS)
        columns = ["start", "side", "qualified", "required_mw", "cleared_mw", "bid_mw",
                   "default_price", "clearing_price", "best_price", "vwa_price",
                   *codes, "auction_id", "lot_id", "notes"]
        detail = selected.sort_values("start", ascending=False)[columns].rename(
            columns={"start": "Delivery start", "side": "Direction"})
        st.caption(f"{len(detail):,} lots offered, including any that did not trade.")
        st.dataframe(detail, hide_index=True, width="stretch", height=520)
        download(detail, "interconnector_lots.csv", "dl-lots")

    st.caption(
        "Buy and sell lots are kept apart because their prices are not comparable. "
        "Price statistics use traded lots only: unfilled lots publish a price of £0. "
        "Volumes treat each lot as a one-hour block. Delivery times are as NESO publishes them."
    )


main()
