# ADR 0002 — A replay is one build, and it may not be promoted until complete

- **Status:** Accepted
- **Date:** 2026-10-11
- **Affects:** `dataflow/replay.cloudbuild.yaml`, `dataflow/launch.sh`,
  `dataflow/promote.sh`, the `co-replay-dev` trigger
- **Relates to:** the reproducibility requirement (every number in the
  thesis must be regeneratable from the raw archive plus committed code at
  a known commit) and the ordering decision the publisher exists to serve

## Context

A replay was a sequence of manual commands: launch the Flex Template, run
the publisher, watch the job, drain it, run the promotion MERGE. Three
problems followed from that, and two of them cost real runs.

**Promotion could run too early.** The publisher exiting means
"everything published", not "everything processed". Promoting at that
moment silently truncates the tail of a run.

**Draining could run too early, which is worse.** A drain stops the job
pulling from Pub/Sub; it does not finish the backlog. Draining a pipeline
that is still behind abandons whatever is left. This is exactly what
happened on the first XLM-R replay: the wait loop treated "the landed
count stopped changing for three minutes" as "finished", which a stalled
pipeline looks identical to. 10,002 of 12,254 records were processed,
3,190 messages were left in the subscription, and the run reported
success. `events` came out mixed — 10,002 rows labelled by the new model,
2,252 still labelled by the stub from an earlier replay.

**The coverage check did not catch it**, because it compares staged ids
against everything ever landed, and those ids *had* landed, during earlier
runs.

**And a run was not a citable artifact.** "I ran these five commands on
Tuesday" is not a provenance record.

## Decision

**One replay is one Cloud Build run**, from `co-replay-dev`:

```
launch → publish → wait for completeness → drain → promote → fingerprint
```

Three rules make it trustworthy:

1. **The drain waits for completeness, not for quiet.** The build computes
   the expected record count from `raw_staging` (respecting an explicit
   window) and waits until that many distinct ids have landed **in this
   run**, identified by `processed_at >= run start`. A count that stops
   rising is no longer evidence of anything.
2. **An incomplete replay is never promoted.** If the records do not all
   arrive within the timeout, the build drains the job and **fails**.
   `events` is left as it was.
3. **The drain always runs**, including when the replay step fails. The
   step is marked `allowFailure` so the build continues to the drain, and
   a later step turns the failure back into a failed build. An undrained
   streaming job bills until someone notices.

The trigger is **manual**. A replay starts a streaming Dataflow job, the
most expensive resource in the project; no push to `main` may start one.

A run is now identified by its build: the commit, the parameters, the
coverage check and the reproducibility fingerprint are all in one log.

## Consequences

- The reproducibility claim is demonstrated through a different execution
  path than the one that first produced it. The same replay reproduced
  fingerprint `-10329993396494980651` from CI, with the pipeline image
  pinned by digest rather than by tag.
- A replay with a different model is one substitution (`_MODEL=vertex`),
  so the whole dataset can be relabelled in one auditable run instead of
  partially.
- The window case is weaker by construction: an `--event_window` replay
  resolves its window from `events.yaml`, which the expected-count query
  cannot reproduce, so that mode falls back to the old "count stopped
  rising" rule and says so in the log.
- The build timing out or being cancelled is the one case the always-drain
  rule cannot cover. The "Dataflow job running too long" alert covers it
  instead.

## Alternatives considered

- **A gated `google_dataflow_flex_template_job` in Terraform.** Rejected.
  With applies going through an approval-gated trigger, starting a job
  would mean editing the tfvars secret and approving an apply, and
  stopping one would mean deleting a resource — a drain expressed as a
  destroy. The manual trigger does the same work with an explicit drain.
- **Promotion as a scheduled query or a mode on the publisher job.** Both
  reintroduce the ordering hazard: neither knows whether the pipeline has
  drained. Promotion has to be downstream of the drain, and a build is the
  cheapest thing that can express "after".
- **Keeping the runbook and documenting the pitfalls.** Tried. The
  pitfalls were documented in `promote.sh`'s own header and the run still
  promoted a partial dataset.
