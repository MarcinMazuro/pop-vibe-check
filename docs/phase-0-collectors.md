# Phase 0 — Collector application code

Status of the "Collector application code" chunk (README § Next: collectors).
This document records what was implemented in this iteration, the design
decisions taken, and the steps that remain (they require Docker and real
credentials, neither available on the machine used here).

Date: 2026-06-19.

---

## What was built

A new `collectors/` Python package plus repo-root tooling.

```
collectors/
├── __init__.py
├── common/
│   ├── __init__.py          # re-exports the public helpers
│   ├── author_hash.py       # SHA-256(username+salt)[:16], GDPR boundary
│   ├── gcs_writer.py        # list[dict] -> JSONL -> gzip -> GCS (partitioned path)
│   ├── events_config.py     # events.yaml loader, event_id -> Event
│   ├── retry.py             # tenacity exponential backoff for 429/5xx
│   └── records.py           # shared record schema builder
├── reddit/
│   ├── __init__.py
│   ├── main.py              # PRAW collector, entry: python -m collectors.reddit.main
│   ├── requirements.txt
│   ├── Dockerfile           # build context = repo root
│   ├── cloudbuild.yaml
│   └── README.md
├── youtube/
│   ├── __init__.py
│   ├── main.py              # google-api-python-client collector
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── cloudbuild.yaml
│   └── README.md
├── config/
│   ├── events.yaml          # 12 Clair Obscur lifecycle events
│   └── youtube_videos.yaml  # 6 curated video slots (ids are placeholders)
└── tests/
    ├── __init__.py
    ├── test_author_hash.py
    ├── test_gcs_writer.py
    └── test_events_config.py
```

Repo root: `pyproject.toml` (black / ruff+pydocstyle / mypy --strict / pytest),
`requirements-dev.txt`. `.gitignore` already covered Python artefacts, so it was
left unchanged.

---

## Design decisions

- **Reddit client: PRAW** — built-in rate-limit handling and simple comment-tree
  traversal.
- **One shared `collectors` package** with `common/` imported by both collectors.
- **Images build from the repository root**, not from `collectors/<svc>/`, so
  `python -m collectors.reddit.main` can import `collectors.common`. This is a
  deliberate departure from the README DoD command
  (`gcloud builds submit --tag ... collectors/reddit/`): the Dockerfiles use
  `-f collectors/<svc>/Dockerfile .` and the provided `cloudbuild.yaml` files
  encode the repo-root context.
- **Code style** is enforced: static typing (mypy strict), a docstring on every
  module/class/function, no emoji anywhere in code, PEP 8 via black + ruff.
  `ANN401` (disallowing `Any`) is ignored only at the PRAW / google-api-client
  boundary, where those libraries are untyped.

## Record schema

Both collectors emit the README schema (one compact JSON object per line):
`id, source, parent_id, created_utc, collected_at, author_hash, text, language,
score, context_id, event_tag`. The NLP fields (`sentiment_*`, `model_version`)
are intentionally omitted — they belong to the Phase 1 Dataflow stage.

GDPR boundary: raw handles are hashed in `common/author_hash.py` and never reach
a record. `hash_author` fails loudly if the salt is missing rather than writing
a re-identifiable un-salted hash.

---

## Verification performed (this machine)

Run inside a local `uv`-managed `.venv` (Python 3.12):

| Check | Command | Result |
|---|---|---|
| Lint (PEP 8 + docstrings) | `uv run ruff check collectors` | pass |
| Format | `uv run black --check collectors` | pass |
| Static typing | `uv run mypy collectors` | pass (15 files, strict) |
| Unit tests | `uv run pytest -q` | 19 passed |
| Config validity | parse `events.yaml` / `youtube_videos.yaml` | 12 events, 6 video slots |
| Import sanity | `import collectors.reddit.main, collectors.youtube.main` | ok |
| Entrypoint smoke (offline) | `uv run python -m collectors.{reddit,youtube}.main` | fails loudly: missing env → clear `ValueError`; unknown `EVENT_ID` → `KeyError` listing the 12 known ids, all before any network call |

The entrypoint smoke confirms both collectors load config, build their client
(PRAW / YouTube static discovery), and validate the event id locally without
Docker and without real credentials. Actual API collection still needs the
follow-up steps below.

---

## Mapping to the README "Definition of done"

| DoD item | Status |
|---|---|
| `common/` has hashing, GCS writer, retry, event loader + hash unit tests | Done (also writer + loader tests) |
| `reddit/` and `youtube/` build into Docker images locally (`docker build .`) | Dockerfiles + cloudbuild written; **build not run** (no Docker here) |
| `config/events.yaml` populated with all 12 events | Done — **dates flagged `# VERIFY`, must be confirmed before merge** |
| `config/youtube_videos.yaml` with ≥5 canonical videos | 6 entries — **ids are `REPLACE` placeholders, need real video ids** |
| Smoke test against real APIs (small window) | **Not done** — needs real credentials |
| Images built and pushed to Artifact Registry | **Not done** — needs Docker/build |
| `terraform apply` with image URI overrides | **Not done** — follow-up |
| `gcloud run jobs execute` produces a valid `.jsonl.gz` | **Not done** — follow-up |
| README per collector | Done (`collectors/reddit/README.md`, `collectors/youtube/README.md`) |

---

## Follow-up (not done here — needs Docker and/or real credentials)

1. **Verify the data placeholders.**
   - Confirm the 12 event dates in `events.yaml` against public sources and
     remove the `# VERIFY` flags.
   - Replace the `REPLACE...` video ids in `youtube_videos.yaml` with real
     11-character YouTube video ids.

2. **Populate the secret containers** (currently placeholder values):
   ```bash
   printf '%s' "$REDDIT_CLIENT_ID"     | gcloud secrets versions add co-reddit-client-id-dev     --project=pop-vibe-check --data-file=-
   printf '%s' "$REDDIT_CLIENT_SECRET" | gcloud secrets versions add co-reddit-client-secret-dev --project=pop-vibe-check --data-file=-
   printf '%s' "$REDDIT_USER_AGENT"    | gcloud secrets versions add co-reddit-user-agent-dev    --project=pop-vibe-check --data-file=-
   printf '%s' "$YOUTUBE_API_KEY"      | gcloud secrets versions add co-youtube-api-key-dev       --project=pop-vibe-check --data-file=-
   openssl rand -hex 32                | gcloud secrets versions add co-author-hash-salt-dev      --project=pop-vibe-check --data-file=-
   ```

3. **Build and push the images** (build context = repo root):
   ```bash
   gcloud builds submit --config collectors/reddit/cloudbuild.yaml .
   gcloud builds submit --config collectors/youtube/cloudbuild.yaml .
   ```

4. **Point the Cloud Run Jobs at the real images.** In
   `terraform/envs/dev/main.tf`, set the (currently commented) overrides on the
   `cloud_run_jobs` module:
   ```hcl
   reddit_image_uri  = "${module.artifact_registry.repository_url}/reddit-collector:<sha>"
   youtube_image_uri = "${module.artifact_registry.repository_url}/youtube-collector:<sha>"
   ```
   then `cd terraform/envs/dev && terraform apply`.

5. **Smoke test** a small window and inspect the output:
   ```bash
   gcloud run jobs execute co-reddit-collector-dev \
     --region=europe-central2 \
     --update-env-vars="EVENT_ID=launch,WINDOW_FROM=2025-04-24T00:00:00Z,WINDOW_TO=2025-04-24T06:00:00Z" \
     --wait
   gcloud storage ls "gs://co-raw-archive-dev/reddit/launch/**"
   ```
   Verify a `.jsonl.gz` exists and its lines match the record schema.

## Local development quickstart

Uses [uv](https://docs.astral.sh/uv/) for environment and dependency management:

```bash
uv venv --python 3.12
uv pip install -r requirements-dev.txt
uv run ruff check collectors
uv run black --check collectors
uv run mypy collectors
uv run pytest -q
```
