# Phase 1 — Dashboard (Looker Studio)

The project's dashboard is a Looker Studio report over the BigQuery
reporting views. It completes Track C4 in [`phase-1-plan.md`](phase-1-plan.md).
It replaced the interim Streamlit dashboard
([`phase-1-dashboard.md`](phase-1-dashboard.md)) and keeps the same three
pages, the same views and the same numbers.

Date: 2026-11-02.

> **State on 2026-11-02: done.** The report **Pop vibe check** reads six
> views in `co_reporting_dev` and shows all **263,893 records**: 251,639
> Steam reviews and 12,254 YouTube comments, across 10 event windows.
> Kacper owns it; Marcin and Oskar are editors. Link sharing is
> *Restricted*. There is no prod report.

**Link:**
<https://lookerstudio.google.com/reporting/68b95688-47a2-4393-9f55-ece433d8004a>.
It opens only for the people listed under [Adding a person](#adding-a-person).

---

## Pages

| Page | Controls | Shows | Views |
|---|---|---|---|
| **Przegląd** | grain (default `week`), source, date range | Scorecards: records, Net sentiment, Positive %, Negative %. Net sentiment per source over time, plotting only periods with at least 20 records. Records per period, stacked by source. *Okna wydarzeń*: each event's first and last record and its volume. | `v_sentiment_by_period`, `v_sentiment_by_event` |
| **Wydarzenia** | source | Net sentiment per event and source. The positive / neutral / negative split per event, one chart for Steam and one for YouTube. *Rozbieżność źródeł*: per event, the most and least positive source and the gap between them, widest first. The event effect, against the source's own baseline: the change in net sentiment and the volume multiplier (records per day), as two charts and a table with the largest drop first. | `v_sentiment_by_event_source`, `v_source_divergence`, `v_event_lift` |
| **Źródła i języki** | source | Records per language (top 15), stacked by source. Positive share per language and source. A source × language table: first and last record, records, Positive %, number of event tags. | `v_source_coverage` |

Each column is described where it is defined, in
`definitions/reporting/*.sqlx`, and in the BigQuery console.

## How it is put together

```
browser ──► Looker Studio report "Pop vibe check"
              │ six embedded BigQuery data sources,
              │ viewer's credentials, 12-hour cache
              ▼
            BigQuery co_reporting_dev  (views from Dataform)
              │ authorized on the analytics dataset
              ▼
            co_analytics_dev.events
```

- **One data source per view.** There are six BigQuery data sources, one
  for each view the pages use in `pop-vibe-check.co_reporting_dev`. They
  are embedded in the report rather than reusable, so they exist only
  inside it: *Resource → Manage added data sources*
  (*Zasób → Zarządzaj dodanymi źródłami danych*) in edit mode.
- **Viewer's credentials.** Each data source runs its queries as the
  person viewing the report, not as the owner. The report shows data only
  to people BigQuery lets read the views, i.e. those in
  `report_viewer_emails`. Sharing the report alone is not enough. Readers
  get nothing on the analytics dataset, and the views exclude
  `author_hash` and `text`, so neither can reach a chart.
- **The views hold the metrics; the report adds counts and divides.**
  `Net sentiment`, `Positive %` and `Negative %` are calculated fields
  over `SUM(positive)`, `SUM(negative)` and `SUM(records)`; for example,
  net sentiment is `(SUM(positive) - SUM(negative)) / SUM(records)`. That
  makes them correct for any combination of sources and periods. The
  `v_sentiment_by_period` data source disables the view's per-row ratios
  (`*_share`, `net_sentiment`, `avg_confidence`) and `distinct_authors`,
  because summing them across rows is meaningless. The event-level views
  are already one row per event and source, so their charts show the
  view's numbers as they are.
- **Freshness.** Looker caches query results for 12 hours (the data
  sources' *data freshness*). To see a Dataform deploy or a new replay at
  once, use *⋮ → Refresh data* (*Odśwież dane*) in view mode.
- **The report is not in git.** The layout, calculated fields and data
  sources live in Looker Studio under Kacper's Google account. Git holds
  only the views. *File → Version history* is the report's history.
  Before that account leaves the project, transfer ownership to another
  editor in the *Share* dialog.

## Adding a person

Access needs **two lists**. A person on only one of them sees no data.

**1. The BigQuery readers (Terraform).** Add the email to
`report_viewer_emails` in the canonical dev tfvars. That grants
`dataViewer` on `co_reporting_dev` and `jobUser` on the project. The same
list also lets the person through IAP to the MLflow UI
([`terraform/modules/mlflow`](../terraform/modules/mlflow/README.md)).

```bash
cd terraform/envs/dev
gcloud secrets versions access latest --secret=co-tfvars-dev \
  --project=pop-vibe-check > terraform.tfvars
# edit: report_viewer_emails = [ ..., "new.person@gmail.com" ]
gcloud secrets versions add co-tfvars-dev --project=pop-vibe-check \
  --data-file=terraform.tfvars
gcloud builds triggers run co-terraform-apply-dev \
  --region=europe-central2 --project=pop-vibe-check --branch=main
```

An approver must then release the queued apply in the Cloud Build console.
`terraform.tfvars` is git-ignored, so do not commit it.

**2. The report (Looker Studio).** Open the report, click *Share*
(*Udostępnij*), enter the email, and choose *Viewer* or *Editor*. Leave
link sharing on *Restricted*.

There is no OAuth test-user list here, unlike for the retired Streamlit
dashboard and for MLflow, because Looker Studio signs people in itself.

**Removing a person:** take the email off both lists. Removing it from
`report_viewer_emails` (tfvars edit plus apply) is what actually cuts off
the data.

### When someone sees no data

| Symptom | Cause | Fix |
|---|---|---|
| The link asks for access | The report is not shared with that account | Step 2 above |
| The report opens, but the charts show a data access error | Not in `report_viewer_emails`, or the apply has not run or propagated yet | Step 1 above; IAM changes can take a few minutes |
| Numbers older than the last deploy or replay | The 12-hour cache | *⋮ → Refresh data* |
| A chart shows a field error after a view changed | A column it uses was renamed or dropped in Dataform | Edit the data source, click *Refresh fields* (*Odśwież pola*), then fix the charts that used the column |

## Changing a metric: Dataform web IDE, workspace, deploy

Every number in the report is a column of a view in `co_reporting_dev`,
or a sum of such columns divided once. The views are a Dataform project in
the repository root ([ADR 0003](adr/0003-reporting-sql-in-dataform.md)):
`definitions/reporting/*.sqlx`, with shared SQL fragments in
`includes/sentiment.js`. A metric changes in SQL, never in the report.

1. **Open a workspace.** Console → BigQuery → Dataform →
   `co-reporting-dev` → *Create development workspace*. Name it with
   letters, digits and underscores only (`kozi_lift`, not `kozi-lift`):
   the name becomes part of a dataset ID. A workspace is a git branch with
   an editor; it starts from `main`.
2. **Edit and run.** *Compile* shows errors as you type. *Start execution*
   creates the views in **`co_reporting_dev_<workspace>`** and the
   assertion results in `co_dataform_assertions_dev_<workspace>`, never in
   the datasets the report reads. A failing assertion shows the rows that
   broke it.
3. **Commit and push** from the workspace to a new branch, not `main` (a
   push to `main` deploys at once, without review), then open a pull
   request on GitHub. `co-dataform-compile-pr-dev` compiles it.
4. **Merge.** `co-dataform-deploy-dev` compiles `main` at the merge
   commit and runs every action: the views are replaced in place, then all
   assertions run, and a failing one fails the build. No approval is
   needed, and nothing in Terraform changes. The report shows the new
   numbers when its 12-hour cache expires, or straight away after
   *Refresh data*. If a column was renamed or dropped, refresh the fields
   of its data source as well.
5. **Clean up** the workspace's datasets when it is done; nothing deletes
   them automatically:

   ```bash
   bq rm -r -f -d pop-vibe-check:co_reporting_dev_<workspace>
   bq rm -r -f -d pop-vibe-check:co_dataform_assertions_dev_<workspace>
   ```

The same edit works without the web IDE: change the `.sqlx` on a branch
and compile locally with `npx --yes @dataform/cli@3.0.71 compile` (no
credentials needed). Details:
[`terraform/modules/dataform/README.md`](../terraform/modules/dataform/README.md).

**A new view** also goes into the `dependencies` of
`definitions/assertions/no_personal_columns.sqlx` and into
`report_view_ids` in `terraform/modules/bigquery/outputs.tf`. To chart
it, add it to the report in edit mode: *Resource → Manage added data
sources → Add a data source → BigQuery* → `pop-vibe-check` →
`co_reporting_dev` → the view. Then set the new data source's credentials
to *Viewer's*, as on the other six.

## Open items

- **prod** has no report. One would be a copy of this report (*File →
  Make a copy*) with its data sources pointed at the prod reporting
  dataset, once prod has Dataform
  ([ADR 0003](adr/0003-reporting-sql-in-dataform.md), Consequences).
