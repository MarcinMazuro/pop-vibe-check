"""Shared chart styling: colours by role, labels and the Plotly layout.

Colour follows the entity, never its position: Steam is always slot 1 and
YouTube slot 2, whichever subset a filter leaves on screen. Sentiment is a
polarity, so it gets the diverging pair (blue = positive, red = negative)
with a grey midpoint for neutral. Light and dark mode each use their own
validated steps rather than one set of colours on both backgrounds.
"""

from __future__ import annotations

from dataclasses import dataclass

import plotly.graph_objects as go
import streamlit as st

SOURCE_LABELS = {"steam": "Steam", "youtube": "YouTube", "reddit": "Reddit"}
SOURCE_ORDER = ["steam", "youtube", "reddit"]

SENTIMENT_LABELS = {
    "positive": "Pozytywne",
    "neutral": "Neutralne",
    "negative": "Negatywne",
}


@dataclass(frozen=True)
class Palette:
    """Colour roles for one colour scheme."""

    ink: str
    ink_secondary: str
    muted: str
    grid: str
    axis: str
    surface: str
    sources: dict[str, str]
    sentiment: dict[str, str]
    event_band: str


LIGHT = Palette(
    ink="#0b0b0b",
    ink_secondary="#52514e",
    muted="#898781",
    grid="#e1e0d9",
    axis="#c3c2b7",
    surface="#fcfcfb",
    sources={"steam": "#2a78d6", "youtube": "#eb6834", "reddit": "#1baf7a"},
    sentiment={"positive": "#256abf", "neutral": "#c3c2b7", "negative": "#e34948"},
    event_band="rgba(11,11,11,0.06)",
)

DARK = Palette(
    ink="#f0efec",
    ink_secondary="#c3c2b7",
    muted="#898781",
    grid="#2c2c2a",
    axis="#383835",
    surface="#1a1a19",
    sources={"steam": "#3987e5", "youtube": "#d95926", "reddit": "#199e70"},
    sentiment={"positive": "#3987e5", "neutral": "#5d5c58", "negative": "#e66767"},
    event_band="rgba(255,255,255,0.07)",
)


def palette() -> Palette:
    """The palette matching the viewer's current Streamlit theme."""
    theme = getattr(st.context, "theme", None)
    return DARK if getattr(theme, "type", None) == "dark" else LIGHT


def source_label(source: str) -> str:
    """Display name of a source (``steam`` → ``Steam``)."""
    return SOURCE_LABELS.get(source, source)


def event_label(tag: str | None) -> str:
    """Display name of an event tag (``tga_2025_sweep`` → ``tga 2025 sweep``)."""
    if tag is None:
        return "(brak)"
    return tag.replace("_", " ")


def ordered_sources(sources: list[str]) -> list[str]:
    """Sources in their fixed colour-slot order, unknown ones last."""
    rank = {name: i for i, name in enumerate(SOURCE_ORDER)}
    return sorted(sources, key=lambda s: (rank.get(s, len(rank)), s))


def style(fig: go.Figure, height: int = 380) -> go.Figure:
    """Apply the shared layout: recessive grid, legend on top, unified hover."""
    p = palette()
    fig.update_layout(
        height=height,
        margin={"l": 16, "r": 16, "t": 48, "b": 16},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": p.ink_secondary},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
            "title": None,
        },
        hoverlabel={"bgcolor": p.surface, "font": {"color": p.ink}},
        # Thousands grouped with a space, as in the headline numbers.
        separators=". ",
    )
    axis = {
        # Grow the margin to fit long category labels instead of clipping them.
        "automargin": True,
        "gridcolor": p.grid,
        "linecolor": p.axis,
        "zerolinecolor": p.axis,
        "tickfont": {"color": p.muted},
        "title": {"font": {"color": p.ink_secondary}},
    }
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    return fig


def show(fig: go.Figure) -> None:
    """Render a styled figure at full width."""
    st.plotly_chart(fig, width="stretch", theme=None)
