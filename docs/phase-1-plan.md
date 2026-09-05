# Phase 1 — completion plan: Dataflow, second source, NLP

Work plan for finishing Phase 1 and reaching a defensible end-to-end
system. Written against the verified state of the `pop-vibe-check` GCP
project and the repository on 2026-09-05. Splits the remaining work into
three parallel tracks, one per contributor.

Date: 2026-09-05.

---

## Verified state

Infrastructure matches code. `terraform plan` in `terraform/envs/dev`
reports `0 to add, 1 to change, 0 to destroy` — the single change is a
cosmetic perpetual diff in the `budgets` module (the provider normalises
`budget_filter.projects` to the project *number*, the module supplies the
project *ID*). Harmless, worth a one-line fix so plans read clean.

Data in BigQuery:

| Table | Rows | `created_utc` range |
|---|---|---|
| `raw_landing` | 4228 | 2024-06-09 → 2025-06-15 |
| `raw_staging` | 4228 | 2024-06-09 → 2025-06-15 |
| `events_landing` | **0** | — |
| `events` | **0** | — |

Coverage is YouTube-only across four lifecycle events:
`xbox_showcase_reveal` (1711), `gameplay_trailer_flying_waters` (1257),
`launch` (909), `critical_acclaim_wave` (351).

Everything else Phase 1 needs is live: the Pub/Sub topic with its ordered
Dataflow subscription and dead-letter path, the `events` / `events_landing`
tables, the Dataflow worker SA and its grants, the dataflow-temp bucket,
the inter-worker firewall rule, and the launch-parameter outputs. Artifact
Registry holds `youtube-collector` and `publisher` images; there is no
`dataflow` image yet.

**The critical path is one thing.** The pipeline currently ends at
Pub/Sub. `events` is empty, meaning the project has not yet classified a
single comment. Nothing else — not more data, not a better model — is
worth anything until records flow through Dataflow into `events`.

---

## Reddit is out of scope

Reddit API credentials were requested and refused. This is not a delay to
work around; it is a permanent constraint, and the plan treats it as one.

**What changes.** Reddit is removed from the collection plan: the
project's stated sources become YouTube and a second source (see the next
section). The `co-reddit-*-dev` secret containers keep their
placeholders, and `co-reddit-collector-dev` stays pinned to the
placeholder image — both are already parameterised to sit idle, so no
Terraform teardown is required.

**What stays.** `collectors/reddit/` remains in the repository, complete
and tested. It is written against the documented Reddit OAuth flow and
would run unchanged the day credentials appear. Keeping it is honest —
the work was done, the blocker is external.

**How the thesis handles it.** As a documented limitation with a
mitigation, which is a stronger result than silently shipping one source.
The write-up should state: access to the Reddit API was denied, the
collector was nonetheless implemented against the published interface,
and a second source with open access was substituted so the multi-source
ordering guarantee remains demonstrable rather than theoretical.

---

## Steam reviews as the second source

**This is a scope decision and needs sign-off** — from the team and,
given that it changes the data sources named in the thesis proposal, from
the supervisor. It is recommended, and the rest of this plan assumes it.

Losing Reddit costs more than a row count. The publisher exists because
global chronological ordering *across sources* is a hard requirement that
Pub/Sub cannot satisfy on its own — BigQuery's `ORDER BY` is total, so the
archive is sorted there and streamed out under Pub/Sub ordering keys (see
the architecture section of the root README and `publisher/README.md`).
With a single source, that entire design argument becomes untestable — the ordering still works, but nothing in the
system demonstrates *why* it was needed. A second source restores it.

Steam reviews for *Clair Obscur: Expedition 33* (appid `1903340`) fit
better than Reddit did.

**Verified working, no key required.** The store review endpoint
(`store.steampowered.com/appreviews/<appid>?json=1`) returns JSON over
plain HTTPS with no authentication, no registration, and no quota
application. Confirmed on 2026-09-05: 277,523 total reviews, cursor
pagination at 100 records per page, `filter=recent` returning strictly
descending `timestamp_created`. There is no approval process to be
refused by.

**The schema already fits.** No changes to the `events` table:

| `events` field | Steam field |
|---|---|
| `id` | `steam:` + `recommendationid` |
| `source` | `steam` |
| `parent_id` | `null` (reviews are flat) |
| `created_utc` | `timestamp_created` (epoch → ISO 8601) |
| `author_hash` | SHA-256 of `author.steamid` + salt, truncated |
| `text` | `review` |
| `language` | `language` (Steam's own; advisory, as with YouTube) |
| `score` | `votes_up` |
| `context_id` | the appid |
| `event_tag` | resolved from the collection window, as elsewhere |

**It is complementary, not redundant.** The game launched 2025-04-24, so
Steam reviews start at launch — pre-launch events (reveal, trailers,
release-date reveal) have no Steam data. YouTube covers the full cycle
including pre-launch; Steam covers launch onward at far greater depth.
Together they cover more of the lifecycle than either does alone, and the
difference in their coverage is itself worth a paragraph in the analysis.

**It supplies ground truth.** Every review carries `voted_up`, a
thumbs-up/down the author chose themselves. That is a free weak label
against which the sentiment classifier can be validated at scale, on top
of the hand-labelled gold set — a genuine evaluation asset that neither
YouTube nor Reddit offered.

**It is multilingual.** A sample page ran 49% English, with Chinese,
Russian, French, and Korean making up most of the rest. This is a real
input to the model decision below, not a footnote.

**Constraints to respect.** The endpoint is undocumented-but-public: rate
limit politely (the existing `collectors/common/retry.py` backoff
applies), identify the client honestly in the user agent, and never write
`author.personaname` or `author.profile_url` to GCS — only the salted
hash of `steamid` leaves the collector, exactly as for YouTube handles.
Hashing at ingest — SHA-256 over the identifier plus a Secret Manager
salt, truncated to 16 hex characters — is the project's privacy-by-design
boundary and is not negotiable per source. Steam profile identifiers are
personal data on the same footing.

Because this changes a binding decision, it needs an ADR recording the
substitution and its rationale alongside the code.

**If sign-off does not happen**, Oskar's track collapses to B2–B4 below
(YouTube depth only) and the thesis carries single-source collection as
an unmitigated limitation. That is the fallback, not the plan.

---

## Track A — Marcin: the Dataflow pipeline

The critical path. Infrastructure is applied and idle; only the
application is missing. Four pull requests.

> **Progress (2026-09-05).** A1 and A3 are implemented and A2's build
> assets are written: `dataflow/` holds the pipeline, Flex Template
> image, template spec metadata, Cloud Build config, launch script, and
> the promotion/verification SQL; `nlp/` holds the classifier contract, a
> deterministic stub, and the registry seam. What has *not* happened is
> the part that costs money — no image has been pushed and no Dataflow
> job has been launched, so `events` is still empty.

### A1 — Beam pipeline + NLP stub

`dataflow/pipeline.py`:

```
ReadFromPubSub(subscription, with_attributes=True,
               timestamp_attribute="created_utc")
  → parse JSON, validate, coerce types
  → detect language (authoritative; overrides the collector's advisory value)
  → classify sentiment (stub in this PR)
  → attach sentiment_label, sentiment_score, model_version, processed_at
  → WriteToBigQuery(events_landing, append)

dead-letter branch (unparseable, missing id, missing created_utc)
  → WriteToPubSub(dlq_topic)
```

The publisher already emits `created_utc` as a message attribute in
RFC 3339 form with a trailing `Z` (`publisher/replay.py`,
`build_message`), so `timestamp_attribute` works with no publisher-side
change and gives a correct event-time watermark despite replay time
compression. Ships with `nlp/stub/` and the classifier interface contract
(see "Contracts" below).

### A2 — Flex Template and first launch

`dataflow/Dockerfile` on `gcr.io/dataflow-templates-base/python312-template-launcher-base`
(verified present), `metadata.json` declaring `input_subscription`,
`output_table`, and `dlq_topic`, `cloudbuild.yaml`, and a `launch.sh`
that reads every parameter from `terraform output` rather than hardcoding
self-links and table references.

**Hard requirement: the image must be self-contained.** Workers launch
with `--disable-public-ips` and reach Google services over Private Google
Access only. There is no PyPI and no model download at runtime — every
dependency and every model file is baked in at build time. A worker that
tries to fetch anything at startup will hang until it times out. Build a
separate `--sdk_container_image` for the worker harness for the same
reason.

### A3 — Promotion MERGE and the reproducibility test

The `events_landing` → `events` MERGE is already specified in
`terraform/modules/bigquery/README.md`; this PR runs it and wraps it in
something repeatable. It must run *after* Dataflow drains a replay, never
when the publisher finishes — the publisher completing means "everything
published", not "everything processed".

Then the project's core reproducibility guarantee: run the same replay
twice and assert an identical set of rows in `events`, modulo
`model_version` and `processed_at` (both differ per run by construction —
which is exactly why `processed_at` is the MERGE tiebreaker). This is the test that makes the reproducibility claim in
the thesis a demonstrated property rather than an assertion.

### A4 — Gated Terraform resource and operations runbook

Optionally promote the launch into a `google_dataflow_flex_template_job`
gated on a variable defaulting to `null`, so it is `count = 0` until an
operator opts in — the pattern `cloud_run_jobs` already uses for
`reddit_image_uri`. Plus the drain procedure and a monitoring alert on job
failure and subscription backlog.

### Cost controls, from the first launch

A streaming Dataflow job bills continuously until drained and is the most
expensive resource in this project. Set `--max-workers=2`,
`--autoscaling_algorithm=THROUGHPUT_BASED`, and a small machine type.

**Enable Streaming Engine.** Without it, streaming workers default to
400 GB of persistent disk each; with it, 30 GB. On a job this small that
disk is the dominant line item, and the difference is more than an order
of magnitude.

---

## Track B — Oskar: data completeness

Independent of Track A. This track decides whether the sentiment curve
presented at the defence has four points or twelve.

**B1 — Steam collector** (assuming sign-off above). New service under
`collectors/steam/`, following the existing pattern: entry point,
`Dockerfile`, `cloudbuild.yaml`, README, tests, reusing
`collectors/common/` for author hashing, the GCS writer, the event-config
loader, and retry. Simpler than the Reddit collector in one respect —
with no API key there is no Secret Manager wiring, only the shared
author-hash salt. Terraform adds a service account and a Cloud Run Job
mirroring the YouTube ones. Then the collection runs themselves, windowed
per lifecycle event from launch onward.

**B2 — YouTube across the full cycle.** `collectors/config/youtube_videos.yaml`
holds 10 videos covering 5 of the 12 events. Missing entirely:
`english_voice_cast`, `baguette_trailer`, `xbox_developer_direct`,
`hotfix_1_2_2_ai_removal`, `thank_you_update_announce`,
`the_game_awards_2025`, `indie_game_awards_rescinded`, and
`one_year_anniversary_update`. Curate videos for each, then collect.
Budget the quota: 10,000 units per day, `commentThreads.list` at 1 unit
and `search.list` at 100, so discovery is the expensive half and the
collection spreads across several days.

**B3 — Verify the event dates.** Nine entries in
`collectors/config/events.yaml` carry a `# VERIFY` marker. Every window
tag, and therefore every chart in the thesis, depends on them. Confirm
each against public sources and remove the markers.

**B4 — Reload staging.** Re-run the publisher's load step
(`RUN_LOAD=only`) over the grown archive, then verify deduplication and
`event_tag` assignment across both sources.

Target: from 4,228 records to a dataset large enough that per-event
sentiment differences are statistically meaningful rather than anecdotal.

---

## Track C — Kacper: NLP, MLflow, presentation

**C1 — The real model**, behind the same interface as Marcin's stub. The
corpus is genuinely multilingual — YouTube carries French around
`baguette_trailer`, and the Steam sample was under half English. A single
multilingual classifier (for example an XLM-R sentiment model with
positive / neutral / negative output) is easier to justify in the write-up
than routing by detected language, and avoids the question of what happens
when detection is wrong on a six-word comment. Weights must be baked into
the Flex Template image at build time (see A2), so measure image size and
worker start-up early — it constrains Marcin's build.

**C2 — Evaluation.** A gold set of roughly 300 hand-labelled comments
gives accuracy and F1 for the evaluation chapter. With Steam in scope,
`voted_up` supplies a second, much larger weak-label set — the
disagreement between the two is itself a result worth reporting.

**C3 — MLflow.** The largest remaining architectural gap: `nlp/registry/`
plus a `terraform/modules/mlflow/`. Hosting needs deciding before any of
it starts (see "Open decisions").

**C4 — Presentation.** Looker Studio dashboard and the BigQuery
authorised views it reads through — listed as outstanding in the
`bigquery` module README.

---

## Contracts between tracks

**A ↔ C, the classifier interface.** Marcin defines it in A1 alongside
the stub; Kacper replaces the implementation without touching the
pipeline. That swappability is the whole reason the NLP layer starts as a
stub — the real model drops in through the registry without disturbing
the surrounding code. Something of the shape `classify(text) -> (label, score, model_version)` plus
`detect_language(text) -> str`. **Agree this in the first week** — once
both tracks are building against it, changing the signature costs both.

**A ↔ B, no dependency.** Marcin develops against the 4,228 records
already in staging. When Oskar's collection lands, the same replay simply
carries more.

**Unassigned.** The `cloud_build/` module (roadmap item 6) belongs to
whoever finishes their track first.

---

## Open decisions

1. **Steam as the second source** — needs team and supervisor sign-off,
   plus an ADR. Everything in Track B assumes yes.
2. **Beam windowing.** Enrich element-by-element and aggregate in
   BigQuery, or compute event-time windowed aggregates in Beam?
   Element-wise is simpler and more obviously reproducible. Windowed
   aggregation is better material for the streaming chapter — if the
   thesis needs it, add it as a side output rather than the main branch.
3. **Streaming Engine** — recommended on, for the disk cost above.
4. **One multilingual model or per-language routing** — recommended
   single multilingual, for the reasons in C1.
5. **MLflow hosting.** Cloud Run plus Cloud SQL plus GCS artifacts is the
   correct shape but adds a recurring cost and a Terraform module. Decide
   early; Track C cannot start C3 without it.
6. **How the MERGE runs** — manual `bq query`, a scheduled query, or a
   Cloud Run Job. Whatever the answer, it triggers after the Dataflow
   drain, not after the publisher exits.

---

## Sequencing

The first milestone that matters is a single record travelling from
`raw_staging` through Pub/Sub and Dataflow into `events` with a sentiment
label attached — even a stub label. Everything in Track A up to A3 serves
that. Tracks B and C run in parallel and neither blocks it.

After that the order is: real data volume (B), real model (C), then
promotion of the launch into Terraform and the dashboard on top.
