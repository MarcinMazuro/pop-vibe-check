"""Events: how each lifecycle event landed, per source."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from dashboard import charts, queries
from plotly.subplots import make_subplots

by_event_source = queries.sentiment_by_event_source()
events = queries.sentiment_by_event()
p = charts.palette()

st.title("Wydarzenia")
st.caption(
    "Sentyment w oknie każdego wydarzenia, osobno dla każdego źródła. "
    "Wydarzenia ułożone chronologicznie."
)

all_sources = charts.ordered_sources(by_event_source["source"].unique().tolist())
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

by_event = by_event_source[by_event_source["source"].isin(sources)]
if not include_general:
    by_event = by_event[by_event["event_tag"] != "general"]

# Chronological order from the event view; 'general' (absent there) goes last.
order = [t for t in events["event_tag"] if t in set(by_event["event_tag"])]
order += sorted(set(by_event["event_tag"]) - set(order))

# --- Where the sources disagree -----------------------------------------------
# The view ranks all sources; its gap holds for the selection as long as both
# ends of it are selected. Otherwise the event is left out rather than shown
# with a gap the selection does not have.
divergence = queries.source_divergence()
divergence = divergence[
    divergence["high_source"].isin(sources)
    & divergence["low_source"].isin(sources)
    & divergence["event_tag"].isin(by_event["event_tag"])
]
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

# --- Event effect against the source's baseline ------------------------------
st.subheader("Efekt wydarzenia")
st.caption(
    "Okno wydarzenia na tle wszystkich pozostałych rekordów tego samego źródła: "
    "na Steamie to głównie recenzje spoza okien (general), YouTube nie ma "
    "general, więc tłem są jego pozostałe wydarzenia. Mnożnik wolumenu porównuje "
    "rekordy na dzień z danymi; na YouTube zależy też od doboru zebranych filmów."
)

# The baseline is the whole source, whatever the 'general' toggle hides; it
# never mixes sources, so filtering the rows by source is exact.
lift = queries.event_lift()
lift = lift[lift["source"].isin(sources)]
lift_order = [t for t in order if t in set(lift["event_tag"])]

drops = lift.dropna(subset=["net_lift"])
if not drops.empty and drops["net_lift"].min() < 0:
    worst = drops.loc[drops["net_lift"].idxmin()]
    st.info(
        f"**Największy spadek nastrojów: {charts.event_label(worst['event_tag'])}** "
        f"({charts.source_label(worst['source'])}) — net "
        f"{worst['net_sentiment']:+.3f} wobec {worst['baseline_net_sentiment']:+.3f} "
        f"w tle (zmiana {worst['net_lift']:+.3f})."
    )

fig = make_subplots(
    rows=1,
    cols=2,
    shared_yaxes=True,
    horizontal_spacing=0.05,
    subplot_titles=["Zmiana net sentimentu względem tła", "Mnożnik wolumenu"],
)
for source in charts.ordered_sources(lift["source"].unique().tolist()):
    s = lift[lift["source"] == source].set_index("event_tag").reindex(lift_order)
    name = charts.source_label(source)
    marker = {"color": p.sources.get(source), "cornerradius": 4}
    y = [labels[t] for t in lift_order]
    fig.add_trace(
        go.Bar(
            y=y,
            x=s["net_lift"],
            name=name,
            legendgroup=source,
            orientation="h",
            marker=marker,
            customdata=s[["net_sentiment", "baseline_net_sentiment", "records"]],
            hovertemplate=(
                "<b>%{y}</b><br>%{x:+.3f} · net %{customdata[0]:+.3f} "
                "wobec %{customdata[1]:+.3f} w tle<br>%{customdata[2]:,} rek."
                f"<extra>{name}</extra>"
            ),
        ),
        row=1,
        col=1,
    )
    # Ratios are drawn on a log2 scale around ×1, so ×4 and ×¼ are the same
    # length on opposite sides.
    fig.add_trace(
        go.Bar(
            y=y,
            x=np.log2(s["volume_multiplier"]),
            name=name,
            legendgroup=source,
            showlegend=False,
            orientation="h",
            marker=marker,
            customdata=s[["volume_multiplier", "per_day", "baseline_per_day"]],
            hovertemplate=(
                "<b>%{y}</b><br>×%{customdata[0]:.2f} · %{customdata[1]:,.0f} "
                "wobec %{customdata[2]:,.0f} rek./dzień w tle"
                f"<extra>{name}</extra>"
            ),
        ),
        row=1,
        col=2,
    )

exponents = np.log2(lift["volume_multiplier"].dropna().to_numpy())
ticks = range(
    int(np.floor(exponents.min(initial=0))), int(np.ceil(exponents.max(initial=0))) + 1
)
fig.update_xaxes(tickformat="+.1f", title="zmiana net sentimentu", row=1, col=1)
fig.update_xaxes(
    tickvals=list(ticks),
    ticktext=[f"×{2**t}" if t >= 0 else f"×1/{2**-t}" for t in ticks],
    title="rekordy na dzień wobec tła",
    row=1,
    col=2,
)
for col in (1, 2):
    fig.add_vline(x=0, line={"color": p.axis, "width": 1}, row=1, col=col)
fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08)
fig.update_yaxes(autorange="reversed", showgrid=False)
for annotation in fig.layout.annotations:
    annotation.font.color = p.ink
charts.style(fig, height=max(320, 56 * len(lift_order)) + 32)
fig.update_layout(legend_y=1.12, margin_t=80)
charts.show(fig)

with st.expander("Tabela efektu wydarzeń"):
    st.dataframe(
        lift.assign(_rank=lift["event_tag"].map({t: i for i, t in enumerate(order)}))
        .sort_values(["_rank", "source"])
        .assign(
            event_tag=lambda d: d["event_tag"].map(charts.event_label),
            source=lambda d: d["source"].map(charts.source_label),
        ),
        hide_index=True,
        width="stretch",
        column_order=[
            "event_tag",
            "source",
            "records",
            "net_sentiment",
            "baseline_net_sentiment",
            "net_lift",
            "per_day",
            "baseline_per_day",
            "volume_multiplier",
        ],
        column_config={
            "event_tag": "Wydarzenie",
            "source": "Źródło",
            "records": st.column_config.NumberColumn("Rekordy", format="%d"),
            "net_sentiment": st.column_config.NumberColumn("Net", format="%+.3f"),
            "baseline_net_sentiment": st.column_config.NumberColumn(
                "Net tła", format="%+.3f"
            ),
            "net_lift": st.column_config.NumberColumn("Zmiana net", format="%+.3f"),
            "per_day": st.column_config.NumberColumn("Rek./dzień", format="%.0f"),
            "baseline_per_day": st.column_config.NumberColumn(
                "Rek./dzień tła", format="%.0f"
            ),
            "volume_multiplier": st.column_config.NumberColumn(
                "Mnożnik", format="×%.2f"
            ),
        },
    )

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
