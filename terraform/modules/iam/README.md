# modules/iam

Provisions per-workload service accounts. Bare identities only — IAM
bindings live alongside the resources they pertain to (bucket IAM in
`storage/`, dataset IAM in `bigquery/`, etc.), not in a central blob here.

## What this creates

Four service accounts, all named `${name_prefix}-{workload}-sa-${env}`:

- **`{name_prefix}-collector-reddit-sa-{env}`** — runs the Reddit collector Cloud Run Job.
- **`{name_prefix}-collector-youtube-sa-{env}`** — runs the YouTube collector Cloud Run Job.
- **`{name_prefix}-publisher-sa-{env}`** — runs the replay publisher Cloud Run Job (GCS → BigQuery load, chronological Pub/Sub replay).
- **`{name_prefix}-cloud-build-sa-{env}`** — executes Cloud Build triggers for this env (terraform, collector image builds, publisher image builds, Dataflow Flex Template uploads).

The Dataflow worker SA is deferred to the Dataflow PR, alongside the module that consumes it.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | GCP project ID; used to compose full SA emails in outputs |
| `name_prefix` | string | yes | — | Short release prefix (2-8 chars, lowercase alphanumeric/hyphen) |
| `env` | string | yes | — | Environment name; suffixed into account_ids |

## Outputs

| Name | Description |
|---|---|
| `collector_reddit_sa_email` | Email of the Reddit collector SA |
| `collector_youtube_sa_email` | Email of the YouTube collector SA |
| `publisher_sa_email` | Email of the replay publisher SA |
| `cloud_build_sa_email` | Email of the Cloud Build runner SA |
| `service_accounts` | Map of workload short name → SA email |
| `service_account_ids` | Map of workload short name → fully-qualified SA resource ID |

## Notes

- **`google_service_account` does not support labels in provider v5** — these resources are not tagged with the standard project/env/owner/managed_by set despite the project-wide convention. Documented exception.
- **No IAM bindings here.** When the `storage/`, `secrets/`, `artifact_registry/`, and `bigquery/` modules need to grant access to these workload SAs, they accept the SA emails as inputs and create resource-scoped bindings locally. Keeps the blast radius of any IAM change tight.
- **SAs are per-env** (`-dev`, `-prod`). This deviates from earlier drafts that listed them as cross-env identities; making each env own its workload SAs avoids cross-env IAM coupling and lets `prod` apply from scratch without conflicting with `dev`.
- **Cloud Build SA is also per-env** for the same reason — a build running in `dev` should not have credentials to push images to `prod` artifact registry. When triggers are wired (Phase 1), each trigger gets the env-matched SA.
