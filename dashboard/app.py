"""Entry point of the Streamlit dashboard.

Run from the repository root, so the ``dashboard`` package is importable::

    python -m streamlit run dashboard/app.py
"""

from __future__ import annotations

import streamlit as st

from dashboard import queries

st.set_page_config(page_title="Pop Vibe Check", page_icon="📈", layout="wide")

page = st.navigation(
    [
        st.Page("views/overview.py", title="Przegląd", icon="📈", default=True),
        st.Page("views/events.py", title="Wydarzenia", icon="🗓️"),
        st.Page("views/coverage.py", title="Źródła i języki", icon="🌐"),
    ]
)

with st.sidebar:
    st.caption(f"Dane: `{queries.PROJECT_ID}.{queries.REPORTING_DATASET}`")
    if st.button("Odśwież dane", help="Pomija pamięć podręczną i pyta BigQuery."):
        st.cache_data.clear()

page.run()
