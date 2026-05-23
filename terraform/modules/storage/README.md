# modules/storage

Provisions the project's GCS buckets.

## What this creates

- **`co-raw-archive-{env}`** — regional, immutable raw archive that collectors write JSONL into. Standard → Coldline transition at 30 days. Versioning is off (data is append-only by convention). Uniform bucket-level access, public access prevention enforced.
- **`co-tf-artifacts-{env}`** — regional, disposable bucket for Cloud Build logs and Dataflow Flex Template payloads. Hard-deletes objects at 30 days.

Both buckets sit in the region passed via `var.region`. Project standard is `europe-central2`.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `env` | string | yes | — | Environment name (e.g. `dev`, `prod`) — suffixed into bucket names |
| `region` | string | yes | — | GCP region for both buckets |
| `labels` | map(string) | yes | — | Labels attached to every bucket |
| `raw_archive_autodelete_days` | number | no | `0` | If > 0, raw archive objects are deleted after this many days. `0` disables hard-delete and lets the archive grow indefinitely. |

## Outputs

| Name | Description |
|---|---|
| `raw_archive_bucket_name` | Name of the raw archive bucket |
| `raw_archive_bucket_url` | `gs://` URL of the raw archive bucket |
| `tf_artifacts_bucket_name` | Name of the artifacts bucket |
| `tf_artifacts_bucket_url` | `gs://` URL of the artifacts bucket |

## Notes

- **No IAM bindings yet.** Collector / Dataflow / Cloud Build service accounts do not exist yet (they land in the `iam/` module). When they do, bucket-level IAM bindings — `objectAdmin` for collector SAs on the raw archive, `objectViewer` for the Dataflow worker, `objectAdmin` for Cloud Build on artifacts — get added here, **not** in a central IAM module.
- Until those workload SAs exist, the runner SA reaches both buckets via its project-level `roles/storage.admin`.
- The raw archive intentionally has **no versioning**. Collectors must write to new object paths under `{source}/{event_id_or_general}/{YYYY}/{MM}/{DD}/{HH}/{batch}.jsonl.gz` rather than overwriting. Versioning would mask bugs in that contract.
- `raw_archive_autodelete_days` is meant for dev tear-downs only. Leave it at `0` for `prod` where the raw archive is the only re-runnable source of truth.
