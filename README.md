# pop-vibe-check

Streaming sentiment analysis around pop-culture releases, on GCP with an MLOps pipeline. Engineering thesis project at Gdańsk University of Technology, Department of Computer Systems Architecture.

> **Status:** Phase 0 complete; Phase 1 stream simulation **live**. The YouTube collector has produced the first real dataset (4228 comments across 4 lifecycle events — see [docs/phase-0-youtube-first-collection.md](docs/phase-0-youtube-first-collection.md)), and the **replay publisher now streams it from BigQuery staging to Pub/Sub in chronological order with time compression** (see [docs/phase-1-publisher.md](docs/phase-1-publisher.md)). The Reddit collector is written but blocked on Reddit API credentials.

---

## What it does

Ingests user opinions about pop-culture releases from Reddit and YouTube, classifies sentiment with an NLP model, and visualises how public sentiment evolves over time around key moments in a release's lifecycle (announcement, trailers, launch, controversies, awards).

**Case study:** *Clair Obscur: Expedition 33* — full hype cycle from the 2024 Xbox Showcase reveal through the 2025 launch, the AI-textures controversy, the Game Awards sweep, and the 2026 anniversary update. Chosen because the curve is *not* flat — universal critical acclaim → controversy → awards sweep → controversy reignites — so the sentiment dynamics are visibly non-trivial.

**Why this is interesting beyond the demo:** the pipeline is release-agnostic. A future Witcher 4 study reuses the same Terraform code with a single variable change (`name_prefix = "w4"`).

## Architecture

```
Reddit API ─┐
            ├──► Cloud Run Jobs (collectors) ──► GCS bucket "raw archive"
YouTube API ┘                                          │
                                                       ▼
                                            BigQuery staging table
                                            (load from raw, ORDER BY time)
                                                       │
                                                       ▼
                                            Cloud Run Job (publisher)
                                            reads sorted result,
                                            emits in replay order
                                                       │
                                                       ▼
                                                   Pub/Sub topic
                                                       │
                                                       ▼
                                            Cloud Dataflow (Apache Beam)
                                            calls NLP model → enriches
                                                       │
                                                       ▼
                                            BigQuery "events" table
                                            (analytical truth)
                                                       │
                                                       ▼
                                                Looker Studio
```

**Why raw GCS sits alongside BigQuery.** BigQuery is the analytical source of truth. GCS holds the immutable raw payloads exactly as scraped, so a replay can be regenerated without re-hitting external APIs. Change the NLP model, change the schema — replay from GCS, not from the internet.

**Why a publisher between BigQuery staging and Pub/Sub.** Global chronological ordering across sources is a hard requirement (the whole point is "how did sentiment evolve over time" — order matters). Pub/Sub alone cannot guarantee global order. BigQuery can — `ORDER BY` is total. The publisher streams a sorted result set out of BigQuery into Pub/Sub with ordering keys, so Dataflow sees events in the order they happened in the real world, not in the order they were scraped.

## Tech stack

| Layer | Choice |
|---|---|
| IaC | Terraform ≥ 1.6, `hashicorp/google` provider 5.x |
| Language (services) | Python 3.12 |
| Runtime (batch) | Cloud Run Jobs |
| Messaging | Pub/Sub (with ordering keys) |
| Streaming | Cloud Dataflow, Apache Beam Python SDK |
| Raw storage | GCS |
| Analytical warehouse | BigQuery |
| Model registry | MLflow |
| Secrets | Secret Manager |
| Container registry | Artifact Registry |
| CI/CD | Cloud Build + GitHub |
| Visualisation | Looker Studio |
| Region | `europe-central2` (Warsaw) |

## Team

| Person | Student # |
|---|---|
| Marcin Mazuro | 198019 |
| Oskar Lewandowski | 198265 |
| Kacper Kozak | 198223 |

Supervisor: mgr inż. Szymon Olewniczak.

---

## Current state

| Block | Status | Lives in |
|---|---|---|
| GCP project + bootstrap (state bucket, runner SA, IAM, API enablement) | ✓ Applied | [`terraform/bootstrap/`](terraform/bootstrap/) |
| Dev environment composition root | ✓ Applied | [`terraform/envs/dev/`](terraform/envs/dev/) |
| Storage module (raw archive + artifacts buckets) | ✓ Applied | [`terraform/modules/storage/`](terraform/modules/storage/) |
| IAM module (collector + cloud-build service accounts) | ✓ Applied | [`terraform/modules/iam/`](terraform/modules/iam/) |
| Secrets module (5 empty containers + accessor bindings) | ✓ Applied | [`terraform/modules/secrets/`](terraform/modules/secrets/) |
| Artifact Registry (Docker repo) | ✓ Applied | [`terraform/modules/artifact_registry/`](terraform/modules/artifact_registry/) |
| Network (VPC + subnet, Private Google Access) | ✓ Applied | [`terraform/modules/network/`](terraform/modules/network/) |
| BigQuery (dataset + `raw_landing` / `raw_staging`; `events` table in the Dataflow PR) | ✓ Applied | [`terraform/modules/bigquery/`](terraform/modules/bigquery/) |
| Budgets (monthly cap + email alerts) | ✓ Applied | [`terraform/modules/budgets/`](terraform/modules/budgets/) |
| Cloud Run Jobs (collector jobs + replay publisher job) | ✓ Applied | [`terraform/modules/cloud_run_jobs/`](terraform/modules/cloud_run_jobs/) |
| Pub/Sub (events topic + ordered verify subscription; DLQ in the Dataflow PR) | ✓ Applied | [`terraform/modules/pubsub/`](terraform/modules/pubsub/) |
| Collector application code (common, reddit, youtube + tests) | ✓ Done | [`collectors/`](collectors/) |
| YouTube collector: image, job wiring, first collection runs | ✓ Done — 4228 records ([details](docs/phase-0-youtube-first-collection.md)) | GCS `co-raw-archive-dev/youtube/` |
| Reddit collector: image + smoke test | ✗ **Blocked on Reddit API credentials** | `collectors/reddit/` |
| Real values in secret containers | YouTube key + salt ✓ real; Reddit ✗ placeholders | Secret Manager |
| Replay publisher: code, image, job, first replay to Pub/Sub | ✓ Done — 4228 records replayed in order ([details](docs/phase-1-publisher.md)) | [`publisher/`](publisher/) |
| Dataflow module, `events` table, Cloud Build module | ✗ Phase 1 (remaining) | Not yet |
| NLP model | ✗ Phase 1 (stub first, real model via MLflow later) | Not yet |

### What's actually live in the `pop-vibe-check` GCP project

After all merged PRs and applies:

- **GCS:** `pvc-tf-state` (shared remote state), `co-raw-archive-dev` (**contains the first real dataset**: `youtube/<event>/...jsonl.gz`, 4228 records), `co-tf-artifacts-dev`
- **Service accounts:** `pvc-tf-runner-sa`, `co-collector-reddit-sa-dev`, `co-collector-youtube-sa-dev`, `co-publisher-sa-dev`, `co-cloud-build-sa-dev`
- **Secret containers:** `co-youtube-api-key-dev` (✓ real key, restricted to YouTube Data API; the invalid v1 is disabled) and `co-author-hash-salt-dev` (✓ real salt) — the three `co-reddit-*-dev` secrets still hold placeholders
- **Artifact Registry:** `co-images-dev` with `youtube-collector:729b1fd...` (built 2026-07-05) and `publisher:2e209f7...` (built 2026-07-16)
- **VPC:** `co-vpc-dev` with subnet `co-subnet-dev` in europe-central2
- **BigQuery:** `co_analytics_dev` dataset with `raw_landing` (truncate-and-load target) and `raw_staging` (deduplicated, DAY-partitioned on `created_utc`, clustered by `source, event_tag`) — both hold the 4228-record dataset
- **Pub/Sub:** `co-events-topic-dev` + `co-events-verify-sub-dev` (ordered pull subscription for manual verification)
- **Cloud Run Jobs:** `co-youtube-collector-dev` (✓ real collector image), `co-publisher-dev` (✓ real publisher image, first replay done), `co-reddit-collector-dev` (still on the `pause` placeholder)
- **Budget:** monthly alert at 50/90/100/120% of configured cap

The YouTube job is fully operational — executing it with `EVENT_ID`/`WINDOW_FROM`/`WINDOW_TO` collects real comments into the raw archive. The publisher job loads the archive into staging (`RUN_LOAD=only`) and replays it to Pub/Sub with time compression (see [publisher/README.md](publisher/README.md)). The Reddit job stays on the placeholder image until Reddit API credentials exist.

---

## Roadmap

### Phase 0 — Collector infrastructure (done)
Foundation needed to run one collector pull from Reddit/YouTube → write raw JSONL to GCS.

✓ All Terraform modules listed above are applied.

### Phase 0 — Collector application code (done)
The Python code that runs inside the collector containers — `collectors/` with shared `common/`, both entry points, tests, Dockerfiles. See [docs/phase-0-collectors.md](docs/phase-0-collectors.md).

### Phase 0 — First real collection (YouTube done, Reddit blocked)
YouTube: image built and pushed, job wired, API key fixed, four events collected (4228 records) — see [docs/phase-0-youtube-first-collection.md](docs/phase-0-youtube-first-collection.md). Remaining: Reddit credentials + smoke test, the `ai_textures_controversy` video decision, and the `# VERIFY` event dates in `events.yaml`.

### Phase 1 — Stream simulation + NLP + analytics
After collectors produce raw JSONL reliably:

1. ✓ `pubsub/` module — events topic + ordered verify subscription (dead-letter topic deferred to the Dataflow PR, where the first nacking consumer appears)
2. ✓ (partial) `bigquery/` extension — `raw_landing` + `raw_staging` tables done; `events` table + authorised views land with the Dataflow PR
3. ✓ (partial) `iam/` extension — publisher SA done; Dataflow worker SA with its module
4. `dataflow/` module — Beam Flex Template, worker SA wiring
5. ✓ `cloud_run_jobs/` extension — publisher job (BigQuery → Pub/Sub bridge with time compression), deployed and verified ([docs/phase-1-publisher.md](docs/phase-1-publisher.md))
6. `cloud_build/` module — per-service triggers, workload-identity for runner SA impersonation (closes the bootstrap chicken-and-egg)
7. Application: ✓ `publisher/`; remaining: `dataflow/` Beam pipeline, `nlp/stub/`, then `nlp/registry/` with MLflow

### Phase 2 — Polish, prod env, defence
- `terraform/envs/prod/` composition (same shape as dev)
- Pre-commit hooks (`terraform fmt`, `tflint`, `tfsec`)
- Architecture diagram for the thesis document
- Looker Studio dashboard

---

## Next: collectors

> **Update 2026-07-05:** this plan is **largely executed** — `collectors/` is
> implemented ([docs/phase-0-collectors.md](docs/phase-0-collectors.md)) and the
> YouTube path runs end-to-end in GCP
> ([docs/phase-0-youtube-first-collection.md](docs/phase-0-youtube-first-collection.md)).
> It remains the reference spec for the **Reddit half**, which is blocked on
> Reddit API credentials (see [§ Real credentials](#real-credentials)).

### Goal

A `gcloud run jobs execute co-reddit-collector-dev --update-env-vars=EVENT_ID=launch,WINDOW_FROM=...,WINDOW_TO=...` pulls the matching Reddit comments and writes valid JSONL.gz files to `gs://co-raw-archive-dev/reddit/launch/2025/04/24/...`. Same for YouTube. After this works for one event, repeat over the full hype cycle.

### Scope

```
collectors/
├── common/        # shared utilities — author hashing, GCS writer, retry, event loader
├── reddit/        # Reddit collector entry point + Dockerfile + cloudbuild.yaml
├── youtube/       # YouTube collector entry point + Dockerfile + cloudbuild.yaml
└── config/
    ├── events.yaml         # the 12 events of Clair Obscur lifecycle
    └── youtube_videos.yaml # curated list of canonical videos per event
```

### `collectors/common/`

Shared library imported by both collectors. Suggested files: `author_hash.py`, `gcs_writer.py`, `events_config.py`, `retry.py`, plus tests.

**Author hashing.** SHA-256 over `username + salt`, salt from env var `AUTHOR_HASH_SALT`, output truncated to 16 hex chars. Hash deterministic per (username, salt) — same author across the dataset must always produce the same `author_hash`. **Raw usernames must never appear in any record written to GCS** — this is the GDPR-by-design boundary, treat it as non-negotiable.

**GCS writer.** Takes a list of dicts and:
- Serialises one JSON object per line (no pretty-printing)
- Gzips
- Uploads to the path `{source}/{event_id_or_general}/{YYYY}/{MM}/{DD}/{HH}/{batch_id}.jsonl.gz` under the target bucket
- `batch_id` should be unique per process invocation (a UUID is fine) so concurrent writes don't collide
- The bucket name comes from env var `TARGET_BUCKET`

**Event config loader.** Reads `collectors/config/events.yaml` and resolves `event_id` → `(name, type, date_utc)`. Used by the GCS writer to know which directory to write under.

**Retry helper.** Exponential backoff for transient API errors (HTTP 429, 5xx). Both PRAW and the YouTube client offer this built-in; if you prefer raw requests, a small `tenacity`-based wrapper is enough.

### `collectors/reddit/`

Entry point: `python -m collectors.reddit.main`.

**Env vars consumed:**

| Variable | Source | Purpose |
|---|---|---|
| `TARGET_BUCKET` | Cloud Run Job literal | GCS bucket to write into (e.g. `co-raw-archive-dev`) |
| `REDDIT_CLIENT_ID` | Secret Manager | Reddit OAuth client ID |
| `REDDIT_CLIENT_SECRET` | Secret Manager | Reddit OAuth client secret |
| `REDDIT_USER_AGENT` | Secret Manager | Required by Reddit (something like `pop-vibe-check/0.1 by u/<your-handle>`) |
| `AUTHOR_HASH_SALT` | Secret Manager | Per-project salt for username hashing |
| `EVENT_ID` | Execution-time `--update-env-vars` | Which lifecycle event this run targets (e.g. `launch`, `xbox_showcase_reveal`) |
| `WINDOW_FROM` | Execution-time | Start of collection window (ISO 8601 UTC) |
| `WINDOW_TO` | Execution-time | End of collection window |

**Algorithm:**

1. Authenticate to Reddit OAuth (PRAW or raw `requests` against `oauth.reddit.com`).
2. Resolve `EVENT_ID` via the event config loader; if it's not in `events.yaml`, fail loudly.
3. Iterate over the in-scope subreddits — for `Clair Obscur: Expedition 33` the obvious ones are `r/ClairObscurExpedition33`, `r/JRPG`, `r/Games`, `r/gaming`. Subreddit list can be hardcoded for now; if it grows, lift into a config file.
4. For each subreddit, paginate `search` with `q=clair obscur OR expedition 33` (or similar — exact query is a judgement call worth committing as a constant) over the time window. **Reddit `search` returns at most ~1000 results per call**, so paginate via narrow time slices — start with 6h windows.
5. For each post returned, fetch its comment thread to depth **≤ 2** (top-level comments + first-level replies + second-level replies, no deeper — deeper sub-threads are usually off-topic relative to the release).
6. For each post and each comment, build a record in the schema below.
7. Batch records (e.g. 500 per batch) and write to GCS via the common writer.

**Record schema** (one JSON object per line in the output):

| Field | Type | Notes |
|---|---|---|
| `id` | string | Source-prefixed unique ID, e.g. `reddit:t3_abc123` (post) or `reddit:t1_def456` (comment) |
| `source` | string | Literal `"reddit"` |
| `parent_id` | string \| null | For comments — Reddit's `parent_id`. For posts: `null` |
| `created_utc` | string (ISO 8601 UTC) | Author-side timestamp (Reddit's `created_utc` epoch converted) |
| `collected_at` | string (ISO 8601 UTC) | Now, set by the collector |
| `author_hash` | string | 16 hex chars, see common/author_hash |
| `text` | string | Post `selftext + title`, or comment `body` |
| `language` | string \| null | Detect with `langdetect` or leave `null` (Dataflow stage can fill in) |
| `score` | int | Upvotes (Reddit's `score` field) |
| `context_id` | string | Subreddit name without the `r/` prefix |
| `event_tag` | string | The `EVENT_ID` env var value |

`sentiment_label`, `sentiment_score`, `model_version` are populated by the Dataflow stage in Phase 1 — collectors should not include those fields.

**Hard constraints:**
- Comment depth ≤ 2 (decision is binding, see the events / docs)
- No raw usernames anywhere in the output
- One record per line, valid JSON, no trailing comma
- Gzipped output (the writer handles this)
- Reddit OAuth rate limit is ~100 req/min — keep paginate-and-sleep in mind for long windows

**Container:**
- `Dockerfile` — Python 3.12 slim base, install `requirements.txt`, set entrypoint to the module
- `requirements.txt` — pin everything, including transitive deps (use `pip-compile` or just `pip freeze` after testing)
- `cloudbuild.yaml` — minimal: build the image, push to `europe-central2-docker.pkg.dev/pop-vibe-check/co-images-dev/reddit-collector:$COMMIT_SHA`

### `collectors/youtube/`

Entry point: `python -m collectors.youtube.main`.

**Env vars consumed:**

| Variable | Source | Purpose |
|---|---|---|
| `TARGET_BUCKET` | Cloud Run Job literal | GCS bucket |
| `YOUTUBE_API_KEY` | Secret Manager | YouTube Data API v3 key |
| `AUTHOR_HASH_SALT` | Secret Manager | Same salt as Reddit collector |
| `EVENT_ID` | Execution-time | Lifecycle event ID |
| `WINDOW_FROM` / `WINDOW_TO` | Execution-time | Collection window (filters comments by `publishedAt`) |

**Algorithm:**

1. Load `collectors/config/youtube_videos.yaml` (a manually curated list of canonical videos per event — official trailers, top reviews, top reaction videos).
2. Filter the list to videos relevant to `EVENT_ID` (each entry has an `event_ids` array; could also be a global pool).
3. For each video, call `commentThreads.list` paginated. **Each call costs 1 quota unit, the daily quota is 10,000** — prefer this endpoint.
4. For each top-level comment, walk replies (`replies.comments` is included in the response).
5. Filter by `publishedAt` against the window — YouTube returns all comments regardless of time, so do this client-side.
6. Optionally, around each event date, use `search.list` to surface videos the curated list missed. **`search.list` costs 100 units per call, use sparingly** (one search per event, capped to the top 20 videos).
7. Hash author handles (`authorDisplayName`), build records, batch, write to GCS via the common writer.

**Record schema:** same as Reddit, with:
- `source = "youtube"`
- `id` like `youtube:Ugxabc123` (the YouTube comment ID with prefix)
- `context_id` = the video ID (not the comment ID)
- `parent_id` = the parent comment ID for replies, `null` for top-level
- `score` = `likeCount`

**Container:**
- `Dockerfile` mirroring the Reddit one
- `requirements.txt` (likely `google-api-python-client`)
- `cloudbuild.yaml` for image build → push to `europe-central2-docker.pkg.dev/pop-vibe-check/co-images-dev/youtube-collector:$COMMIT_SHA`

### `collectors/config/`

**`events.yaml`** — the 12 lifecycle events of Clair Obscur. One entry per event:

```yaml
events:
  - id: xbox_showcase_reveal
    name: Xbox Games Showcase reveal
    type: reveal
    date_utc: 2024-06-09
  - id: gameplay_trailer_flying_waters
    name: Flying Waters gameplay trailer
    type: trailer
    date_utc: 2024-08-27
  # … 10 more
```

Full list of 12 events (id, type, date) is in this repo's history under the engineering thesis context — populate from there. Verify each date against public sources before merging; the dates in earlier docs are best-effort.

**`youtube_videos.yaml`** — manually curated list, ≥1 video per event:

```yaml
videos:
  - id: <YouTube video ID>
    title: <human-readable title for your reference>
    event_ids: [launch, ai_textures_controversy]   # which events this video is relevant to
```

Start with 5-10 entries (the official trailers, the launch reaction videos with the highest comment count, the IGN/GameSpot reviews); grow over time.

### Definition of done

Before opening the PR for collector code, verify:

- [x] `collectors/common/` has author hashing, GCS writer, retry, event loader — with unit tests for at least the hash function (deterministic, salt-sensitive)
- [x] `collectors/reddit/` and `collectors/youtube/` build into Docker images locally (`docker build .`) — YouTube built and pushed; Reddit Dockerfile written, build pending
- [x] `collectors/config/events.yaml` populated with all 12 events (dates flagged `# VERIFY` still need confirmation)
- [x] `collectors/config/youtube_videos.yaml` populated with ≥5 canonical videos — 9 API-verified ids
- [x] At least one smoke test against the real APIs with a small window — **YouTube done** (4 real runs); **Reddit pending credentials**
- [x] Images built and pushed manually to Artifact Registry — **YouTube done** (note: build context is the repo root, `docker build -f collectors/<svc>/Dockerfile .`, not `collectors/<svc>/`); **Reddit pending**
- [x] Cloud Run Job points at the real image — **YouTube done** (`youtube_image_uri` in `terraform/envs/dev/main.tf` + in-place `gcloud run jobs update`); **Reddit pending**
- [x] One `gcloud run jobs execute …` produces a valid `.jsonl.gz` — **YouTube done**, contents verified against the schema; **Reddit pending**
- [x] README per collector with setup + local-run + execute commands

### Real credentials

The secret containers currently hold placeholder strings. Before the collector can do useful work, populate them with real values:

- **Reddit**: create a Reddit app at <https://www.reddit.com/prefs/apps> → script type → record `client_id`, `client_secret`. User agent should be a descriptive string like `pop-vibe-check/0.1 by u/<your-reddit-handle>`. Push to Secret Manager:
  ```bash
  printf '%s' "$REDDIT_CLIENT_ID" | gcloud secrets versions add co-reddit-client-id-dev --project=pop-vibe-check --data-file=-
  # same for client_secret and user_agent
  ```
- **YouTube**: ✓ done — a real key (restricted to YouTube Data API v3) is stored as version 2 of `co-youtube-api-key-dev`; the invalid version 1 is disabled.
- **Author-hash salt**: ✓ done — version 1 of `co-author-hash-salt-dev` is real. Never rotate it (rotation invalidates author continuity across the dataset).

The Reddit and YouTube credentials are operator-personal — each contributor uses their own. The salt is project-shared.

### How to run

Works today for YouTube (Reddit once its image is wired up):

```bash
gcloud run jobs execute co-youtube-collector-dev \
  --region=europe-central2 \
  --update-env-vars="EVENT_ID=launch,WINDOW_FROM=2025-04-24T00:00:00Z,WINDOW_TO=2025-04-26T00:00:00Z" \
  --wait
```

`--wait` blocks until the task finishes. Logs are in Cloud Logging filtered by the job name. Output JSONL ends up under `gs://co-raw-archive-dev/youtube/launch/…` (path uses collection date, not window date). Re-running with a different window only appends new batch files — dedupe by record `id` happens in Phase 1.

### Suggested split between contributors

Three people, three roughly-equal chunks:

- **Person A:** `collectors/common/` (hashing, GCS writer, retry, event loader) + unit tests. This is the foundation both collectors import.
- **Person B:** `collectors/reddit/` (entry point, Dockerfile, cloudbuild.yaml, smoke test) and `collectors/config/events.yaml`.
- **Person C:** `collectors/youtube/` (entry point, Dockerfile, cloudbuild.yaml, smoke test) and `collectors/config/youtube_videos.yaml`.

A and (B or C) can start in parallel; the other waits a day for A's common library to stabilise enough to import.

---

## Repository layout

```
.
├── README.md                              # this file
├── terraform/
│   ├── bootstrap/                         # one-time GCP project setup (applied)
│   ├── envs/
│   │   └── dev/                           # dev composition root (applied)
│   └── modules/                           # all Phase 0 modules applied
│       ├── artifact_registry/
│       ├── bigquery/
│       ├── budgets/
│       ├── cloud_run_jobs/
│       ├── iam/
│       ├── network/
│       ├── pubsub/
│       ├── secrets/
│       └── storage/
├── collectors/                            # implemented — shared lib + both collectors
│   ├── common/                            # author hashing, GCS writer, retry, event loader
│   ├── reddit/                            # written; blocked on Reddit API credentials
│   ├── youtube/                           # live — collecting real data in GCP
│   ├── config/                            # events.yaml + youtube_videos.yaml (API-verified ids)
│   └── tests/
├── publisher/                             # live — replay publisher (BQ staging → Pub/Sub)
│   └── tests/
└── docs/                                  # phase write-ups (collectors, first collection, publisher)
```

Future directories that will appear in the rest of Phase 1: `dataflow/`, `nlp/`, and more `terraform/modules/` (`dataflow/`, `cloud_build/`).

## Getting set up

If you're picking up this project on a new laptop:

1. Install `gcloud`, `terraform` ≥ 1.6, Python 3.12, Docker.
2. `gcloud auth login` and `gcloud auth application-default login`.
3. Ask Marcin for `roles/iam.serviceAccountTokenCreator` on `pvc-tf-runner-sa` (so the Terraform provider can impersonate the runner SA — `roles/owner` alone is not enough; GCP excludes `iam.serviceAccounts.getAccessToken` from Owner).
4. `cd terraform/envs/dev && cp terraform.tfvars.example terraform.tfvars && $EDITOR terraform.tfvars` (fill in `project_id`, `billing_account_id`, `monthly_budget_amount`, `notification_emails`).
5. `terraform init && terraform plan` — should report "No changes" against the current state.

For the bootstrap procedure (only needed on a brand-new GCP project, not for joining an existing one), see [`terraform/bootstrap/README.md`](terraform/bootstrap/README.md).

## Conventions

- **Commits**: Conventional Commits (`feat:`, `fix:`, `refactor:`, `chore:`, `docs:`).
- **Branching**: trunk-based, short-lived feature branches, PR into `main`, squash merge.
- **Terraform**: `terraform fmt` on commit, `terraform validate` clean, module inputs documented in each module's README.
- **Python**: PEP 8, `black` formatting, `ruff` linting, type hints on public functions, one service = one container = one `requirements.txt`.
- **Secrets**: never in committed files, never echoed in logs, always Secret Manager.

## Constraints worth knowing

These are non-negotiable design choices — propose an ADR before contradicting any of them.

1. **GCS is the immutable raw archive. BigQuery is the analytical source of truth.** Both are first-class; neither is temporary.
2. **Global chronological ordering of events is required.** The whole replay mechanism depends on it.
3. **Reddit comment depth ≤ 2.** Deeper threads are usually off-topic.
4. **Author handles are SHA-256-hashed at ingest.** Original usernames never reach GCS.
5. **BigQuery schema: single denormalised `events` table.** No joins for the dashboard layer.
6. **NLP starts as a stub.** Real model swapped in later via MLflow without touching surrounding code.

The full list with rationale lives in the engineering thesis text and the agent-only architectural notes.
