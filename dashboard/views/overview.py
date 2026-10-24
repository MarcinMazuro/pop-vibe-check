"""Overview: headline numbers and sentiment over time, per source."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
from dashboard import charts, metrics, queries

GRAINS = {"Dzień": "day", "Tydzień": "week", "Miesiąc": "month"}

by_period = queries.sentiment_by_period()
events = queries.sentiment_by_event()
p = charts.palette()

st.title("Sentyment w czasie")
st.caption(
    "Udział komentarzy pozytywnych minus negatywnych (net sentiment, od −1 do 1), "
    f"źródło: `{queries.REPORTING_DATASET}.v_sentiment_by_period`."
)

# --- Filters, one row above the charts --------------------------------------
all_sources = charts.ordered_sources(by_period["source"].unique().tolist())
f1, f2, f3, f4 = st.columns([3, 2, 2, 2], vertical_alignment="bottom")
sources = f1.multiselect(
    "Źródła", all_sources, default=all_sources, format_func=charts.source_label
)
grain_name = f2.segmented_control(
    "Okres", list(GRAINS), default="Tydzień", selection_mode="single"
)
grain = GRAINS[grain_name or "Tydzień"]
min_records = f3.number_input(
    "Min. rekordów w punkcie",
    min_value=0,
    max_value=1000,
    value=20,
    step=10,
    help=(
        "Okresy z mniejszą liczbą rekordów nie są rysowane na wykresie "
        "sentymentu: przy kilku komentarzach jeden głos przesuwa wynik "
        "o dziesiątki punktów."
    ),
)
show_events = f4.toggle("Okna wydarzeń", value=True)

if not sources:
    st.info("Wybierz co najmniej jedno źródło.")
    st.stop()

selected = by_period[by_period["source"].isin(sources)]

# --- Headline numbers --------------------------------------------------------
# Every record is in exactly one month, so the month rows' counts sum to the
# whole selection.
total = metrics.totals(selected[selected["grain"] == "month"])
k1, k2, k3, k4 = st.columns(4)
k1.metric("Rekordy", f"{int(total['records']):,}".replace(",", " "))
k2.metric("Net sentiment", f"{total['net_sentiment']:+.3f}")
k3.metric("Pozytywne", f"{total['positive_share']:.1%}")
k4.metric("Negatywne", f"{total['negative_share']:.1%}")

# The view's periods span all sources; trim them to the selected sources'
# first and last record, so YouTube alone does not run on into empty months.
series = selected[selected["grain"] == grain]
active = series.loc[series["records"] > 0, "period"]
series = series[series["period"].between(active.min(), active.max())]
# 'general' is everything outside the event windows, not a window itself.
windows = events[events["event_tag"] != "general"]


def _event_bands(fig: go.Figure, y_top: float) -> None:
    """Shade each lifecycle event's window; a marker on top names it on hover."""
    for row in windows.itertuples():
        fig.add_vrect(
            x0=row.first_record_utc,
            x1=row.last_record_utc,
            fillcolor=p.event_band,
            line_width=0,
            layer="below",
        )
    fig.add_trace(
        go.Scatter(
            x=windows["first_record_utc"]
            + (windows["last_record_utc"] - windows["first_record_utc"]) / 2,
            y=[y_top] * len(windows),
            mode="markers",
            marker={"symbol": "triangle-down", "size": 9, "color": p.muted},
            text=[charts.event_label(t) for t in windows["event_tag"]],
            customdata=windows[["records"]],
            hovertemplate=(
                "<b>%{text}</b><br>%{customdata[0]:,} rekordów<extra></extra>"
            ),
            showlegend=False,
        )
    )


# --- Net sentiment over time ---------------------------------------------------
st.subheader("Net sentiment")
fig = go.Figure()
if show_events:
    _event_bands(fig, y_top=1.08)
for source in charts.ordered_sources(series["source"].unique().tolist()):
    s = series[series["source"] == source].sort_values("period")
    # Thin periods become gaps instead of being dropped, so the line does not
    # bridge months without data.
    net = s["net_sentiment"].where(s["records"] >= min_records)
    fig.add_trace(
        go.Scatter(
            x=s["period"],
            y=net,
            name=charts.source_label(source),
            mode="lines+markers",
            connectgaps=False,
            line={"color": p.sources.get(source), "width": 2},
            marker={"size": 4 if grain == "day" else 8},
            customdata=s[["records", "positive_share", "negative_share"]],
            hovertemplate=(
                "%{y:+.3f} · %{customdata[0]:,} rek. · "
                "poz. %{customdata[1]:.0%} / neg. %{customdata[2]:.0%}"
            ),
        )
    )
fig.add_hline(y=0, line={"color": p.axis, "width": 1})
fig.update_yaxes(range=[-1.05, 1.15], tickformat="+.1f", title="net sentiment")
fig.update_layout(hovermode="x unified")
charts.show(charts.style(fig, height=420))

# --- Volume ----------------------------------------------------------------------
st.subheader("Liczba rekordów")
fig = go.Figure()
for source in charts.ordered_sources(series["source"].unique().tolist()):
    s = series[series["source"] == source].sort_values("period")
    fig.add_trace(
        go.Bar(
            x=s["period"],
            y=s["records"],
            name=charts.source_label(source),
            marker={
                "color": p.sources.get(source),
                "line": {"width": 0},
                "cornerradius": 4,
            },
            hovertemplate="%{y:,} rekordów",
        )
    )
fig.update_layout(
    barmode="stack", bargap=0.15, hovermode="x unified", legend_traceorder="normal"
)
fig.update_yaxes(title="rekordy")
charts.show(charts.style(fig, height=300))

with st.expander("Tabela"):
    table = series.assign(source=series["source"].map(charts.source_label))
    st.dataframe(
        table[
            [
                "period",
                "source",
                "records",
                "net_sentiment",
                "positive_share",
                "negative_share",
                "avg_confidence",
            ]
        ].sort_values(["period", "source"]),
        hide_index=True,
        width="stretch",
        column_config={
            "period": st.column_config.DateColumn("Okres"),
            "source": "Źródło",
            "records": st.column_config.NumberColumn("Rekordy", format="%d"),
            "net_sentiment": st.column_config.NumberColumn("Net", format="%+.3f"),
            "positive_share": st.column_config.NumberColumn(
                "Pozytywne", format="percent"
            ),
            "negative_share": st.column_config.NumberColumn(
                "Negatywne", format="percent"
            ),
            "avg_confidence": st.column_config.NumberColumn(
                "Śr. pewność", format="%.3f"
            ),
        },
    )
