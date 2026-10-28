# mlflow_server

The image of the MLflow tracking server: stock `mlflow server` with a Postgres driver and the GCS client, configured entirely from the environment the Cloud Run service sets. There is no application code here.

- Infrastructure, first deployment and how clients authenticate: [`terraform/modules/mlflow/README.md`](../terraform/modules/mlflow/README.md).
- Why a server at all, and why Cloud SQL: [ADR 0004](../docs/adr/0004-mlflow-tracking-server-on-cloud-run-and-cloud-sql.md).
- Logging runs to it: [`nlp/tracking/mlflow_utils.py`](../nlp/tracking/mlflow_utils.py). Copying the older file-store runs into it: [`nlp/tracking/migrate.py`](../nlp/tracking/migrate.py).

The version in `requirements.txt` is the upper bound for the training client (`nlp/training/requirements.txt`). A newer client may call endpoints this server does not have, so move both together.

Run it locally against SQLite, for a look at the UI:

```bash
pip install -r mlflow_server/requirements.txt
mlflow server --backend-store-uri sqlite:///mlflow.db --port 5000
```
