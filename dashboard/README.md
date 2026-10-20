# dashboard

Streamlit dashboard over the BigQuery reporting views. A quick, code-first way to explore the results; the same charts can later be rebuilt in Looker Studio against the same views.

## Rule: the numbers live in the views

Every query is a plain `SELECT *` over one authorized view in the reporting dataset (`terraform/modules/bigquery/main.tf`). A new metric is a new column or a new view in Terraform, never a calculation in Python — that is what keeps a Looker Studio rebuild a matter of clicking the charts together.

The one exception is `metrics.rollup`: it rolls `v_sentiment_daily` up to weeks, months and whole events by **summing the counts and dividing again**, exactly what a Looker Studio chart does with SUM fields. It never averages shares, and it drops `distinct_authors`, which is not additive.

The dashboard never reads the analytics dataset. The reporting views leave out `author_hash` and `text`, so neither can reach a chart.

## Pages

| Page | View | Shows |
|---|---|---|
| Przegląd | `v_sentiment_daily`, `v_sentiment_by_event` | Headline numbers, net sentiment and volume over time per source, event windows shaded |
| Wydarzenia | `v_sentiment_daily`, `v_sentiment_by_event` | Net sentiment and sentiment split per event × source, the widest source divergence |
| Źródła i języki | `v_source_coverage` | Volume and positive share per source and language |

## Running locally

From the repository root, in a separate virtualenv (Streamlit's dependencies do not belong in the pipeline's):

```bash
python -m venv dashboard/.venv
dashboard/.venv/Scripts/python -m pip install -r dashboard/requirements.txt   # Windows
# dashboard/.venv/bin/python -m pip install -r dashboard/requirements.txt     # Linux / macOS

gcloud auth application-default login
dashboard/.venv/Scripts/python -m streamlit run dashboard/app.py
```

Run it as `python -m streamlit` from the repository root: that puts the root on `sys.path`, so `from dashboard import …` resolves. Your Google account needs read access to the reporting dataset — `report_viewer_emails` in the env's `terraform.tfvars` grants exactly that.

Saving a page under `views/` reloads it (`--server.runOnSave true` skips the *Rerun* prompt). Changes to `charts.py`, `metrics.py` or `queries.py` need a server restart: Streamlit does not re-import the `dashboard` package's modules. Query results are cached for `CACHE_TTL_SECONDS`; the sidebar's *Odśwież dane* button clears the cache.

## Deployment (Cloud Run)

The dev dashboard runs as the Cloud Run service `co-dashboard-dev` (`terraform/modules/dashboard`), behind Identity-Aware Proxy. Open the URL from `terraform output dashboard_url` and sign in with a Google account listed in `report_viewer_emails`; the page then reads the views as the service's own identity, so viewers need no BigQuery access.

Every merge to main that touches `dashboard/` builds `dashboard/Dockerfile`, pushes the image and deploys it by digest (`dashboard/cloudbuild.yaml`). To try the image locally:

```bash
docker build -f dashboard/Dockerfile -t dashboard .
docker run --rm -p 8080:8080 -e PORT=8080 \
  -e GOOGLE_APPLICATION_CREDENTIALS=/adc.json \
  -v "$APPDATA/gcloud/application_default_credentials.json:/adc.json:ro" dashboard
```

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `PROJECT_ID` | `pop-vibe-check` | GCP project, also the one billed for queries |
| `REPORTING_DATASET` | `co_reporting_dev` | Dataset holding the authorized views (`<prefix>_reporting_<env>`) |
| `CACHE_TTL_SECONDS` | `300` | How long a query result is reused |

## Tests

```bash
dashboard/.venv/Scripts/python -m pytest dashboard/tests
```

The tests cover the rollup arithmetic only; they skip themselves where pandas is not installed (the CI image).
