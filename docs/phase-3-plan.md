# Phase 3 — a second release, and real-time analysis

Two scope items confirmed on 2026-10-14, after the first release's
pipeline was working end to end. Neither has started. This document is
what the work actually involves, so the estimate is not a guess later.

Neither item changes the replay design. Replay stays what makes a result
reproducible ([ADR 0002](adr/0002-replay-runs-as-one-build-with-a-completeness-gate.md));
real-time runs *beside* it, not instead of it.

---

## A second release

The parts that already parameterise cleanly:

- `var.name_prefix` prefixes every GCP resource name, so a second release
  gets `w4-raw-archive-dev` beside `co-raw-archive-dev` in the same
  project, with its own Terraform state prefix. This was designed in from
  the start and is the reason the prefix exists.
- `STEAM_APPID` is a Cloud Run Job environment variable, not a constant.
- The BigQuery schema is release-agnostic: `event_tag` carries the
  lifecycle event, nothing carries the release.

The parts that do not, and are therefore the work:

1. **Release configuration is baked into the images.**
   `collectors/config/events.yaml` and `youtube_videos.yaml` name one
   release, and both are `COPY`'d into the collector containers. Two
   releases means either a config per release in the image
   (`events-<release>.yaml`, selected by an env var) or the configs moved
   to GCS and read at start-up. The GCS option costs a read and a
   permission; the in-image option costs a rebuild per config edit, which
   is already how it works today.
2. **One dataset or two.** Separate datasets per release keep the
   reporting views trivially unchanged and keep `name_prefix` the only
   switch. One shared dataset with a `release` column would allow
   cross-release comparison in a single query — which is a thesis
   question, not an engineering one. **Decide before collecting**: it is
   a schema change afterwards.
3. **The NLP model is release-agnostic**, so nothing is needed there —
   but the gold evaluation set is not. A second release needs its own
   labelled sample before its numbers mean anything.
4. **Cost doubles** for anything that runs continuously. Currently that is
   nothing, which is why a second release is cheap to add today.

Rough size: a day for the configuration split, plus collection time per
release (YouTube is quota-bound, Steam is stream-cap-bound — see
[`collectors/steam/README.md`](../collectors/steam/README.md)).

---

## Real-time analysis

Today every record reaches BigQuery through a replay of the archive. Live
analysis means the archive grows while the pipeline is running, and the
pipeline does not stop.

### What it needs

1. **Incremental collection, on a schedule.** Cloud Scheduler triggering
   the collectors every N minutes with a window of "since the last run".
   The Steam collector is already shaped for this: `filter=recent` is
   newest-first, so a short window is a short walk — and the stream cap
   that blocks historical collection is irrelevant when the window is an
   hour. YouTube needs the same treatment plus care with the 10,000-unit
   daily quota: `commentThreads.list` at 1 unit per call makes a 15-minute
   cadence affordable, `search.list` at 100 does not.
2. **A continuously running Dataflow job.** This is the real cost. A
   streaming job bills until drained, and every cost guard in this project
   exists because of that — the manual-only replay trigger, the
   always-drain rule, the "job running too long" alert. Running one
   permanently is a deliberate reversal of a deliberate decision, and the
   alert threshold has to move with it or it will page constantly.
3. **Watermark and late data.** The replay publisher sets `created_utc` as
   a message attribute and the pipeline windows on event time, so late
   records are already handled correctly in principle. Live data tests it
   for real: a review edited hours after posting arrives late by
   definition.
4. **Dedup across runs.** Already solved by construction: ids are stable
   and the landing → table MERGE keys on id, so re-collecting an overlap
   is free. This is why incremental collection does not need exact
   bookkeeping.

### What it does not need

The replay path stays. A live dashboard and a reproducible thesis number
are different requirements: the dashboard wants freshness, the thesis
wants a fixed dataset at a known commit. Both read `events`; only replay
guarantees the second.

### The cheap demonstration

If the goal is showing real-time at the defence rather than running it
permanently: schedule the collectors every 15 minutes, launch the pipeline
an hour before, drain it afterwards. That is the full live path, costs one
hour of streaming Dataflow, and needs no change to the cost guards. Worth
doing first in any case — it finds the watermark and quota problems
without a standing bill.

Rough size: an evening for the scheduled collection plus the demo run; a
separate decision, with its own budget line, for leaving it running.
