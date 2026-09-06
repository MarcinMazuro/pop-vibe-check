# modules/storage

Provisions the project's GCS buckets.

## What this creates

- **`{name_prefix}-raw-archive-{env}`** — regional, immutable raw archive that collectors write JSONL into. Standard → Coldline transition at 30 days. Versioning is off (data is append-only by convention). Uniform bucket-level access, public access prevention enforced.
- **`{name_prefix}-tf-artifacts-{env}`** — regional bucket for Cloud Build logs, generic build artifacts, and NLP training caches. Hard-deletes objects under `logs/` and `cloudbuild/` at 30 days; the `nlp/` prefix (dataset cache, MLflow runs, exported weights) is retained. The ML trainer SA has `roles/storage.objectAdmin` on this bucket.
- **`{name_prefix}-dataflow-temp-{env}`** — regional bucket for Dataflow's runtime staging/temp files and the Flex Template spec. **Prefix-scoped** lifecycle: hard-deletes objects older than 7 days **only under `staging/` and `temp/`** — `templates/` (the spec every launch reads) is exempt and survives indefinitely. Plus `roles/storage.objectAdmin` on this bucket for the Dataflow worker SA.

All three buckets sit in the region passed via `var.region`. Project standard is `europe-central2`. `name_prefix` is short (≤ 8 chars) and identifies the case study — e.g. `co` for Clair Obscur, `w4` for Witcher 4 — so multiple releases can coexist in one GCP project.

### Why the dataflow-temp lifecycle rule is prefix-scoped

A bucket-wide "delete after 7 days" would take `templates/` with it, and the Flex Template spec under `templates/` is what `gcloud dataflow flex-template run` reads at launch — deleting it makes the job unlaunchable a week after the template was built. The lifecycle rule therefore matches only `staging/` and `temp/` (the churn prefixes), leaving `templates/` untouched. Do **not** widen it to the whole bucket.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `name_prefix` | string | yes | — | Short prefix prepended to bucket names. Lowercase alphanumeric / hyphen, 2-8 chars. |
| `env` | string | yes | — | Environment name (e.g. `dev`, `prod`) — suffixed into bucket names |
| `region` | string | yes | — | GCP region for both buckets |
| `labels` | map(string) | yes | — | Labels attached to every bucket |
| `dataflow_worker_sa_email` | string | yes | — | Dataflow worker SA granted `roles/storage.objectAdmin` on the dataflow-temp bucket |
| `ml_trainer_sa_email` | string | yes | — | ML trainer SA granted `roles/storage.objectAdmin` on the artifacts bucket (`nlp/` cache and MLflow) |
| `raw_archive_autodelete_days` | number | no | `0` | If > 0, raw archive objects are deleted after this many days. `0` disables hard-delete and lets the archive grow indefinitely. |
| `force_destroy_raw_archive` | bool | no | `false` | One-off escape hatch for `terraform destroy` when the raw archive bucket still has objects. See "Tearing down" below. |
| `force_destroy_artifacts` | bool | no | `false` | Same escape hatch for the artifacts bucket. |
| `force_destroy_dataflow_temp` | bool | no | `false` | Same escape hatch for the dataflow-temp bucket. Do not use while a Flex Template under `templates/` is in use. |

## Outputs

| Name | Description |
|---|---|
| `raw_archive_bucket_name` | Name of the raw archive bucket |
| `raw_archive_bucket_url` | `gs://` URL of the raw archive bucket |
| `tf_artifacts_bucket_name` | Name of the artifacts bucket |
| `tf_artifacts_bucket_url` | `gs://` URL of the artifacts bucket |
| `dataflow_temp_bucket_name` | Name of the Dataflow staging/temp bucket |
| `dataflow_temp_bucket_url` | `gs://` URL of the Dataflow staging/temp bucket |

## Tearing down

`force_destroy = false` is the default on both buckets — GCS will refuse to delete a bucket that still has objects. That is a deliberate barrier; the raw archive especially is the only re-runnable source of truth for collector data, accidental deletion is unrecoverable.

When you genuinely want to recreate a bucket, set the override on the CLI for both the apply that lifts the barrier and the destroy itself, same pattern as the bootstrap state bucket:

```bash
terraform apply  -var="force_destroy_raw_archive=true" -auto-approve
terraform destroy -var="force_destroy_raw_archive=true" -auto-approve
```

Or `force_destroy_artifacts=true` / `force_destroy_dataflow_temp=true` for the other two buckets. The defaults flip back to `false` on the next normal apply — no code edit, no risk of leaving a bucket unprotected. (For dataflow-temp, don't force-destroy while a Flex Template spec under `templates/` is still in use by a launchable job.)

## Notes

- **Bucket IAM is co-located with the consumer, not centralised.** The dataflow-temp `objectAdmin` binding for the worker SA lives in this module because the bucket is owned here and its consumer is a Dataflow job (no Cloud Run resource to hang it off). The raw archive's read/write bindings, by contrast, live in the `cloud_run_jobs/` module next to the collector and publisher jobs that consume it (those jobs receive the bucket name as input). Either way the binding sits next to a resource that owns the relationship — never in a central IAM module.
- The raw archive intentionally has **no versioning**. Collectors must write to new object paths under `{source}/{event_id_or_general}/{YYYY}/{MM}/{DD}/{HH}/{batch}.jsonl.gz` rather than overwriting. Versioning would mask bugs in that contract.
- `raw_archive_autodelete_days` is meant for dev tear-downs only. Leave it at `0` for `prod` where the raw archive is the only re-runnable source of truth.
