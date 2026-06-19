# YouTube collector

Pulls comment threads (top-level comments and replies) from a curated list of
canonical videos for one lifecycle event, filters them by publish time, and
writes gzipped JSONL batches to
`gs://co-raw-archive-dev/youtube/<event>/YYYY/MM/DD/HH/<batch>.jsonl.gz`.

Entry point: `python -m collectors.youtube.main`.

## Environment variables

| Variable | Source | Purpose |
|---|---|---|
| `TARGET_BUCKET` | Cloud Run Job literal | GCS bucket to write into (`co-raw-archive-dev`) |
| `YOUTUBE_API_KEY` | Secret Manager | YouTube Data API v3 key |
| `AUTHOR_HASH_SALT` | Secret Manager | Per-project salt for username hashing |
| `EVENT_ID` | Execution-time | Lifecycle event id (must exist in `config/events.yaml`) |
| `WINDOW_FROM` | Execution-time | Start of collection window (ISO 8601 UTC) |
| `WINDOW_TO` | Execution-time | End of collection window (ISO 8601 UTC) |

## Behaviour

- Videos come from `config/youtube_videos.yaml`, filtered to those whose
  `event_ids` include `EVENT_ID`. Placeholder ids (prefixed `REPLACE`) are
  skipped with a warning — populate real video ids before running.
- Uses `commentThreads.list` (1 quota unit/page; daily quota 10,000).
- Comments are filtered client-side by `publishedAt` against the window.
- `score` = `likeCount`, `context_id` = video id, `parent_id` = parent comment
  id for replies (else `null`).
- Author handles are SHA-256-hashed at ingest; **raw handles never reach GCS**.

## Run locally

```bash
# From the repository root (so collectors.common is importable).
uv venv --python 3.12
uv pip install -r collectors/youtube/requirements.txt
export TARGET_BUCKET=co-raw-archive-dev
export YOUTUBE_API_KEY=...
export AUTHOR_HASH_SALT=...
export EVENT_ID=launch WINDOW_FROM=2025-04-24T00:00:00Z WINDOW_TO=2025-04-26T00:00:00Z
uv run python -m collectors.youtube.main
```

## Build the image

Build context is the **repository root**:

```bash
gcloud builds submit --config collectors/youtube/cloudbuild.yaml .
# or locally:
docker build -f collectors/youtube/Dockerfile -t youtube-collector .
```

## Execute the Cloud Run Job

After the image URI is wired into Terraform and applied:

```bash
gcloud run jobs execute co-youtube-collector-dev \
  --region=europe-central2 \
  --update-env-vars="EVENT_ID=launch,WINDOW_FROM=2025-04-24T00:00:00Z,WINDOW_TO=2025-04-26T00:00:00Z" \
  --wait
```
