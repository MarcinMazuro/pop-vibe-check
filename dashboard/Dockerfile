# Streamlit dashboard image, served by the Cloud Run service
# (terraform/modules/dashboard).
#
# Build context MUST be the repository root (not dashboard/): the app runs
# as `python -m streamlit run dashboard/app.py` and imports the dashboard
# package from the working directory:
#
#   docker build -f dashboard/Dockerfile -t dashboard .
#
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

COPY dashboard/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY dashboard/ ./dashboard/

# The rollup tests are for CI, not the server.
RUN rm -rf ./dashboard/tests

# Shell form: Cloud Run passes the port to listen on in $PORT.
CMD exec python -m streamlit run dashboard/app.py --server.port="${PORT:-8080}"
