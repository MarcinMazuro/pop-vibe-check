# collectors/steam

Collects Steam user reviews for one application and writes them to the raw
archive as gzipped JSONL — the same record shape and the same bucket layout
as the YouTube collector.

Steam is the project's second source. The reasoning (and why Reddit is not)
is in
[docs/adr/0001-steam-replaces-reddit-as-second-source.md](../../docs/adr/0001-steam-replaces-reddit-as-second-source.md).

## Why this collector is simple

The store review endpoint
(`store.steampowered.com/appreviews/<appid>?json=1`) is plain HTTPS with
**no key, no registration and no quota application**. There is no Secret
Manager wiring beyond the shared author-hash salt, and no client library —
just `requests`.

It is also undocumented, so the collector is deliberately polite: one page
at a time (100 reviews, the endpoint's maximum), a pause between pages
(`STEAM_PAGE_SLEEP_SECONDS`, default 0.5s), an honest `User-Agent` naming
the project, and a page cap per run (`STEAM_MAX_PAGES`).

## Windowing, and why `EVENT_ID=auto` exists

The request sets `filter=recent`, which returns reviews in **descending
`timestamp_created`** order — the only ordering a window can be read
against. There is no "reviews since date" parameter: a run always starts at
today and walks backwards.

For this release that is ~280,000 reviews, about 2,800 pages. Collecting
each lifecycle event separately would re-walk those pages once per event,
so historical collection is **one walk** with `EVENT_ID=auto`: every review
is tagged by its own date, the nearest event within `EVENT_WINDOW_DAYS`
(default 3) wins, and a review near no event is tagged `general` — a prefix
the raw archive layout already allows. Ties go to the earlier event date,
so two runs tag identically.

`EVENT_ID=<id>` still works and tags the whole run with that id. That is
the right mode for topping up a recent window, where the walk back is
short.

Either way the collector skips reviews newer than `WINDOW_TO`, keeps what
falls inside, and **stops as soon as it reads past `WINDOW_FROM`**.

## The endpoint caps a result stream, not the data

Measured on appid `1903340` (2026-10-12): a `filter=recent` walk ended on
its own at **page 1243 — 124,187 of 280,699 reviews**, with the oldest
record reaching only **September 2025** for a game that launched in April.
The page came back empty; nothing failed. Steam simply stops paginating a
given result stream long before the data runs out.

So full history is not one walk, it is **several narrower streams whose
ids the staging MERGE unions** (every review's id is stable, so passes
overlap harmlessly):

| Variable | Values | Why it helps |
|---|---|---|
| `STEAM_REVIEW_TYPE` | `all` / `positive` / `negative` | Negatives are ~13,000 of 280,000, so a negative pass reaches launch comfortably |
| `STEAM_LANGUAGE` | `all` or a Steam language name (`english`, `schinese`, …) | Each language is its own stream with its own cap |
| `STEAM_FILTER` | `recent` / `updated` / `all` | A different ordering is a different stream: `updated` reaches April 2025 reviews on its first page |

Two things that do **not** help, both checked: `day_range` is clamped to
roughly 365 days, so it cannot reach an 18-month-old launch; and raising
`STEAM_MAX_PAGES` does nothing, because the stream ends before the cap.

Only `filter=recent` is ordered by creation time, so only `recent` stops
early once it reads past `WINDOW_FROM`. `updated` and `all` interleave old
and new, so they walk their whole stream and filter per record — slower,
but the only way to reach what `recent` will not serve. Each pass logs the
oldest record it wrote, which is the coverage number worth recording.

## Rate limits and resuming

Steam rate-limits this endpoint and does not document the limit. Measured:
two requests a second earns a 429 within a hundred pages; roughly thirty a
minute is tolerated, which is the default pace (`STEAM_PAGE_SLEEP_SECONDS`,
2s). A page is retried up to eight times with waits up to five minutes,
honouring `Retry-After` when Steam sends one, and **every 429 doubles the
inter-page pause for the rest of the run** — a wrong guess at the pace
should slow a walk down, not end it.

Because a full walk is thousands of pages, the cursor is **checkpointed to
`gs://<bucket>/steam/_checkpoints/<appid>.json` every 25 pages**, after the
pending records are flushed, so a resumed run never skips what the cursor
has passed. An interrupted run — a 429 storm, a task restart, a timeout —
continues where it stopped instead of starting at today again. The
checkpoint is keyed by appid and window, so resuming a different window
ignores it, and a completed walk deletes it.

Set `STEAM_RESUME=false` to force a walk from the newest review.

Pagination stops on an empty page, a missing cursor, or a cursor that
repeats — the endpoint hands back the same cursor at the end of the list
rather than signalling completion.

## Field mapping

| Record field | Steam field |
|---|---|
| `id` | `steam:` + `recommendationid` |
| `source` | `steam` |
| `parent_id` | `null` — reviews are flat, there are no replies |
| `created_utc` | `timestamp_created` (epoch → ISO 8601 UTC) |
| `author_hash` | `SHA-256(author.steamid + salt)`, truncated to 16 chars |
| `text` | `review` |
| `score` | `votes_up` |
| `context_id` | the appid |
| `event_tag` | the run's `EVENT_ID` |
| `voted_up` | `voted_up` — the author's own thumbs up/down |

**`voted_up` is the reason this source earns its place twice over.** It is
a sentiment label chosen by the author, so it evaluates the classifier at
a scale no hand-labelled gold set reaches. It is `NULL` for YouTube, and
`false` means thumbs down — never read a missing value as a negative.

**Nothing else about the author is kept.** `personaname` and `profile_url`
are dropped inside `review_record`; only the salted hash of `steamid`
reaches GCS. A test asserts that none of the three appear in a record.

`language` is **not** taken from Steam: its values are names like
`schinese`, not the ISO codes the schema holds. Language is detected the
same way as for YouTube, and Dataflow overrides it with the authoritative
value anyway.

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `TARGET_BUCKET` | yes | — | Raw archive bucket |
| `AUTHOR_HASH_SALT` | yes | — | Salt, from Secret Manager |
| `EVENT_ID` | yes | — | Lifecycle event id, or `auto` to tag each review by its own date |
| `WINDOW_FROM` | yes | — | Inclusive ISO 8601 start |
| `WINDOW_TO` | yes | — | Exclusive ISO 8601 end |
| `STEAM_APPID` | yes | — | Application id; `1903340` is Clair Obscur: Expedition 33 |
| `STEAM_PAGE_SLEEP_SECONDS` | no | `0.5` | Pause between pages |
| `STEAM_MAX_PAGES` | no | `3000` | Safety cap on pages per run (~300,000 reviews) |
| `EVENT_WINDOW_DAYS` | no | `3` | Half-width of each event window, for `EVENT_ID=auto` |
| `STEAM_RESUME` | no | `true` | Continue from the stored cursor when one matches this appid and window |
| `STEAM_FILTER` | no | `recent` | Endpoint ordering: `recent` (creation time), `updated` (last edit), `all` (helpfulness) |
| `STEAM_REVIEW_TYPE` | no | `all` | `all`, `positive` or `negative` |
| `STEAM_LANGUAGE` | no | `all` | Steam language name, or `all` |

`TARGET_BUCKET`, `STEAM_APPID` and the salt are set on the Cloud Run Job by
Terraform; the window and event are per-execution.

## Run it

Full history, tagged per event — the run that matters, ~30 minutes:

```bash
gcloud run jobs execute co-steam-collector-dev \
  --region=europe-central2 \
  --update-env-vars="EVENT_ID=auto,WINDOW_FROM=2025-04-24T00:00:00Z,WINDOW_TO=2026-12-31T00:00:00Z" \
  --wait
```

A single recent event, where the walk back is short:

```bash
gcloud run jobs execute co-steam-collector-dev \
  --region=europe-central2 \
  --update-env-vars="EVENT_ID=anniversary_update_2026,WINDOW_FROM=2026-04-22T00:00:00Z,WINDOW_TO=2026-04-30T00:00:00Z" \
  --wait
```

Reviews start at launch (2025-04-24), so earlier events — the reveal, the
trailers, the release-date reveal — have no Steam data by construction.
That asymmetry against YouTube's full-cycle coverage is reported in the
analysis rather than hidden.

Locally:

```bash
export TARGET_BUCKET=co-raw-archive-dev AUTHOR_HASH_SALT=... STEAM_APPID=1903340
export EVENT_ID=launch WINDOW_FROM=2025-04-24T00:00:00Z WINDOW_TO=2025-05-01T00:00:00Z
python -m collectors.steam.main
```

## Build the image

Cloud Build builds it on every pull request touching the collector and, on
merge to `main`, pushes it tagged with the commit SHA and deploys it to
`co-steam-collector-dev` by digest. Terraform ignores the job's image.

Locally: `docker build -f collectors/steam/Dockerfile -t steam-collector .`
(build context is the repository root).
