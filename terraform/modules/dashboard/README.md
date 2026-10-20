# modules/dashboard

Serves the Streamlit dashboard (`dashboard/`) as a Cloud Run service behind Identity-Aware Proxy.

## What this creates

- **`{name_prefix}-dashboard-{env}`** — Cloud Run v2 service running as the dashboard SA. 1 CPU, 1Gi, scales 0–2 instances, CPU billed only while a websocket is open, session affinity on, 3600s request timeout (a Streamlit session is one long-lived websocket). Created on Google's public `hello` sample image; Cloud Build deploys the real one on every merge to main and the image field is ignored afterwards.
- **`roles/run.invoker`** on the service for the IAP service agent — the only principal that calls the service directly.
- **`roles/iap.httpsResourceAccessor`** on the project for each of `viewer_emails`. Project-level because provider 5.x has no per-service IAP IAM resource; this service is the project's only IAP resource.
- **`roles/bigquery.dataViewer`** on the reporting dataset and **`roles/bigquery.jobUser`** on the project for the dashboard SA. The page reads the authorized views as this SA, so viewers need no BigQuery access of their own.
- **Image deployer grants** (when `deployer_sa_email` is set): `roles/run.developer` on the service and `roles/iam.serviceAccountUser` on the dashboard SA, for the Cloud Build SA.

## IAP is switched on outside Terraform

The pinned provider (5.x) has no `iap_enabled` field on `google_cloud_run_v2_service`. Turn it on once, after the first apply creates the service:

```bash
gcloud run services update co-dashboard-dev --region=europe-central2 --iap
gcloud run services describe co-dashboard-dev --region=europe-central2 | grep -i iap   # Iap Enabled: true
```

Image deploys keep the setting. A Terraform change to the service may switch it off again; that fails closed (the run.app URL then wants `run.invoker`, which no viewer holds, so everyone gets a 403) and the same command restores it.

## One-time prerequisites

1. **The IAP API and its service agent.** `iap.googleapis.com` is in bootstrap's `enabled_services`; on a project where bootstrap has not been re-applied since, enable it by hand. The agent the invoker grant names must exist before the apply:

   ```bash
   gcloud services enable iap.googleapis.com --project=<PROJECT_ID>
   gcloud beta services identity create --service=iap.googleapis.com --project=<PROJECT_ID>
   ```

2. **A custom OAuth client, for viewers outside the project's organization** (every `@gmail.com` account). IAP's default Google-managed client only admits identities from the organization. In the console, *Security → Identity-Aware Proxy*: set up the OAuth consent screen with audience **External**, then use *Auto generate credentials* (or create a Web client with redirect URI `https://iap.googleapis.com/v1/oauth/clientIds/CLIENT_ID:handleRedirect` and apply it with `gcloud iap settings set`). While the consent screen is in *Testing*, only the test users listed on it can sign in — add the viewers there or publish the app.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | GCP project ID |
| `name_prefix` | string | yes | — | Short release prefix (2-8 chars) |
| `env` | string | yes | — | Environment name; suffixed into the service name |
| `region` | string | yes | — | Region the service runs in |
| `labels` | map(string) | yes | — | Labels applied to the service |
| `dashboard_sa_email` | string | yes | — | Runtime identity; granted read on the reporting dataset |
| `reporting_dataset_id` | string | yes | — | Wired into `REPORTING_DATASET` |
| `viewer_emails` | list(string) | no | `[]` | Users allowed through IAP |
| `image_uri` | string | no | `hello` sample | Image the service is created with; ignored afterwards |
| `memory` | string | no | `1Gi` | Container memory limit |
| `cpu` | string | no | `1` | Container CPU limit |
| `max_instances` | number | no | `2` | Instance cap (cost guard) |
| `request_timeout` | string | no | `3600s` | Longest a websocket session stays open |
| `deployer_sa_email` | string | no | `null` | Cloud Build SA granted deploy rights; `null` skips |

## Outputs

| Name | Description |
|---|---|
| `service_name` | Short service name, e.g. `co-dashboard-dev` |
| `service_url` | run.app URL of the dashboard |
