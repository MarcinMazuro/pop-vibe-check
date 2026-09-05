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
| `promote.sql` / `coverage.sql` / `verify.sql` | The statements `promote.sh` runs |

## The image must be self-contained

Workers launch with `--disable-public-ips` and reach Google services over
Private Google Access only. **There is no PyPI at runtime.** Every
dependency is installed at build time, and when a real model replaces the
stub its weights are `COPY`ed into the image — never downloaded on
start-up. A worker that tries to fetch something hangs until it times out,
which presents as a job that starts and then does nothing.

This is also why the Dockerfile builds one image that serves as both the
Flex Template launcher and the Beam SDK worker harness: the launch passes
it back as `sdk_container_image`, so the workers run the exact image the
template was built from.

## Build

```bash
gcloud builds submit --config dataflow/cloudbuild.yaml .
```

**This does not work yet.** `gcloud builds submit` runs as the Compute
Engine default service account, which holds no project roles, so the build
fails on its own source bucket before starting. Until the `cloud_build/`
Terraform module exists (or the build is pointed at
`co-cloud-build-sa-dev` with `--service-account`), build and push by hand,
which is how the collector and publisher images were deployed too:

```bash
SHA=$(git rev-parse HEAD)
IMG=europe-central2-docker.pkg.dev/pop-vibe-check/co-images-dev/sentiment-pipeline:$SHA
docker build -f dataflow/Dockerfile -t "$IMG" .
docker push "$IMG"
gcloud dataflow flex-template build \
  gs://co-dataflow-temp-dev/templates/sentiment-pipeline.json \
  --image="$IMG" --sdk-language=PYTHON --metadata-file=dataflow/metadata.json
```

Produces the image tagged with the commit SHA and writes the template spec
to `gs://co-dataflow-temp-dev/templates/sentiment-pipeline.json`, pinning
that exact image.

## Run

Have the publisher put messages on the topic first (see
`publisher/README.md`), then:

```bash
dataflow/launch.sh                  # asks for confirmation
dataflow/launch.sh --yes            # skips it
dataflow/launch.sh --model stub     # pick a registered classifier
```

Every infrastructure value — region, worker SA, subnetwork, temp and
staging locations, subscription, table, DLQ topic — is read from
`terraform output`, so the script cannot drift from what is deployed.

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
- **The promotion step is a script, not infrastructure.** Whether it
  becomes a `RUN_MERGE` mode on the publisher job or a separate one-shot
  job is still open; the Dataflow worker SA already holds the grants
  either would need.
