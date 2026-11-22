# collectors/bluesky

Collects public Bluesky posts that match a release's search queries and
writes them to the raw archive as gzipped JSONL — the same record shape and
the same bucket layout as the YouTube and Steam collectors.

Bluesky is the second source for releases without a Steam page (GTA VI).
The reasoning is in
[docs/adr/0005-bluesky-as-second-source-for-gta-vi.md](../../docs/adr/0005-bluesky-as-second-source-for-gta-vi.md).

## How it reads

`app.bsky.feed.searchPosts` with `sort=latest`, `since` and `until`. The
window is cut into slices (`BLUESKY_SLICE_MINUTES`, default 360), newest
first, and each slice is read to the end of its cursor for every query.
Slices exist because search results are paginated to a finite depth: one
huge window could end early without an error. A slice that hits
`BLUESKY_MAX_PAGES_PER_SLICE` logs a warning naming the slice — rerun that
period with narrower slices.

Each finished slice is flushed to GCS before the next starts, so an
interrupted run keeps everything it read.

## Two modes, one job

| Mode | Window | Typical use |
|---|---|---|
| History | `WINDOW_FROM` + `WINDOW_TO` | Backfill a lifecycle event, or the whole cycle with `EVENT_ID=auto` |
| Live | `WINDOW_LOOKBACK_MINUTES` | Scheduled every N minutes; the window ends at "now" |

A scheduler can only pass fixed environment overrides, which is why live
mode is a look-back rather than "since the last run". Make the look-back
longer than the schedule interval (e.g. 30 minutes every 15): overlaps
are free, because ids are stable and the staging MERGE keys on them.

## Login

Search refuses anonymous pagination, so the collector logs in with an
**app password** (Bluesky → Settings → Privacy and security → App
passwords; leave direct-message access off). It never uses the account
password. One session per run, refreshed if it expires: the PDS limits
logins to a few hundred a day, which a 15-minute schedule (96 a day)
stays well inside.

The handle is not secret and is a Terraform variable. The app password
lives in Secret Manager as `{name_prefix}-bluesky-app-password-{env}`;
add it without putting it on the command line:

```bash
read -rs BSKY_APP_PASSWORD && printf '%s' "$BSKY_APP_PASSWORD" | \
  gcloud secrets versions add gta6-bluesky-app-password-dev \
  --project=<PROJECT_ID> --data-file=-
```

## Privacy

- `author_hash` is the salted hash of the author's DID. Handle, display
  name, avatar and DID are never written.
- A post's AT URI embeds the DID, so `id` and `parent_id` are salted
  hashes of the whole URI (`bluesky:` + 32 hex). They deliberately do not
  contain the author hash: `id` is visible in the reporting layer and must
  not let anyone group posts by author. Replies still point at their
  parents, because the parent's id is computed from the parent's URI.

## Record mapping

| Field | From |
|---|---|
| `id` | salted hash of `post.uri` |
| `parent_id` | salted hash of `record.reply.parent.uri`, or null |
| `created_utc` | earlier of `record.createdAt` and `indexedAt` — the client sets the first and can claim any date |
| `author_hash` | salted hash of the DID in `post.uri` |
| `text` | `record.text`; posts with no text (image-only) are skipped |
| `language` | `record.langs[0]` when the author set it, else detected (advisory — Dataflow writes the real value) |
| `score` | `likeCount` |
| `context_id` | the search query that found the post |
| `event_tag` | the run's `EVENT_ID`, or per post with `EVENT_ID=auto` |
| `voted_up` | null — posts carry no author verdict |

A post matched by several queries is written once per run.

## Environment

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `TARGET_BUCKET` | yes | — | Raw archive bucket |
| `RELEASE` | yes | — | Release config directory under `collectors/config/`; its `events.yaml` drives `EVENT_ID` validation and `auto` tagging |
| `AUTHOR_HASH_SALT` | yes | — | Shared salt (Secret Manager) |
| `BLUESKY_HANDLE` | yes | — | Account the collector logs in as |
| `BLUESKY_APP_PASSWORD` | yes | — | App password (Secret Manager) |
| `BLUESKY_QUERIES` | yes | — | `;`-separated queries, e.g. `"GTA 6";GTA6;"GTA VI"` |
| `EVENT_ID` | yes | — | Lifecycle event id, or `auto` |
| `WINDOW_FROM` / `WINDOW_TO` | one form | — | Explicit window (ISO 8601 UTC) |
| `WINDOW_LOOKBACK_MINUTES` | one form | — | Window ending now |
| `BLUESKY_PDS_URL` | no | `https://bsky.social` | Where to log in; later calls go to the account's own PDS from its DID document |
| `BLUESKY_SLICE_MINUTES` | no | `360` | Slice width |
| `BLUESKY_MAX_PAGES_PER_SLICE` | no | `100` | Page cap per query per slice (100 posts a page) |
| `BLUESKY_PAGE_SLEEP_SECONDS` | no | `1.0` | Pause between pages |
| `EVENT_WINDOW_DAYS` | no | `3` | Half-width of each event window, for `EVENT_ID=auto` |

`TARGET_BUCKET`, `RELEASE`, `BLUESKY_HANDLE`, `BLUESKY_QUERIES` and both
secrets are set on the Cloud Run Job by Terraform. The window and
`EVENT_ID` are execution-time overrides.

## Running

Local, against a scratch bucket:

```bash
export TARGET_BUCKET=<scratch-bucket> RELEASE=gta6 AUTHOR_HASH_SALT=<salt>
export BLUESKY_HANDLE=<you>.bsky.social BLUESKY_QUERIES='"GTA 6";GTA6'
read -rs BLUESKY_APP_PASSWORD && export BLUESKY_APP_PASSWORD
EVENT_ID=launch WINDOW_LOOKBACK_MINUTES=60 python -m collectors.bluesky.main
```

On Cloud Run — a history backfill around launch, and a live top-up:

```bash
gcloud run jobs execute gta6-bluesky-collector-dev --region=europe-central2 \
  --update-env-vars="EVENT_ID=auto,WINDOW_FROM=2026-11-16T00:00:00Z,WINDOW_TO=2026-11-23T00:00:00Z,BLUESKY_SLICE_MINUTES=60"

gcloud run jobs execute gta6-bluesky-collector-dev --region=europe-central2 \
  --update-env-vars="EVENT_ID=auto,WINDOW_LOOKBACK_MINUTES=30"
```

On `execute`, `--update-env-vars` overrides that one execution only, so
the two modes never leak into each other. Setting both window forms in one
run fails loudly.

## Image

Built and deployed by Cloud Build on merge to main
(`cloudbuild.yaml`, same shape as the other collectors), only in
compositions where the job exists (`enable_bluesky = true`).
