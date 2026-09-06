# modules/bigquery

Provisions the BigQuery dataset and its four tables: `raw_landing` / `raw_staging` for the replay publisher, and `events_landing` / `events` for the Dataflow streaming pipeline. Looker Studio authorized views over `events` land with the analytics PR inside this same module.

## What this creates

- **`{name_prefix}_analytics_{env}`** — regional BigQuery dataset in the supplied region. Default region per project convention is `europe-central2`. Multi-region BigQuery is explicitly out of scope for the thesis.
- **`raw_landing`** — permanent truncate-and-load target for GCS raw archive loads (unpartitioned; rewritten wholesale by every load).
- **`raw_staging`** — deduplicated raw records (one row per `id`, freshest `collected_at` wins), DAY-partitioned on `created_utc` and clustered by `(source, event_tag)`. The replay publisher reads it with `ORDER BY created_utc`.
- **`events_landing`** — append-only Dataflow write target. Carries the eleven raw fields plus the enrichment columns (`sentiment_label`, `sentiment_score`, `model_version`, `processed_at`). Tolerates duplicate and multi-pass rows per `id`; the MERGE below promotes them into `events`. DAY-partitioned on `created_utc` so it never becomes a growing unpartitioned scan target.
- **`events`** — the analytical source of truth (CLAUDE.md §9): one row per `id`, DAY-partitioned on `created_utc`, clustered by `(source, event_tag)`. Written **only** by the MERGE, never by the pipeline directly. Single denormalised table — the dashboard layer does no joins.
- Publisher IAM: dataset-level `roles/bigquery.dataEditor` plus project-level `roles/bigquery.jobUser` for the publisher SA (jobUser is only grantable at project scope; kept here because it exists solely for this dataset's load/replay jobs).
- Dataflow worker IAM: the same `dataEditor` (dataset) + `jobUser` (project) pair for the Dataflow worker SA, so the pipeline can write `events_landing`.
- ML trainer IAM: dataset-level `roles/bigquery.dataViewer` plus project-level `roles/bigquery.jobUser` so Vertex AI Workbench can SELECT from `raw_staging` / `events` when building the own-domain fine-tune split. Read-only on purpose — the trainer must not write analytical tables.

### Schema: one source, two tables

`raw_landing` / `raw_staging` share the eleven collector fields. `events_landing` / `events` reuse those exact field definitions and append four enrichment columns — the raw fields are defined once (`local.raw_fields`) and extended, so the two table families cannot drift structurally. One documented difference in **meaning**: the `language` column is advisory in `raw_staging` (the collectors' `langdetect` output, unreliable on short comments) and **authoritative** in `events`, where the Dataflow pipeline writes it. That difference is captured in the column descriptions; the column type is identical.

`processed_at` is the Dataflow-side processing timestamp and the MERGE tiebreaker. `collected_at` cannot serve that role: two pipeline runs over the same staged data produce identical `collected_at` values, so it cannot distinguish a fresher pass. `processed_at` differs per run and breaks that tie.

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
| `dataflow_worker_sa_email` | string | yes | — | Dataflow worker SA granted dataEditor on the dataset and jobUser on the project, so the streaming pipeline can write `events_landing` |
| `ml_trainer_sa_email` | string | yes | — | ML trainer SA granted dataViewer on the dataset and jobUser on the project (Workbench gold / own-domain reads) |
| `delete_contents_on_destroy` | bool | no | `false` | One-off escape hatch for `terraform destroy` when the dataset still has tables. See "Tearing down" below. |

## Outputs

| Name | Description |
|---|---|
| `dataset_id` | Short dataset ID, e.g. `co_analytics_dev` |
| `dataset_full_id` | Fully-qualified resource ID |
| `dataset_location` | Region the dataset lives in |
| `raw_landing_table_id` | Short table id of the landing table (`raw_landing`) |
| `raw_staging_table_id` | Short table id of the staging table (`raw_staging`) |
| `events_landing_table_id` | Short table id of the Dataflow write target (`events_landing`) |
| `events_table_id` | Short table id of the analytical events table (`events`) |

## Promotion MERGE (`events_landing` → `events`)

The Dataflow pipeline writes append-only into `events_landing`; a MERGE promotes rows into `events`, one row per `id`, freshest `processed_at` winning. This mirrors the `raw_landing` → `raw_staging` split the publisher already uses, and it is what makes CLAUDE.md §11's guarantee — *same replay twice → identical `events`* — hold without exactly-once semantics from Pub/Sub or Beam.

Terraform does **not** run this statement — it only creates the tables. Run it as a BigQuery query (dev example, substitute your dataset):

```sql
MERGE `pop-vibe-check.co_analytics_dev.events` AS t
USING (
  SELECT * EXCEPT (rn)
  FROM (
    SELECT
      *,
      ROW_NUMBER() OVER (PARTITION BY id ORDER BY processed_at DESC) AS rn
    FROM `pop-vibe-check.co_analytics_dev.events_landing`
  )
  WHERE rn = 1
) AS s
ON t.id = s.id
WHEN MATCHED AND s.processed_at > t.processed_at THEN UPDATE SET
  source          = s.source,
  parent_id       = s.parent_id,
  created_utc     = s.created_utc,
  collected_at    = s.collected_at,
  author_hash     = s.author_hash,
  text            = s.text,
  language        = s.language,
  score           = s.score,
  context_id      = s.context_id,
  event_tag       = s.event_tag,
  sentiment_label = s.sentiment_label,
  sentiment_score = s.sentiment_score,
  model_version   = s.model_version,
  processed_at    = s.processed_at
WHEN NOT MATCHED THEN
  INSERT ROW
```

**Run it *after* Dataflow has drained the replay — not when the publisher finishes.** The publisher completing means "every message has been published", not "every message has been processed". Pub/Sub delivery to the pipeline and Beam's own windowing lag the publisher by seconds to minutes; running the MERGE the moment the publisher exits silently truncates the tail of the run — the last records are still in flight and never reach `events_landing` before the MERGE reads it. Wait until the pipeline's backlog on `{name_prefix}-events-dataflow-sub-{env}` is drained (unacked count at zero and the watermark past the last event) before promoting.

**Who runs it is a later decision, not settled here.** The two candidates are a `RUN_MERGE` mode on the publisher job (mirroring its existing `RUN_LOAD`) or a separate one-shot job; the Dataflow worker SA already holds the `dataEditor` + `jobUser` grants either would need. That is a pipeline-PR call — this module just documents the statement and provisions the tables it targets.

## Tearing down

`delete_contents_on_destroy = false` is the default — BigQuery will refuse to delete a dataset that still has tables in it. That's a deliberate barrier against accidentally nuking analytical data.

When you genuinely want to recreate the dataset, set the override on the CLI for both the apply that lifts the barrier and the destroy itself:

```bash
terraform apply  -var="delete_contents_on_destroy=true" -auto-approve
terraform destroy -var="delete_contents_on_destroy=true" -auto-approve
```

The default flips back to `false` automatically on the next normal apply — no code edit, no risk of leaving the dataset unprotected.

## Notes

- **Looker views still to come.** Authorized views over `events` for Looker Studio are added here with the analytics PR; the underlying tables now exist.
- **Language authority.** `raw_staging.language` is advisory (collector `langdetect`); `events.language` is authoritative (written by Dataflow). Same column type, different documented meaning — see "Schema: one source, two tables" above. Picking the detector library is the pipeline PR's call; note that Dataflow workers run without public IPs, so any detector model file must be baked into the Flex Template image rather than downloaded at runtime.
- **Per env, per release.** `co_analytics_dev` and `co_analytics_prod` are separate datasets with separate IAM; `w4_analytics_dev` lives alongside `co_analytics_dev` in the same project without conflict.
