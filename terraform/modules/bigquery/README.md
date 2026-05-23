# modules/bigquery

Provisions the BigQuery dataset that holds analytical tables. Dataset only — `raw_staging` and `events` tables, plus authorized views for Looker Studio, land in Phase 1 inside this same module.

## What this creates

- **`{name_prefix}_analytics_{env}`** — regional BigQuery dataset in the supplied region. Default region per project convention is `europe-central2`. Multi-region BigQuery is explicitly out of scope for the thesis.

Note: BigQuery dataset names require underscores rather than hyphens (GCP rule). Any hyphen in `name_prefix` is converted to underscore in the dataset ID only — other resources keep the hyphen.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | GCP project ID |
| `name_prefix` | string | yes | — | Short release prefix (2-8 chars, lowercase alphanumeric/hyphen) |
| `env` | string | yes | — | Environment name; suffixed into the dataset ID |
| `region` | string | yes | — | Region for the dataset |
| `labels` | map(string) | yes | — | Labels applied to the dataset |
| `delete_contents_on_destroy` | bool | no | `false` | One-off escape hatch for `terraform destroy` when the dataset still has tables. See "Tearing down" below. |

## Outputs

| Name | Description |
|---|---|
| `dataset_id` | Short dataset ID, e.g. `co_analytics_dev` |
| `dataset_full_id` | Fully-qualified resource ID |
| `dataset_location` | Region the dataset lives in |

## Tearing down

`delete_contents_on_destroy = false` is the default — BigQuery will refuse to delete a dataset that still has tables in it. That's a deliberate barrier against accidentally nuking analytical data.

When you genuinely want to recreate the dataset, set the override on the CLI for both the apply that lifts the barrier and the destroy itself:

```bash
terraform apply  -var="delete_contents_on_destroy=true" -auto-approve
terraform destroy -var="delete_contents_on_destroy=true" -auto-approve
```

The default flips back to `false` automatically on the next normal apply — no code edit, no risk of leaving the dataset unprotected.

## Notes

- **Tables in Phase 1.** `raw_staging` (mirrors raw JSONL layout, partitioned by `DATE(created_utc)`) and `events` (partitioned by `DATE(created_utc)`, clustered by `(source, event_tag)`) are added here when Phase 1 lands.
- **No dataset-level IAM yet.** The runner SA already has `roles/bigquery.admin` at project level. Dataflow worker SA gets `bigquery.dataEditor` on this dataset in Phase 1 inside this module — bindings stay next to the resource per project convention.
- **Per env, per release.** `co_analytics_dev` and `co_analytics_prod` are separate datasets with separate IAM; `w4_analytics_dev` lives alongside `co_analytics_dev` in the same project without conflict.
