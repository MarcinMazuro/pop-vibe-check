# Phase 1 — Dataflow: first end-to-end run

The pipeline that was missing between the Pub/Sub replay and the `events`
table now runs. Replayed records are parsed, language-detected,
classified, written to `events_landing`, and promoted into `events`. The
project's reproducibility guarantee — same replay twice, same rows — is
demonstrated rather than asserted.

Date: 2026-09-05.

---

## Result

| | |
|---|---|
| Records processed | 4228 (the full YouTube dataset) |
| Rows in `events` | 4228 — one per `id` |
| Dead-lettered | 0 |
| Rows with no sentiment | 0 |
| Reproducibility fingerprint | `-10329993396494980651`, identical across two replays |
| Ids whose language differed between replays | 0 |
| Ids whose sentiment differed between replays | 0 |

Sentiment across the four collected lifecycle events (stub classifier, so
these numbers describe the plumbing, not public opinion):

| event_tag | pos | neu | neg |
|---|---|---|---|
| `xbox_showcase_reveal` | 784 | 477 | 450 |
| `gameplay_trailer_flying_waters` | 537 | 352 | 368 |
| `launch` | 400 | 238 | 271 |
| `critical_acclaim_wave` | 156 | 92 | 103 |

The job was drained after verification. Nothing streaming is left
running.

## How it was deployed

Cloud Build could not be used. `gcloud builds submit` runs as the Compute
Engine default service account, which holds **no project roles at all**,
so the build failed before starting on `storage.objects.get` against its
own source bucket. The `cloud_build/` Terraform module that would fix this
properly is still an open roadmap item, so the image was built locally and
pushed by hand — the same path the YouTube collector and publisher images
took. `dataflow/cloudbuild.yaml` is committed and correct; it needs either
that module or a `--service-account` flag pointing at
`co-cloud-build-sa-dev` before it will run.

Deployment is otherwise: build the image, push it to Artifact Registry
under the commit SHA, `gcloud dataflow flex-template build` to write the
spec, then `dataflow/launch.sh`.

## Four launch failures, and what each one taught

The pipeline did not start on the first, second, or third attempt. Each
failure was a real gap, and each fix is now covered by a test or lives in
Terraform.

### 1. The Storage Write API needs an explicit schema

`ValueError: A schema is required in order to prepare rows for writing
with STORAGE_WRITE_API`. Unlike streaming inserts, it will not read the
schema off the destination table, even with `CREATE_NEVER`.

Fixed by reading the schema from the target table when the graph is
built, rather than declaring it a second time in Python where it would be
free to drift from the Terraform-managed table it has to match.

**Caught late because nothing had ever assembled the whole graph.** The
unit tests exercised the DoFns in isolation. There are now
graph-construction tests, so this class of failure surfaces in CI instead
of in a queued job.

### 2. The Storage Write API needs Java

`RuntimeError: Java must be installed on this system to use this
transform/runner`. In the Python SDK that sink is a cross-language
transform: it starts a Java expansion service at construction and needs a
Java SDK harness on the workers at runtime.

Neither belongs in an image that is deliberately self-contained because
the workers have no public IPs. The default is now `STREAMING_INSERTS`,
which is pure Python. The per-byte saving the Storage Write API offers is
meaningless at this volume — a whole replay is a few megabytes — and
at-least-once remains correct either way, because the landing table is
append-only and the promotion MERGE collapses duplicates by `id`.
`STORAGE_WRITE_API` stays selectable for anyone who adds the JRE.

### 3. `roles/pubsub.subscriber` is not enough for Dataflow

The job reached `JOB_STATE_RUNNING`, reported healthy, and consumed
nothing. The backlog sat at 4228 for over an hour. The only clue was a
warning that sounded like a performance note:

> Querying the configuration of Pub/Sub subscription … failed. … Specific
> error: User not authorized to perform this action.

`roles/pubsub.subscriber` grants `subscriptions.consume` but not
`subscriptions.get`, and Dataflow reads the subscription's configuration
before consuming. Fixed with a `roles/pubsub.viewer` binding in the
`pubsub` module.

### 4. Custom event time requires creating a tracking subscription

With the viewer grant in place the real blocker appeared:

> Creating watermark tracking pubsub subscription
> `…__df_internal…` to topic … failed with error: User not authorized.

Because the pipeline reads Pub/Sub with a custom event-time attribute
(`created_utc` — publish time is meaningless when the replay compresses
months into minutes), Dataflow creates its own tracking subscription on
the source topic to derive a watermark, and deletes it on drain. That
needs `pubsub.subscriptions.create` plus
`pubsub.topics.attachSubscription`.

The documented answer is `roles/pubsub.editor` at project scope, which
also grants publish and delete on every topic and subscription in the
project. The `pubsub` module defines a **custom role** with exactly the
five permissions instead. Managing custom roles in turn required
`roles/iam.roleAdmin` on the Terraform runner SA, added in
`terraform/bootstrap/` — the same pattern as the earlier
`compute.securityAdmin` addition for firewall rules.

**Both of these fail silently.** The job runs, autoscales, reports
healthy, and processes nothing. Watch the subscription backlog, not the
job state.

## The reproducibility bug

With the pipeline running, the first two replays produced **different
results**: same row count, same ids, but 68 records disagreed on
`language`. Sentiment and every other column matched exactly. Since
`language` is authoritative in the `events` table, that alone made a
replay non-reproducible — the central claim the whole architecture exists
to support.

It had two independent causes, both in language detection.

### Cause 1: a seed set as an import-time side effect

langdetect samples n-grams randomly and seeds a fresh RNG per detection
from `DetectorFactory.seed`, a class attribute defaulting to `None` —
meaning "seed from system entropy". The seed was being set at module
import. That looked equivalent to setting it per call and was not: on the
workers the module reached the detector without the assignment having
taken effect. Short text is where it shows — unseeded, `"Hell yeah!"`
drifts between `en`, `id` and `tr`.

The seed is now set inside `detect_language` on every call, so
determinism does not depend on how the module was loaded.

### Cause 2: a cold-start race on profile loading

The seed fix was necessary but not sufficient: 87 records still differed,
and the pattern gave it away. **Cold workers labelled plain English text
`af`, `it` or `no`; warm workers labelled the same text `en`.**

langdetect publishes its factory global *before* the profiles finish
loading:

```python
if _factory is None:
    _factory = DetectorFactory()
    _factory.load_profile(PROFILES_DIRECTORY)
```

A thread arriving in that window sees a non-`None` factory, skips
loading, and detects against whatever profiles exist so far —
alphabetically, hence `af` and `da` — or raises `Need to load profiles`
and the record ends up with no language at all. Dataflow runs several
bundle threads per worker, so a cold worker hits this on essentially
every start.

Reproduced locally: cold plus twelve concurrent threads gives `af`/`da`/
`en` and lost languages on 3 of 3 trials; warm and sequential gives `en`
every time.

The first initialisation is now serialised behind a lock and warmed up in
`DoFn.setup`, before any bundle thread reaches the detector. Afterwards
the factory is read-only, so the hot path stays lock-free. The tests reset
langdetect to its cold state and hammer it from twelve threads, so they
fail if the warm-up is removed.

**Worth keeping in mind for the real model.** The bug was not in our code
but in how a third-party library behaves under the concurrency Dataflow
imposes. Any model added later — especially one loading files at start-up
— deserves the same cold-start scrutiny, and the fingerprint check is how
to catch it.

## Verifying a run

```bash
dataflow/promote.sh --check-only   # staged vs landed; promotes nothing
dataflow/promote.sh                # coverage, MERGE, fingerprint
```

Coverage compares distinct ids in `raw_staging` against `events_landing`.
A non-zero `missing_ids` means the replay has not finished draining —
the publisher exiting means "everything published", not "everything
processed".

The fingerprint hashes every column except `model_version` and
`processed_at` (which differ per run by construction) and sums the
per-row hashes, so it is order-independent. Two replays of the same data
must produce the same number.

One bug found here too: `FARM_FINGERPRINT` returns a full-range `INT64`,
so summing a few thousand of them overflows a 64-bit accumulator and the
query fails outright. The sum is cast to `NUMERIC`.

## Known gaps

- **Cloud Build is unusable** until the `cloud_build/` module exists or
  the build is pointed at `co-cloud-build-sa-dev`. Images are built and
  pushed by hand meanwhile.
- **Language detection is poor on short comments.** 3467 of 4228 records
  came back `en`; the rest include obvious misfires (`af`, `tl`, `et`) on
  one- and two-word comments. It is deterministic now, which is what
  reproducibility requires, but deterministic is not the same as correct.
  Worth revisiting when the real model lands, since that model may carry
  its own language handling.
- **BigQuery rejections are routed best-effort.** Rows the table refuses
  go to the dead-letter topic, but the Beam attribute exposing them
  differs between write methods and across releases; if absent the
  pipeline logs a warning rather than failing the launch.
- **The promotion step is a script, not infrastructure.** Whether it
  becomes a `RUN_MERGE` mode on the publisher job or a separate one-shot
  job is still open.
