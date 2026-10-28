# MLflow tracking server image, served by the Cloud Run service
# (terraform/modules/mlflow).
#
# Build context is the repository root, as for every other image here:
#
#   docker build -f mlflow_server/Dockerfile -t mlflow-server .
#
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY mlflow_server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# The backend URI carries the database password, so it is assembled here
# from the service's env rather than stored anywhere whole. The socket
# under /cloudsql is Cloud Run's built-in Cloud SQL connection.
#
# --no-serve-artifacts: clients write artifacts straight to GCS and the
# server reads them back only for the UI; nothing large passes through
# Cloud Run's 32 MiB request limit. One worker, matching the service's
# single instance (see the module).
#
# Allowed hosts and CORS origins come from MLFLOW_SERVER_ALLOWED_HOSTS and
# MLFLOW_SERVER_CORS_ALLOWED_ORIGINS, set by the module.
CMD exec mlflow server \
    --host 0.0.0.0 \
    --port "${PORT:-8080}" \
    --workers 1 \
    --backend-store-uri "postgresql+psycopg2://${DB_USER}:${DB_PASSWORD}@/${DB_NAME}?host=/cloudsql/${CLOUD_SQL_CONNECTION_NAME}" \
    --default-artifact-root "${ARTIFACT_ROOT}" \
    --no-serve-artifacts
