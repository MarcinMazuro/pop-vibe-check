# Reddit collector

Pulls posts and comments about *Clair Obscur: Expedition 33* from a fixed set of
subreddits for one lifecycle event and time window, and writes gzipped JSONL
batches to `gs://co-raw-archive-dev/reddit/<event>/YYYY/MM/DD/HH/<batch>.jsonl.gz`.

Entry point: `python -m collectors.reddit.main`.

## Environment variables

| Variable | Source | Purpose |
|---|---|---|
| `TARGET_BUCKET` | Cloud Run Job literal | GCS bucket to write into (`co-raw-archive-dev`) |
| `REDDIT_CLIENT_ID` | Secret Manager | Reddit OAuth client id |
| `REDDIT_CLIENT_SECRET` | Secret Manager | Reddit OAuth client secret |
| `REDDIT_USER_AGENT` | Secret Manager | e.g. `pop-vibe-check/0.1 by u/<handle>` |
| `AUTHOR_HASH_SALT` | Secret Manager | Per-project salt for username hashing |
| `EVENT_ID` | Execution-time | Lifecycle event id (must exist in `config/events.yaml`) |
| `WINDOW_FROM` | Execution-time | Start of collection window (ISO 8601 UTC) |
| `WINDOW_TO` | Execution-time | End of collection window (ISO 8601 UTC) |

## Behaviour

- Subreddits: `ClairObscurExpedition33`, `JRPG`, `Games`, `gaming` (constant in `main.py`).
- Search query: `clair obscur OR expedition 33`.
- The window is walked in 6-hour slices (Reddit search caps at ~1000 results/query).
- Comment threads are descended to depth ≤ 2 (binding design constraint).
- Author handles are SHA-256-hashed at ingest; **raw usernames never reach GCS**.

## Run locally

```bash
# From the repository root (so collectors.common is importable).
uv venv --python 3.12
uv pip install -r collectors/reddit/requirements.txt
export TARGET_BUCKET=co-raw-archive-dev
export REDDIT_CLIENT_ID=... REDDIT_CLIENT_SECRET=... REDDIT_USER_AGENT='pop-vibe-check/0.1 by u/<handle>'
export AUTHOR_HASH_SALT=...
export EVENT_ID=launch WINDOW_FROM=2025-04-24T00:00:00Z WINDOW_TO=2025-04-24T06:00:00Z
uv run python -m collectors.reddit.main
```

## Build the image

Build context is the **repository root**:

```bash
gcloud builds submit --config collectors/reddit/cloudbuild.yaml .
# or locally:
docker build -f collectors/reddit/Dockerfile -t reddit-collector .
```

## Execute the Cloud Run Job

After the image URI is wired into Terraform and applied:

```bash
gcloud run jobs execute co-reddit-collector-dev \
  --region=europe-central2 \
  --update-env-vars="EVENT_ID=launch,WINDOW_FROM=2025-04-24T00:00:00Z,WINDOW_TO=2025-04-26T00:00:00Z" \
  --wait
```
