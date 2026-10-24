# modules/dataform

Dataform repository for the reporting layer. The SQL of every reporting view lives in this git repository's root — `workflow_settings.yaml`, `definitions/`, `includes/` — because managed Dataform reads a project from the repository root only, never a subdirectory.

Dataform here is a window onto GitHub: the web IDE edits branches through it, and Cloud Build compiles `main` at the merged commit and runs it (`cloudbuild.dataform.yaml`, triggers in `modules/cloud_build`). There is no release config and no workflow config — the views change when the code does, not on a schedule.

## The project

```
workflow_settings.yaml        project, location, datasets, core version, vars.analytics_dataset
includes/                     shared SQL fragments (sentiment.js) and settings (reporting.js)
definitions/sources/          declarations of what Terraform owns (events)
definitions/reporting/        one .sqlx per view in co_reporting_dev, with its built-in assertions
definitions/assertions/       assertions across views (no_personal_columns, records_reconcile)
```

Compile locally — no credentials, nothing touches BigQuery — with the version pinned in `workflow_settings.yaml`:

```bash
npx --yes @dataform/cli@3.0.71 compile
```

## What this creates

- **`{name_prefix}-reporting-{env}`** — Dataform repository (`google-beta`) in `var.region`, linked to `https://github.com/{github_owner}/{github_repo}.git` on `default_branch`. Invocations run as `dataform_sa_email`. Workspace compilations get `schema_suffix = "${workspaceName}"`.
- **`{name_prefix}-dataform-github-token-{env}`** — empty secret container for the GitHub token the repository fetches and pushes with. Only the Dataform service agent can read it.
- The Dataform service agent (`service-<number>@gcp-sa-dataform.iam.gserviceaccount.com`), forced into existence with `google_project_service_identity` — otherwise it only appears with the first repository, too late for the grants it needs. It gets `roles/secretmanager.secretAccessor` on the token secret and `roles/iam.serviceAccountTokenCreator` on the Dataform SA.
- For the deployer (Cloud Build SA) and each of `editor_emails`: `roles/dataform.editor` on the repository and `roles/iam.serviceAccountUser` on the Dataform SA. Strict act-as: whoever starts an invocation that runs as a custom SA must be able to act as it.

The Dataform SA's BigQuery access lives in `modules/bigquery`, next to the datasets: `dataViewer` on analytics, `dataEditor` on reporting and on the assertions dataset, `bigquery.user` on the project.

## One-time setup

1. **Bootstrap.** The runner needs `roles/dataform.admin` and `dataform.googleapis.com` must stay enabled; both are in `terraform/bootstrap` — re-apply it by hand before the first apply that includes this module.
2. **Apply** the environment (creates the repository and the empty secret).
3. **GitHub token.** A [fine-grained PAT](https://github.com/settings/personal-access-tokens/new) with access to this repository only and *Contents: Read and write* (write lets workspaces push branches; Cloud Build deploys need read only). Then:

   ```bash
   printf '%s' "$PAT" | gcloud secrets versions add co-dataform-github-token-dev --data-file=-
   ```

   The repository reads `versions/latest`, so a rotated token is picked up without an apply.
4. **Check** in the console (*BigQuery → Dataform → co-reporting-dev*): create a workspace; it should pull `main`.

## The web IDE: workspaces

A workspace is a branch with an editor. Compiling or executing from one uses the workspace override, so every dataset name gets `_<workspace>` appended: a run writes `co_reporting_dev_<workspace>` and `co_dataform_assertions_dev_<workspace>`, never the views the dashboard reads. The Dataform SA creates those datasets (project-level `bigquery.user`) and owns them.

- **Name workspaces with letters, digits and underscores only** — the name becomes part of a dataset ID, and a hyphen makes the run fail.
- Commit and push from the workspace to a branch, open a PR on GitHub; the merge is what deploys.
- Workspace datasets are not cleaned up automatically. Drop them when the workspace is done:

  ```bash
  bq rm -r -f -d pop-vibe-check:co_reporting_dev_<workspace>
  bq rm -r -f -d pop-vibe-check:co_dataform_assertions_dev_<workspace>
  ```

Views in a workspace dataset are not authorized on analytics (only `co_reporting_dev` is). The Dataform SA can still query them — it reads analytics directly — so assertions run, but other users without analytics access cannot.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | GCP project ID |
| `name_prefix` | string | yes | — | Short release prefix |
| `env` | string | yes | — | Environment name; suffixed into names |
| `region` | string | yes | — | Repository region; same as the datasets |
| `labels` | map(string) | yes | — | Labels on the repository and secret |
| `github_owner` | string | yes | — | GitHub owner of the repository |
| `github_repo` | string | yes | — | GitHub repository name |
| `default_branch` | string | no | `main` | Branch compiled and checked out by default |
| `dataform_sa_email` | string | yes | — | SA every invocation runs as |
| `deployer_sa_email` | string | no | `null` | Cloud Build SA allowed to compile and invoke; `null` skips |
| `editor_emails` | list(string) | no | `[]` | Users allowed to work in the web IDE |

## Outputs

| Name | Description |
|---|---|
| `repository_name` | Short repository name, e.g. `co-reporting-dev` |
| `repository_id` | Fully-qualified repository ID |
| `github_token_secret_id` | Secret to add the GitHub token to |
| `service_agent_email` | The project's Dataform service agent |
