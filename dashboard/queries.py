"""BigQuery reads for the dashboard.

Every query is a plain ``SELECT`` over one authorized view in the reporting
dataset. The metrics themselves live in the view SQL — the Dataform project
in ``definitions/reporting/`` — so a Looker Studio data source pointed at the
same view shows the same numbers. Nothing here reads the analytics dataset,
and the runtime identity is not allowed to.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st
from google.cloud import bigquery

PROJECT_ID = os.environ.get("PROJECT_ID", "pop-vibe-check")
REPORTING_DATASET = os.environ.get("REPORTING_DATASET", "co_reporting_dev")

# Replay data only changes when a replay runs; live data (phase 3) arrives
# continuously. Five minutes keeps a live demo fresh without re-querying on
# every widget change.
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "300"))


@st.cache_resource
def _client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID)


def _view(name: str) -> str:
    return f"`{PROJECT_ID}.{REPORTING_DATASET}.{name}`"


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Pobieranie danych z BigQuery…")
def _select(sql: str) -> pd.DataFrame:
    return _client().query(sql).to_dataframe()


def sentiment_by_period() -> pd.DataFrame:
    """One row per grain × period × source (``v_sentiment_by_period``).

    Every source has a row for every period, zero counts where it had none.
    """
    df = _select(f"SELECT * FROM {_view('v_sentiment_by_period')}")
    df["period"] = pd.to_datetime(df["period"])
    return df


def sentiment_by_event_source() -> pd.DataFrame:
    """One row per event_tag × source, ``general`` included."""
    return _select(f"SELECT * FROM {_view('v_sentiment_by_event_source')}")


def event_lift() -> pd.DataFrame:
    """One row per event_tag × source against the rest of its source."""
    return _select(f"SELECT * FROM {_view('v_event_lift')}")


def source_divergence() -> pd.DataFrame:
    """Per event_tag with two or more sources, the most and least positive one."""
    return _select(f"SELECT * FROM {_view('v_source_divergence')} ORDER BY gap DESC")


def sentiment_by_event() -> pd.DataFrame:
    """One row per lifecycle event tag (``v_sentiment_by_event``)."""
    return _select(
        f"SELECT * FROM {_view('v_sentiment_by_event')} ORDER BY first_record_utc"
    )


def source_coverage() -> pd.DataFrame:
    """One row per source × language (``v_source_coverage``)."""
    return _select(
        f"SELECT * FROM {_view('v_source_coverage')} ORDER BY source, records DESC"
    )
