# modules/storage

Provisions the project's GCS buckets.

## What this creates

- **`{name_prefix}-raw-archive-{env}`** — regional, immutable raw archive that collectors write JSONL into. Standard → Coldline transition at 30 days. Versioning is off (data is append-only by convention). Uniform bucket-level access, public access prevention enforced.
- **`{name_prefix}-tf-artifacts-{env}`** — regional, disposable bucket for Cloud Build logs and Dataflow Flex Template payloads. Hard-deletes objects at 30 days.

Both buckets sit in the region passed via `var.region`. Project standard is `europe-central2`. `name_prefix` is short (≤ 8 chars) and identifies the case study — e.g. `co` for Clair Obscur, `w4` for Witcher 4 — so multiple releases can coexist in one GCP project.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `name_prefix` | string | yes | — | Short prefix prepended to bucket names. Lowercase alphanumeric / hyphen, 2-8 chars. |
| `env` | string | yes | — | Environment name (e.g. `dev`, `prod`) — suffixed into bucket names |
| `region` | string | yes | — | GCP region for both buckets |
| `labels` | map(string) | yes | — | Labels attached to every bucket |
| `raw_archive_autodelete_days` | number | no | `0` | If > 0, raw archive objects are deleted after this many days. `0` disables hard-delete and lets the archive grow indefinitely. |
| `force_destroy_raw_archive` | bool | no | `false` | One-off escape hatch for `terraform destroy` when the raw archive bucket still has objects. See "Tearing down" below. |
| `force_destroy_artifacts` | bool | no | `false` | Same escape hatch for the artifacts bucket. |

## Outputs

| Name | Description |
|---|---|
| `raw_archive_bucket_name` | Name of the raw archive bucket |
| `raw_archive_bucket_url` | `gs://` URL of the raw archive bucket |
| `tf_artifacts_bucket_name` | Name of the artifacts bucket |
| `tf_artifacts_bucket_url` | `gs://` URL of the artifacts bucket |

## Tearing down

`force_destroy = false` is the default on both buckets — GCS will refuse to delete a bucket that still has objects. That is a deliberate barrier; the raw archive especially is the only re-runnable source of truth for collector data, accidental deletion is unrecoverable.

When you genuinely want to recreate a bucket, set the override on the CLI for both the apply that lifts the barrier and the destroy itself, same pattern as the bootstrap state bucket:

```bash
terraform apply  -var="force_destroy_raw_archive=true" -auto-approve
terraform destroy -var="force_destroy_raw_archive=true" -auto-approve
```

Or `force_destroy_artifacts=true` for the artifacts bucket. The defaults flip back to `false` on the next normal apply — no code edit, no risk of leaving a bucket unprotected.

## Notes

- **No IAM bindings yet.** Collector / Dataflow / Cloud Build service accounts do not exist yet (they land in the `iam/` module). When they do, bucket-level IAM bindings — `objectAdmin` for collector SAs on the raw archive, `objectViewer` for the Dataflow worker, `objectAdmin` for Cloud Build on artifacts — get added here, **not** in a central IAM module.
- Until those workload SAs exist, the runner SA reaches both buckets via its project-level `roles/storage.admin`.
- The raw archive intentionally has **no versioning**. Collectors must write to new object paths under `{source}/{event_id_or_general}/{YYYY}/{MM}/{DD}/{HH}/{batch}.jsonl.gz` rather than overwriting. Versioning would mask bugs in that contract.
- `raw_archive_autodelete_days` is meant for dev tear-downs only. Leave it at `0` for `prod` where the raw archive is the only re-runnable source of truth.
