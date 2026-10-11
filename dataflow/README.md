# dataflow — streaming sentiment pipeline

The Apache Beam pipeline that turns the replayed Pub/Sub stream into
enriched rows in BigQuery. It is the step that finally puts a sentiment
label on the data the collectors gathered and the publisher replays.

```
Pub/Sub subscription (ordered replay, event time = created_utc)
      │
      ├─ parse + validate ──► unparseable ──► dead-letter topic
      │
      ├─ batch
      ├─ detect language (authoritative)
      ├─ classify sentiment (nlp registry)
      ├─ stamp processed_at
      │
      ▼
BigQuery events_landing (append-only)
      │
      ▼  dataflow/promote.sh  (after the job drains)
BigQuery events (one row per id)
```

## Design decisions

**The pipeline writes `events_landing`, never `events`.** The analytical
table is written only by the promotion MERGE, after a replay drains. That
split is what lets this job be at-least-once: duplicate deliveries and
repeated passes over the same `id` collapse downstream, so reproducibility
does not depend on exactly-once semantics from Pub/Sub or Beam. It is also
why the BigQuery write uses the Storage Write API in its at-least-once
mode — the cheaper option, and the guarantee the design already provides.

**Event time comes from the record.** The replay compresses months into
minutes, so the moment a message was published says nothing about when
the opinion was written. `ReadFromPubSub` is given
`timestamp_attribute="created_utc"`, the attribute the publisher already
sets, so the watermark tracks the real chronology of the events. Anything
windowed added later is then correct by default rather than by accident.

**A bad record is dead-lettered; a hard-to-classify one is not.** Only
structural failures — malformed JSON, a missing `id` or `created_utc` —
go to the dead-letter topic. A comment the language detector or the model
cannot make sense of still reaches BigQuery with nulls where appropriate.
Dropping an opinion because a model was unsure would quietly bias the
analysis, which is the one failure mode this project cannot tolerate.

**The stub classifier is deterministic, not random.** The obvious
placeholder is a coin flip, but that would break the guarantee that the
same replay produces the same rows — and it would break it for reasons
that have nothing to do with the pipeline. `nlp/stub/` is a small keyword
rule with a hash-derived fallback, so it is reproducible while still
spreading labels across all three classes. See `nlp/base.py` for the
contract a real model must honour.

## Layout

| File | Purpose |
|---|---|
| `pipeline.py` | Beam graph and the two DoFns; the only module that imports the SDK |
| `transforms.py` | Pure record logic — parse, validate, language, row building. No Beam import, so it is unit-testable without a runner |
| `options.py` | Launch parameters, all sourced from `terraform output` |
| `Dockerfile` | Flex Template image, serving as both launcher and worker harness |
| `metadata.json` | Parameter declarations and validation for the template spec |
| `cloudbuild.yaml` | Builds the image and the template spec |
| `launch.sh` | Starts a job from the built template |
| `promote.sh` | Coverage check → MERGE → reproducibility fingerprint |
| `replay.cloudbuild.yaml` | The whole replay as one Cloud Build run (`co-replay-dev`) |
| `promote.sql` / `coverage.sql` / `verify.sql` | The statements `promote.sh` runs |

## The image must be self-contained

Workers launch with `--disable-public-ips` and reach Google APIs over
Private Google Access only. **There is no PyPI or Hugging Face Hub at
runtime.** Every pip dependency is installed at build time.
`google-cloud-aiplatform` is in the image so workers can call a Vertex
Endpoint; DistilBERT **weights are not** `COPY`ed in. A worker that
tries to fetch something from the public internet hangs until it times
out, which presents as a job that starts and then does nothing.

This is also why the Dockerfile builds one image that serves as both the
Flex Template launcher and the Beam SDK worker harness: the launch passes
it back as `sdk_container_image`, so the workers run the exact image the
template was built from.

## Build

Cloud Build builds this image automatically (see `terraform/modules/cloud_build`):

- **Pull request** touching `dataflow/` or `nlp/` — image build only. The
  Dockerfile's import check runs, nothing is pushed.
- **Merge to `main`** — the image is pushed tagged with the full commit SHA,
  and two template specs pinned to its **digest** are written:
  `gs://co-dataflow-temp-dev/templates/sentiment-pipeline-<sha>.json`
  (immutable, one per commit) and `.../sentiment-pipeline.json` (current).

No build ever starts a Dataflow job. `launch.sh` uses the current spec, or
`launch.sh --sha <commit>` to launch the template of a specific commit.

Manual build from the repo root, e.g. for a branch that is not merged yet:

```bash
gcloud builds submit --region=europe-central2 \
  --service-account=projects/pop-vibe-check/serviceAccounts/co-cloud-build-sa-dev@pop-vibe-check.iam.gserviceaccount.com \

  --gcs-source-staging-dir=gs://co-tf-artifacts-dev/cloudbuild/source \
  --config dataflow/cloudbuild.yaml \
  --substitutions=COMMIT_SHA=$(git rev-parse HEAD),_DEPLOY=true .
```

`--service-account` is required: without it the build runs as the Compute
Engine default service account, which holds no project roles. The build SA
reads its uploaded source with its own credentials, hence
`--gcs-source-staging-dir` pointing at the prefix it can read. Note that a
manual `_DEPLOY=true` run also overwrites the current spec.

## Run

### One replay, as a build (the normal path)

`co-replay-dev` runs the whole sequence — launch, publish, wait, drain,
promote, fingerprint — as one Cloud Build run from
[`replay.cloudbuild.yaml`](replay.cloudbuild.yaml). It is a **manual**
trigger: a replay starts a streaming job that bills until drained, so no
push starts one.

```bash
gcloud builds triggers run co-replay-dev --region=europe-central2 \
  --branch=main --substitutions=_MODEL=stub
```

`_MODEL=vertex` needs nothing else: the trigger carries the Endpoint id,
project and region from `terraform output`.

Useful substitutions (all optional): `_MODEL` (`stub` / `vertex`),
`_TEMPLATE_SHA` (launch a specific commit's template instead of the
current one), `_RUN_LOAD`, `_EVENT_ID`, `_WINDOW_FROM`, `_WINDOW_TO`,
`_SPEEDUP`, `_MAX_SLEEP_SECONDS` (publisher parameters — anything left
empty keeps the job's deployed default), `_MAX_WORKERS`, `_MACHINE_TYPE`,
`_PROMOTE=false` (replay and drain without touching `events`).

Two properties make this better than running the steps by hand:

- **The promotion cannot run too early.** It runs after the job is
  drained, never merely after the publisher exits — the failure this
  ordering exists to prevent (`promote.sh`'s header explains it).
- **The drain cannot run too early either.** The build waits until every
  staged id has landed *in this run* before draining. A drain stops
  pulling from Pub/Sub, so draining a pipeline that is still behind
  abandons the rest of the backlog: the run looks successful, and the
  records it never processed keep whatever labels an earlier replay gave
  them. If the records do not all arrive within
  `_WAIT_TIMEOUT_MINUTES`, the build drains and fails **without
  promoting**. (An `_EVENT_ID` replay cannot compute its expected count
  — the window comes from `events.yaml` — so it falls back to waiting for
  the landed count to stop rising, and says so in the log.)
- **The drain step always runs**, even when the replay fails, so a failed
  run does not leave a streaming job billing. The gap it cannot close is
  the build itself timing out or being cancelled; the "Dataflow job
  running too long" alert covers that (`terraform/modules/monitoring/`).

The build's log is the record of the run: the commit, the parameters, the
coverage check and the fingerprint.

### By hand

Have the publisher put messages on the topic first (see
`publisher/README.md`), then:

```bash
dataflow/launch.sh                  # asks for confirmation
dataflow/launch.sh --yes            # skips it
dataflow/launch.sh --model stub     # pick a registered classifier
dataflow/launch.sh --model vertex   # DistilBERT via Vertex Endpoint
```

`--model vertex` reads `VERTEX_ENDPOINT_ID` / `VERTEX_PROJECT` /
`VERTEX_LOCATION` from the environment, or from terraform outputs
`vertex_endpoint_id`, `vertex_project_id`, `vertex_location`. The
Endpoint must already exist and have a deployed replica — see
`nlp/README.md`. The stub stays the default so a first e2e replay does
not need a GPU.

Every infrastructure value — region, worker SA, subnetwork, temp and
staging locations, subscription, table, DLQ topic — is read from
`terraform output`, so the script cannot drift from what is deployed.
Each one can also be supplied through the environment (`REGION`,
`WORKER_SA`, `SUBNETWORK`, `TEMP_LOCATION`, `STAGING_LOCATION`,
`SPEC_DIR`, `INPUT_SUBSCRIPTION`, `OUTPUT_TABLE`, `DLQ_TOPIC`), which is
how the replay build runs the same script without Terraform state.
`promote.sh` works the same way (`PROJECT_ID`, `DATASET`,
`RAW_STAGING_TABLE_ID`, `EVENTS_LANDING_TABLE_ID`, `EVENTS_TABLE_ID`).

### Cost

**A streaming job bills continuously until it is drained.** It is the most
expensive resource in this project, and nothing about `terraform apply`
starts one — that is deliberate.

The launch defaults to at most two `e2-standard-2` workers with Streaming
Engine enabled. Streaming Engine is a cost decision, not a performance
one: without it each streaming worker provisions a 400 GB persistent disk
instead of 30 GB, which on a job this small is the dominant line item.

Stop a job with **drain**, not cancel, so in-flight records still reach
BigQuery:

```bash
gcloud dataflow jobs list --region=europe-central2 --status=active
gcloud dataflow jobs drain JOB_ID --region=europe-central2
```

## Promote and verify

Once the job has drained the replay:

```bash
dataflow/promote.sh --check-only    # coverage only, promotes nothing
dataflow/promote.sh                 # coverage, MERGE, fingerprint
```

The coverage step compares distinct ids in `raw_staging` against
`events_landing`. **A non-zero `missing_ids` means the replay has not
finished** — the publisher exiting means "everything published", not
"everything processed", and promoting early silently truncates the tail of
the run.

The fingerprint step is the reproducibility check. It hashes every column
except `model_version` and `processed_at` (which differ per run by
construction) and sums the per-row hashes, so the result is
order-independent. To demonstrate the guarantee:

1. Replay, drain, promote, record `row_count` and `fingerprint`.
2. Truncate `events_landing`, replay the same window again, drain,
   promote.
3. The two fingerprints must match.

## Tests

```bash
pytest dataflow/tests nlp/tests
```

`test_transforms.py` needs no Beam install; `test_pipeline.py` skips
itself when the SDK is absent and otherwise exercises both DoFns on the
local runner. The Pub/Sub and BigQuery IOs are not covered by unit tests —
they need real endpoints, and the first real launch is what exercises
them.

## If the job runs but nothing happens

Two IAM gaps make the pipeline consume nothing while reporting healthy —
the job reaches `JOB_STATE_RUNNING`, autoscales, and logs only warnings.
**Watch the subscription backlog, not the job state.** Both are fixed in
the `pubsub` module; the symptoms are recorded here because the failure
mode gives no useful error:

- `roles/pubsub.subscriber` grants `subscriptions.consume` but not
  `subscriptions.get`, which Dataflow reads before consuming. Symptom:
  "Querying the configuration of Pub/Sub subscription … failed".
- Reading with a custom event-time attribute makes Dataflow create its own
  watermark-tracking subscription on the source topic. Symptom: "Creating
  watermark tracking pubsub subscription … failed".

See [docs/phase-1-dataflow.md](../docs/phase-1-dataflow.md) for the full
account of the first run, including the reproducibility bug that came
from langdetect's behaviour under Dataflow's threading.

## Known gaps

- **BigQuery rejections are routed best-effort.** Rows the table refuses
  are sent to the dead-letter topic, but the Beam attribute exposing them
  differs between write methods and across releases; if it is missing the
  pipeline logs a warning and those rejections show up only in the job's
  error counters rather than failing the launch.
- **No windowed aggregation.** The pipeline enriches record by record;
  per-event aggregates are computed in BigQuery. Event time is wired
  correctly, so a windowed branch can be added without reworking the read.
- **The launch is not a Terraform resource.** A gated
  `google_dataflow_flex_template_job` was considered and rejected:
  with applies going through an approval-gated Cloud Build trigger,
  starting a job would mean editing the tfvars secret and approving an
  apply, and stopping one would mean deleting a resource. The manual
  `co-replay-dev` trigger does the same job with an explicit drain.
- **Alerting covers the job, not the data.** Job failure, a job left
  running, an ageing backlog and dead letters all alert
  (`terraform/modules/monitoring/`). A replay that lands *wrong* rows
  does not — that is what the coverage check and the fingerprint are for.
