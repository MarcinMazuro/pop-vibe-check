"""BigQuery reads for the dashboard.

Every query is a plain ``SELECT`` over one authorized view in the reporting
dataset. The metrics themselves live in the view SQL
(``terraform/modules/bigquery/main.tf``), so a Looker Studio data source
pointed at the same view shows the same numbers. Nothing here reads the
analytics dataset, and the runtime identity is not allowed to.
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


def sentiment_daily() -> pd.DataFrame:
    """One row per day × source × event_tag (``v_sentiment_daily``)."""
    df = _select(f"SELECT * FROM {_view('v_sentiment_daily')}")
    df["event_date"] = pd.to_datetime(df["event_date"])
    return df


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
