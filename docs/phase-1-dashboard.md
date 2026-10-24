# Phase 1 — Preliminary dashboards (Streamlit on Cloud Run)

A code-first dashboard over the BigQuery reporting views, deployed for the
team before the Looker Studio dashboard (Track C4 in
[`phase-1-plan.md`](phase-1-plan.md)) exists. It reads the same authorized
views a Looker data source would, so the numbers carry over unchanged.

Code and local runs: [`dashboard/README.md`](../dashboard/README.md).
Infrastructure:
[`terraform/modules/dashboard/README.md`](../terraform/modules/dashboard/README.md).

Date: 2026-10-20 (PR #64 for the app, PR #65 for the deployment).

> **State on 2026-10-20.** Live in dev as the Cloud Run service
> `co-dashboard-dev`, behind Identity-Aware Proxy. The views hold
> **263,893 records**: 251,639 Steam reviews (2025-04-24 → 2026-10-14,
> 47 languages) and 12,254 YouTube comments (2024-06-09 → 2026-04-30,
> 38 languages), across 11 lifecycle event tags. Four people have
> access. There is no prod deployment.

---

## Opening it

```bash
gcloud run services describe co-dashboard-dev --region=europe-central2 \
  --project=pop-vibe-check --format='value(status.url)'
# or, from terraform/envs/dev:  terraform output dashboard_url
```

Open the URL and sign in with a Google account that has access (see
[Adding a person](#adding-a-person)). The consent screen asks to share the
account's email address with "Pop Vibe Check Dashboard" once per account.

## Pages

| Page | Views | Shows |
|---|---|---|
| **Przegląd** (Sentyment w czasie) | `v_sentiment_by_period`, `v_sentiment_by_event` | Headline numbers, net sentiment and volume per source by day / week / month, event windows shaded |
| **Wydarzenia** | `v_sentiment_by_event_source`, `v_source_divergence`, `v_event_lift`, `v_sentiment_by_event` | Net sentiment and the pos / neu / neg split per event × source, the widest source divergence, the event effect (net-sentiment change and volume multiplier against the rest of the same source) |
| **Źródła i języki** | `v_source_coverage` | Volume and positive share per source and language |

Query results are cached for 5 minutes per instance. The sidebar's
*Odśwież dane* clears the cache.

## How it is put together

```
browser ──► IAP (Google sign-in, access list) ──► Cloud Run co-dashboard-dev
                                                     │ runs as co-dashboard-sa-dev
                                                     ▼
                                     BigQuery co_reporting_dev (authorized views)
```

- **Who may open the page** is decided by IAP. **What the page may read**
  is decided by the service's own SA, `co-dashboard-sa-dev`: `dataViewer`
  on the reporting dataset plus project `jobUser`, and nothing on the
  analytics dataset. Viewers need no BigQuery access of their own, and the
  views exclude `author_hash` and `text`, so neither can reach a chart.
- **Scaling:** 0–2 instances, 1 CPU / 1 GiB, CPU billed only while a
  browser session is open. Session affinity is on and the request timeout
  is 3600 s, because a Streamlit session is a single long-lived websocket.
  The cap of 2 instances is a cost guard.
- **Deploys:** a pull request touching `dashboard/` builds the image
  (`co-dashboard-pr-dev`). A merge to `main` builds it, pushes it, and
  deploys it by digest (`co-dashboard-deploy-dev`,
  [`dashboard/cloudbuild.yaml`](../dashboard/cloudbuild.yaml)). Terraform
  created the service and ignores its image from then on.

### What lives outside Terraform

The repository does not capture three settings. They were configured by
hand on 2026-10-20 and must be redone for a new project or environment:

| Setting | Where | Why not in Terraform |
|---|---|---|
| IAP enabled on the service | `gcloud run services update co-dashboard-dev --region=europe-central2 --iap` | The pinned Google provider (5.x) has no `iap_enabled` field. |
| Custom OAuth client for IAP | Console → Security → Identity-Aware Proxy → *All web services* ⋮ → Settings → *Custom OAuth* → *Auto Generate Credentials* | The project belongs to an organization and our accounts are `@gmail.com`, i.e. outside it. IAP's default Google-managed client admits only organization accounts and answered "You don't have access" even with the IAM grant in place. OAuth clients cannot be created programmatically. |
| OAuth consent screen "Pop Vibe Check Dashboard" | Console → Google Auth Platform (Branding, Audience) | Same as above. Audience **External**, publishing status **Testing**. |

A Terraform change to the Cloud Run service may switch IAP off again. That
fails closed: everyone gets a 403. Re-run the `--iap` command above to fix
it.

## Adding a person

Access needs **two lists**. A person on only one of them cannot get in.

**1. The IAP access list (Terraform).** Add the email to
`report_viewer_emails` in the canonical dev tfvars. The same list grants
read access to the reporting views for the future Looker Studio dashboard.

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
The apply grants `roles/iap.httpsResourceAccessor` on the project.
`terraform.tfvars` is git-ignored, so do not commit it.

**2. The OAuth test users (console).** While the consent screen is in
*Testing*, Google lets only listed test users sign in. Go to Console →
Google Auth Platform → **Audience** → *Test users* → **Add users**, enter
the email, and click **Save**. The cap is 100 test users over the app's
lifetime.

The person can then open the URL. IAM changes can take a few minutes to
propagate.

**Removing a person:** delete the email from both lists in the same way.
The IAP grant, removed by the tfvars edit plus apply, is the one that
actually revokes access.

### When someone cannot get in

| Symptom | Cause | Fix |
|---|---|---|
| Google shows "Access blocked … has not completed the Google verification process" (`Error 403: access_denied`) | Not on the test users list | Step 2 above |
| IAP page "You don't have access", showing the right email | Not in `report_viewer_emails`, or the apply has not run or propagated yet | Step 1 above; wait a few minutes |
| "You don't have access" with a different email | Signed in to Chrome with several Google accounts | Use *try a different account* on that page |
| Everyone gets a plain 403 | IAP was switched off on the service (e.g. by a Terraform update) | `gcloud run services update co-dashboard-dev --region=europe-central2 --iap` |

## Changing a metric: Dataform web IDE, workspace, deploy

Every number on the pages is a column of a view in `co_reporting_dev`, and
the views are a Dataform project in the repository root
([ADR 0003](adr/0003-reporting-sql-in-dataform.md)):
`definitions/reporting/*.sqlx`, shared SQL fragments in
`includes/sentiment.js`. A metric changes in SQL, never in the dashboard.

1. **Open a workspace.** Console → BigQuery → Dataform →
   `co-reporting-dev` → *Create development workspace*. Name it with
   letters, digits and underscores only (`kozi_lift`, not `kozi-lift`):
   the name becomes part of a dataset ID. A workspace is a git branch with
   an editor; it starts from `main`.
2. **Edit and run.** *Compile* shows errors as you type. *Start execution*
   creates the views in **`co_reporting_dev_<workspace>`** and the
   assertion results in `co_dataform_assertions_dev_<workspace>`, never in
   the datasets the dashboard reads. A failing assertion shows the rows
   that broke it.
3. **Commit and push** from the workspace to a new branch, not `main` (a
   push to `main` deploys at once, without review), then open a pull
   request on GitHub. `co-dataform-compile-pr-dev` compiles it.
4. **Merge.** `co-dataform-deploy-dev` compiles `main` at the merge
   commit and runs every action: the views are replaced in place, then all
   assertions run, and a failing one fails the build. No approval is
   needed, and nothing in Terraform changes. The dashboard shows the new
   numbers once its 5-minute cache expires (or after *Odśwież dane*).
5. **Clean up** the workspace's datasets when it is done; nothing deletes
   them automatically:

   ```bash
   bq rm -r -f -d pop-vibe-check:co_reporting_dev_<workspace>
   bq rm -r -f -d pop-vibe-check:co_dataform_assertions_dev_<workspace>
   ```

The same edit works without the web IDE: change the `.sqlx` on a branch
and compile locally with `npx --yes @dataform/cli@3.0.71 compile` (no
credentials needed). A new view also goes into the `dependencies` of
`definitions/assertions/no_personal_columns.sqlx`, and into
`report_view_ids` in `terraform/modules/bigquery/outputs.tf` if Looker
Studio should find it. Details:
[`terraform/modules/dataform/README.md`](../terraform/modules/dataform/README.md).

## Open items

- **Looker Studio (C4)** is still outstanding. This dashboard is the
  interim presentation layer and a spec for the Looker rebuild: same views,
  same metrics. The pages only filter rows; the headline numbers sum the
  selected sources' counts, which is what a Looker scorecard does with SUM
  fields.
- **Publishing the consent screen** (*Audience → Publish app*) would remove
  the 100-test-user cap and the second list. For the `openid` and `email`
  scopes, publishing should not require Google verification. Access would
  still be limited by the IAP list.
- **prod** has no dashboard module. Adding one means the same module in
  `terraform/envs/prod` plus the three manual settings above.
