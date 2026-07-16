# modules/bigquery

Provisions the BigQuery dataset plus the `raw_landing` / `raw_staging` tables used by the replay publisher. The `events` table and authorized views for Looker Studio land with the Dataflow PR inside this same module.

## What this creates

- **`{name_prefix}_analytics_{env}`** — regional BigQuery dataset in the supplied region. Default region per project convention is `europe-central2`. Multi-region BigQuery is explicitly out of scope for the thesis.
- **`raw_landing`** — permanent truncate-and-load target for GCS raw archive loads (unpartitioned; rewritten wholesale by every load).
- **`raw_staging`** — deduplicated raw records (one row per `id`, freshest `collected_at` wins), DAY-partitioned on `created_utc` and clustered by `(source, event_tag)`. The replay publisher reads it with `ORDER BY created_utc`.
- Publisher IAM: dataset-level `roles/bigquery.dataEditor` plus project-level `roles/bigquery.jobUser` for the publisher SA (jobUser is only grantable at project scope; kept here because it exists solely for this dataset's load/replay jobs).

Note: BigQuery dataset names require underscores rather than hyphens (GCP rule). Any hyphen in `name_prefix` is converted to underscore in the dataset ID only — other resources keep the hyphen.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | GCP project ID |
| `name_prefix` | string | yes | — | Short release prefix (2-8 chars, lowercase alphanumeric/hyphen) |
| `env` | string | yes | — | Environment name; suffixed into the dataset ID |
| `region` | string | yes | — | Region for the dataset |
| `labels` | map(string) | yes | — | Labels applied to the dataset |
| `publisher_sa_email` | string | yes | — | Publisher SA granted dataEditor on the dataset and jobUser on the project |
| `delete_contents_on_destroy` | bool | no | `false` | One-off escape hatch for `terraform destroy` when the dataset still has tables. See "Tearing down" below. |

## Outputs

| Name | Description |
|---|---|
| `dataset_id` | Short dataset ID, e.g. `co_analytics_dev` |
| `dataset_full_id` | Fully-qualified resource ID |
| `dataset_location` | Region the dataset lives in |
| `raw_landing_table_id` | Short table id of the landing table (`raw_landing`) |
| `raw_staging_table_id` | Short table id of the staging table (`raw_staging`) |

## Tearing down

`delete_contents_on_destroy = false` is the default — BigQuery will refuse to delete a dataset that still has tables in it. That's a deliberate barrier against accidentally nuking analytical data.

When you genuinely want to recreate the dataset, set the override on the CLI for both the apply that lifts the barrier and the destroy itself:

```bash
terraform apply  -var="delete_contents_on_destroy=true" -auto-approve
terraform destroy -var="delete_contents_on_destroy=true" -auto-approve
```

The default flips back to `false` automatically on the next normal apply — no code edit, no risk of leaving the dataset unprotected.

## Notes

- **Remaining Phase 1 tables.** `events` (partitioned by `DATE(created_utc)`, clustered by `(source, event_tag)`) plus Looker authorized views are added here with the Dataflow PR.
- **Dataflow IAM later.** The Dataflow worker SA gets `bigquery.dataEditor` on this dataset in the Dataflow PR inside this module — bindings stay next to the resource per project convention.
- **Per env, per release.** `co_analytics_dev` and `co_analytics_prod` are separate datasets with separate IAM; `w4_analytics_dev` lives alongside `co_analytics_dev` in the same project without conflict.
