# ADR 0003 — The reporting SQL is a Dataform project, and the metrics are views

- **Status:** Accepted
- **Date:** 2026-10-24
- **Affects:** `workflow_settings.yaml`, `definitions/`, `includes/`,
  `cloudbuild.dataform.yaml`, `terraform/modules/{bigquery,dataform,cloud_build}`,
  `dashboard/` (PRs #68, #69, #70 and the dashboard switch)
- **Relates to:** Looker Studio (Track C4 in
  [`phase-1-plan.md`](../phase-1-plan.md)), which must show the same
  numbers as the interim dashboard, and the privacy boundary on
  `author_hash` and `text`

## Context

The reporting layer was split across two places, and neither was a good
home for SQL.

**The view SQL lived in HCL.** Four views were heredocs in
`terraform/modules/bigquery/main.tf`. Changing a `GROUP BY` meant a
Terraform plan, an approval and an apply, the same path as changing a
service account. Nothing tested the data: a view could double-count and
still deploy.

**Half the metrics lived in Python.** `dashboard/metrics.py` rolled
`v_sentiment_daily` up to weeks and months, filled in empty periods,
compared each event with the rest of its source and ranked the sources
against each other. Looker Studio cannot run that code. Rebuilding the
dashboard there would have meant re-deriving four calculations as blends
and calculated fields, and keeping them in step with the pandas versions
by hand.

**Each view was authorized on analytics separately.** A new view could
not read `events` until a Terraform apply had added its entry, so any SQL
change that added a view needed two deploys in the right order.

## Decision

**All reporting SQL is a Dataform project (core 3.0.71) in the repository
root:**
- `workflow_settings.yaml`: project, location, datasets, the core version
  pin;
- `definitions/reporting/*.sqlx`: one file per view, with its
  description, column descriptions, labels and built-in assertions;
- `definitions/assertions/`: checks across views;
- `includes/`: shared SQL fragments.

The project sits in the root because a managed Dataform repository reads
only the root, never a subdirectory.

**The layer stays views, not tables.** When phase 3 streams into
`events`, the views show it immediately. There is no schedule to run and
nothing goes stale.

**Deploys follow merges.**
- On every pull request, `co-dataform-compile-pr-dev` compiles the
  project.
- On every merge to `main`, `co-dataform-deploy-dev` asks the Dataform API
  to compile the merge commit, runs every action and waits for the result.
  A failing assertion fails the build.
- There is no release or workflow config: the views change when the code
  does.

**The metrics are views.** Four views replace `metrics.py`'s calculations:

| View | Replaces |
|---|---|
| `v_sentiment_by_period` | `complete_periods(rollup(…, grain))` |
| `v_sentiment_by_event_source` | `rollup(…, ["event_tag", "source"])` |
| `v_event_lift` | `event_lift` |
| `v_source_divergence` | `source_divergence` |

The dashboard now only picks rows. The single exception is the headline
numbers, which sum the selected sources' counts, exactly as a Looker
scorecard does.

**The reporting dataset is authorized on analytics as a whole**
(`target_types = ["VIEWS"]`), so a new view needs no Terraform apply. Two
things compensate for the wider grant:
- the `no_personal_columns` assertion fails the deploy if any object in
  `co_reporting_dev` has a column named `author_hash` or `text`;
- only the Dataform SA and the Terraform runner can write to the dataset.

**Terraform keeps what is infrastructure:** the datasets, who may read
and write them, the authorization and the Dataform repository itself. It
handed the four existing views over with `removed { destroy = false }`
blocks, so they were forgotten rather than dropped.

**The web IDE cannot touch dev.** A workspace compiles with
`schema_suffix = <workspace>`, so its runs land in
`co_reporting_dev_<workspace>`.

## Consequences

- **A SQL change needs no Terraform approval.** The review is the pull
  request. A merged change deploys without anyone approving it, which is
  the point; Terraform changes still go through approval.
- **Every deploy tests the data:**
  - `uniqueKey` on each view's grain;
  - `rowConditions` on counts and shares;
  - `records_reconcile`: every grain of every view adds up to `events`;
  - `no_personal_columns`.
  
  Deliberately broken views fail these assertions.
- **The new views reproduce the pandas results.** I compared them with
  `metrics.py` on the live data using `assert_frame_equal(rtol=1e-9)`, and
  then compared the dashboard's pages, old against new, for every source
  selection.
  - `distinct_authors` is now exact at every grain. The pandas rollup had
    to drop it because it is not additive.
- **Looker Studio gets the metrics for free.** A data source over
  `v_event_lift` shows the same numbers as the dashboard.
- **Taking over a view needed a one-time order.** Dataform could not
  replace a view that still had its own authorized entry on analytics:
  BigQuery then requires `datasets.update` on the source dataset. The
  first deploy failed until the apply that removed the per-view entries
  had run. New views do not have this problem.
- **prod is not covered.** `envs/prod` uses the same module. Its next
  apply will forget prod's views too, and they will stay as Terraform last
  created them until Dataform is set up for prod.
- **The source divergence is exact only when both of its ends are
  selected.** The view ranks all sources. With today's two sources that
  is exact. With three, deselecting the highest or lowest source hides the
  event rather than recomputing the gap.
- **GitHub access is a stored token.** Dataform fetches the repository
  with a token from Secret Manager. Today that is a collaborator's classic
  PAT. An SSH deploy key, which needs the repository owner, should replace
  it.

## Alternatives considered

- **Keeping the SQL in Terraform and adding tests elsewhere.** Rejected.
  It keeps SQL edits behind applies, and it leaves the pandas metrics
  where Looker cannot reach them.
- **dbt.** Rejected. It needs a runtime we would host and a profile with
  credentials. Dataform runs in BigQuery, has a web IDE in the console
  and is configured with the same Terraform as everything else.
- **Materialized tables or scheduled queries.** Rejected for now. The
  data is small enough for views to answer in seconds, and a schedule
  would make the phase 3 stream look stale between runs.
- **Per-view authorization, managed from Dataform.** Rejected. Every new
  view would need a Terraform apply before its first deploy: the same
  ordering trap the takeover hit once, but on every new view.
