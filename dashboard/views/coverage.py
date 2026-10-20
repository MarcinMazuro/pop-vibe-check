"""Coverage: where each source contributes, by language."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
from dashboard import charts, queries

TOP_LANGUAGES = 12
UNKNOWN_LANGUAGE = "nieznany"

coverage = queries.source_coverage()
p = charts.palette()

st.title("Źródła i języki")
st.caption(
    f"Wolumen i udział pozytywnych per źródło i język, "
    f"źródło: `{queries.REPORTING_DATASET}.v_source_coverage`."
)

coverage = coverage.assign(language=coverage["language"].fillna(UNKNOWN_LANGUAGE))
all_sources = charts.ordered_sources(coverage["source"].unique().tolist())

# --- Per-source summary --------------------------------------------------------------
cols = st.columns(len(all_sources))
for col, source in zip(cols, all_sources, strict=True):
    s = coverage[coverage["source"] == source]
    col.metric(
        charts.source_label(source),
        f"{int(s['records'].sum()):,}".replace(",", " "),
    )
    col.caption(
        f"{s['first_record_utc'].min():%Y-%m-%d} → "
        f"{s['last_record_utc'].max():%Y-%m-%d} · {len(s)} języków"
    )

source = (
    st.segmented_control(
        "Źródło",
        all_sources,
        default=all_sources[0],
        format_func=charts.source_label,
        selection_mode="single",
    )
    or all_sources[0]
)

s = coverage[coverage["source"] == source].sort_values("records", ascending=False)
head = s.head(TOP_LANGUAGES)
color = p.sources.get(source)

left, right = st.columns(2)

with left:
    st.subheader("Rekordy per język")
    fig = go.Figure(
        go.Bar(
            y=head["language"],
            x=head["records"],
            orientation="h",
            marker={"color": color, "cornerradius": 4},
            text=[f"{v:,}".replace(",", " ") for v in head["records"]],
            textposition="outside",
            textfont={"color": p.ink_secondary},
            hovertemplate="<b>%{y}</b><br>%{x:,} rekordów<extra></extra>",
            cliponaxis=False,
        )
    )
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(title="rekordy")
    charts.show(charts.style(fig, height=40 * len(head) + 80))

with right:
    st.subheader("Udział pozytywnych")
    fig = go.Figure(
        go.Bar(
            y=head["language"],
            x=head["positive_share"],
            orientation="h",
            marker={"color": color, "cornerradius": 4},
            text=[f"{v:.0%}" for v in head["positive_share"]],
            textposition="outside",
            textfont={"color": p.ink_secondary},
            hovertemplate="<b>%{y}</b><br>%{x:.1%} pozytywnych<extra></extra>",
            cliponaxis=False,
        )
    )
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(range=[0, 1.08], tickformat=".0%", title="udział pozytywnych")
    charts.show(charts.style(fig, height=40 * len(head) + 80))

if UNKNOWN_LANGUAGE in set(s["language"]):
    st.caption(
        f"„{UNKNOWN_LANGUAGE}” — język nie został wykryty (zwykle bardzo krótkie "
        "teksty lub same emotikony). Takie rekordy model oznacza głównie jako "
        "neutralne, stąd niski udział pozytywnych."
    )

if len(s) > TOP_LANGUAGES:
    st.caption(f"Pokazano {TOP_LANGUAGES} języków z {len(s)}; pełna lista w tabeli.")

with st.expander("Tabela"):
    st.dataframe(
        s,
        hide_index=True,
        width="stretch",
        column_config={
            "source": None,
            "language": "Język",
            "records": st.column_config.NumberColumn("Rekordy", format="%d"),
            "first_record_utc": st.column_config.DatetimeColumn(
                "Pierwszy rekord", format="YYYY-MM-DD"
            ),
            "last_record_utc": st.column_config.DatetimeColumn(
                "Ostatni rekord", format="YYYY-MM-DD"
            ),
            "event_tags": "Tagi wydarzeń",
            "positive_share": st.column_config.NumberColumn(
                "Pozytywne", format="percent"
            ),
        },
    )
