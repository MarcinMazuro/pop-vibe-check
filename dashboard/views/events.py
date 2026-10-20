"""Events: how each lifecycle event landed, per source."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
from dashboard import charts, metrics, queries
from plotly.subplots import make_subplots

daily = queries.sentiment_daily()
events = queries.sentiment_by_event()
p = charts.palette()

st.title("Wydarzenia")
st.caption(
    "Sentyment w oknie każdego wydarzenia, osobno dla każdego źródła. "
    "Wydarzenia ułożone chronologicznie."
)

all_sources = charts.ordered_sources(daily["source"].unique().tolist())
f1, f2 = st.columns([3, 2], vertical_alignment="bottom")
sources = f1.multiselect(
    "Źródła", all_sources, default=all_sources, format_func=charts.source_label
)
include_general = f2.toggle(
    "Pokaż „general”",
    value=False,
    help=(
        "Tag general to wszystko poza oknami wydarzeń: ~78% rekordów. "
        "Ukryty domyślnie, żeby nie zagłuszał wydarzeń."
    ),
)

if not sources:
    st.info("Wybierz co najmniej jedno źródło.")
    st.stop()

selected = daily[daily["source"].isin(sources)]
if not include_general:
    selected = selected[selected["event_tag"] != "general"]

by_event = metrics.rollup(selected, ["event_tag", "source"])

# Chronological order from the event view; 'general' (absent there) goes last.
order = [t for t in events["event_tag"] if t in set(by_event["event_tag"])]
order += sorted(set(by_event["event_tag"]) - set(order))

# --- Where the sources disagree -----------------------------------------------
divergence = metrics.source_divergence(by_event)
if not divergence.empty:
    top = divergence.iloc[0]
    st.info(
        f"**Największa rozbieżność źródeł: {charts.event_label(top['event_tag'])}** — "
        f"{charts.source_label(top['high_source'])} {top['high_net']:+.3f}, "
        f"{charts.source_label(top['low_source'])} {top['low_net']:+.3f} "
        f"(różnica {top['gap']:.3f}). Analiza jednego źródła dałaby tu inny obraz."
    )

# --- Net sentiment per event --------------------------------------------------
st.subheader("Net sentiment per wydarzenie")
labels = {t: charts.event_label(t) for t in order}
fig = go.Figure()
for source in charts.ordered_sources(by_event["source"].unique().tolist()):
    s = by_event[by_event["source"] == source].set_index("event_tag").reindex(order)
    fig.add_trace(
        go.Bar(
            y=[labels[t] for t in order],
            x=s["net_sentiment"],
            name=charts.source_label(source),
            orientation="h",
            marker={"color": p.sources.get(source), "cornerradius": 4},
            customdata=s[["records", "positive_share", "negative_share"]],
            hovertemplate=(
                "<b>%{y}</b><br>net %{x:+.3f} · %{customdata[0]:,} rek.<br>"
                "poz. %{customdata[1]:.0%} / neg. %{customdata[2]:.0%}"
                f"<extra>{charts.source_label(source)}</extra>"
            ),
        )
    )
fig.add_vline(x=0, line={"color": p.axis, "width": 1})
fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08)
fig.update_xaxes(range=[-1, 1], tickformat="+.1f", title="net sentiment")
fig.update_yaxes(autorange="reversed", showgrid=False)
charts.show(charts.style(fig, height=max(320, 56 * len(order))))

# --- Sentiment split ----------------------------------------------------------
st.subheader("Rozkład sentymentu")
facet_sources = charts.ordered_sources(by_event["source"].unique().tolist())
fig = make_subplots(
    rows=1,
    cols=len(facet_sources),
    shared_yaxes=True,
    horizontal_spacing=0.04,
    subplot_titles=[charts.source_label(s) for s in facet_sources],
)
for col, source in enumerate(facet_sources, start=1):
    s = by_event[by_event["source"] == source].set_index("event_tag").reindex(order)
    for kind in ("positive", "neutral", "negative"):
        fig.add_trace(
            go.Bar(
                y=[labels[t] for t in order],
                x=s[f"{kind}_share"],
                name=charts.SENTIMENT_LABELS[kind],
                legendgroup=kind,
                showlegend=col == 1,
                orientation="h",
                marker={
                    "color": p.sentiment[kind],
                    # A surface-coloured edge keeps a 2px gap between segments.
                    "line": {"color": p.surface, "width": 1},
                },
                customdata=s[[f"{kind}"]],
                hovertemplate=(
                    "<b>%{y}</b><br>%{x:.1%} · %{customdata[0]:,} rek."
                    f"<extra>{charts.SENTIMENT_LABELS[kind]}</extra>"
                ),
            ),
            row=1,
            col=col,
        )
fig.update_layout(barmode="stack", bargap=0.3)
fig.update_xaxes(range=[0, 1], tickformat=".0%")
fig.update_yaxes(autorange="reversed", showgrid=False)
for annotation in fig.layout.annotations:
    annotation.font.color = p.ink
charts.style(fig, height=max(320, 40 * len(order)) + 32)
# Lift the legend clear of the subplot titles.
fig.update_layout(legend_y=1.12, margin_t=80)
charts.show(fig)

# --- Table --------------------------------------------------------------------
with st.expander("Tabela per wydarzenie (wszystkie źródła razem)"):
    st.dataframe(
        events.assign(event_tag=events["event_tag"].map(charts.event_label)),
        hide_index=True,
        width="stretch",
        column_config={
            "event_tag": "Wydarzenie",
            "first_record_utc": st.column_config.DatetimeColumn(
                "Pierwszy rekord", format="YYYY-MM-DD HH:mm"
            ),
            "last_record_utc": st.column_config.DatetimeColumn(
                "Ostatni rekord", format="YYYY-MM-DD HH:mm"
            ),
            "records": st.column_config.NumberColumn("Rekordy", format="%d"),
            "sources": "Źródła",
            "distinct_authors": st.column_config.NumberColumn("Autorzy", format="%d"),
            "positive": None,
            "neutral": None,
            "negative": None,
            "positive_share": st.column_config.NumberColumn(
                "Pozytywne", format="percent"
            ),
            "net_sentiment": st.column_config.NumberColumn("Net", format="%+.3f"),
        },
    )
