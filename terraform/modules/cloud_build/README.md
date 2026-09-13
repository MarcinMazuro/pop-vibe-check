# modules/cloud_build

Cloud Build CI/CD for one environment: the GitHub connection, the triggers,
and the secrets and IAM they need.

## What this creates

**Always:**

- **`{name_prefix}-github-token-{env}`** — empty secret container for the GitHub token the connection authorizes with. Only the Cloud Build service agent (`service-<number>@gcp-sa-cloudbuild.iam.gserviceaccount.com`) can read it.
- **`{name_prefix}-tfvars-{env}`** — empty secret container for the env's canonical `terraform.tfvars`. Read by the Terraform CI SA.
- `roles/logging.logWriter` for the Cloud Build SA (builds use `CLOUD_LOGGING_ONLY`).
- `roles/cloudbuild.builds.approver` for each of `approver_emails`.

**Once `github_app_installation_id` is set:**

- **`{name_prefix}-github-{env}`** — Cloud Build (2nd gen) GitHub connection, and the linked repository.
- The triggers below, all in `var.region`.

| Trigger | Event | Files | Runs as | Config | Does |
|---|---|---|---|---|---|
| `co-python-checks-pr-dev` | PR → main | `**/*.py`, `pyproject.toml`, `requirements-dev.txt`, `collectors/config/**` | Cloud Build SA | `cloudbuild.checks.yaml` | ruff, black `--check`, pytest |
| `co-youtube-collector-pr-dev` | PR → main | `collectors/{youtube,common,config}/**` | Cloud Build SA | `collectors/youtube/cloudbuild.yaml` | image build only |
| `co-youtube-collector-deploy-dev` | push main | same | Cloud Build SA | same | build, push `:<sha>`, `gcloud run jobs update --image=@digest` |
| `co-publisher-pr-dev` | PR → main | `publisher/**`, `collectors/{common,config}/**` | Cloud Build SA | `publisher/cloudbuild.yaml` | image build only |
| `co-publisher-deploy-dev` | push main | same | Cloud Build SA | same | build, push, deploy to the publisher job |
| `co-sentiment-pipeline-pr-dev` | PR → main | `dataflow/**`, `nlp/**` | Cloud Build SA | `dataflow/cloudbuild.yaml` | image build only (import check included) |
| `co-sentiment-pipeline-deploy-dev` | push main | same | Cloud Build SA | same | build, push, publish template specs — **never launches a job** |
| `co-terraform-plan-pr-dev` | PR → main | `terraform/**` | Terraform CI SA | `terraform/cloudbuild.yaml` | fmt, validate, plan |
| `co-terraform-apply-dev` | push main | `terraform/**` | Terraform CI SA | same | **manual approval**, then plan + apply |

Markdown and test files are ignored by the image triggers; the pipeline
image additionally ignores the NLP training, eval and notebook trees, which
its Dockerfile deletes anyway. The Reddit collector has no trigger — the
source is out of scope.

Pull requests from forks do not build until a collaborator comments
`/gcbrun` (the repository is public, and a PR build runs its Dockerfiles and
tests). Collaborators' own PRs build immediately.

## Identities

| SA | Created in | Used for | Can |
|---|---|---|---|
| `co-cloud-build-sa-dev` | `modules/iam` | checks, image builds, deploys | push to Artifact Registry; `run.developer` on the YouTube and publisher jobs + actAs their SAs; write `templates/` in the dataflow-temp bucket; launch Dataflow jobs |
| `pvc-tf-ci-sa` | `terraform/bootstrap` | terraform plan / apply | read the tfvars secret; impersonate `pvc-tf-runner-sa` |

The split is deliberate: image builds execute code from pull requests, so
their identity must not be able to mint runner tokens.

## First-time setup

The connection cannot be created by Terraform alone — GitHub needs an app
installation and a token first. Setup takes two applies.

1. **Apply with `github_app_installation_id` unset.** Creates the two
   secret containers and the grants.

2. **Install the Google Cloud Build GitHub App** on the repository owner:
   <https://github.com/apps/google-cloud-build> → *Install* → *Only select
   repositories* → this repository. The installation ID is the number at
   the end of the app's page under <https://github.com/settings/installations>
   (`.../installations/<id>`). It is not secret.

3. **Create a classic personal access token** at
   <https://github.com/settings/tokens> with scopes **`repo`** and
   **`read:user`**, owned by the same GitHub account. Prefer no expiry: an
   expired token silently stops every trigger until a new version is added.
   Store it without it touching shell history or files:

   ```bash
   read -rs GH_TOKEN && printf '%s' "$GH_TOKEN" | \
     gcloud secrets versions add co-github-token-dev --project=<PROJECT_ID> --data-file=- \
     && unset GH_TOKEN
   ```

4. **Publish the canonical tfvars**, now including
   `github_app_installation_id = <id>`:

   ```bash
   gcloud secrets versions add co-tfvars-dev --project=<PROJECT_ID> \
     --data-file=terraform/envs/dev/terraform.tfvars
   ```

5. **Apply again, locally.** Creates the connection, the repository and the
   triggers. Every later apply goes through `co-terraform-apply-dev`.

### Rotating the GitHub token

Add a new version to `co-github-token-dev` (step 3). The connection reads
`versions/latest`, so no apply is needed.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | GCP project ID |
| `name_prefix` | string | yes | — | Release prefix for names |
| `env` | string | yes | — | Environment suffix |
| `region` | string | yes | — | Region of the connection, triggers and builds |
| `labels` | map(string) | yes | — | Labels on the secret containers |
| `github_owner` | string | yes | — | GitHub owner of the repository |
| `github_repo` | string | yes | — | GitHub repository name |
| `github_app_installation_id` | number | no | `null` | Cloud Build GitHub App installation; `null` skips connection and triggers |
| `cloud_build_sa_email` | string | yes | — | SA for checks and image triggers |
| `terraform_ci_sa_email` | string | yes | — | SA for Terraform triggers (from bootstrap) |
| `terraform_runner_sa_email` | string | yes | — | Runner SA the Terraform builds impersonate for the state backend |
| `terraform_env_dir` | string | yes | — | Composition the Terraform triggers run, e.g. `terraform/envs/dev` |
| `approver_emails` | list(string) | no | `[]` | Users who can approve the apply build |
| `artifact_registry_repository_id` | string | yes | — | Short repository ID images are pushed to |
| `youtube_job_name` | string | yes | — | Cloud Run Job the YouTube image is deployed to |
| `publisher_job_name` | string | yes | — | Cloud Run Job the publisher image is deployed to |
| `template_spec_dir` | string | yes | — | `gs://` prefix for Flex Template specs |

## Outputs

| Name | Description |
|---|---|
| `github_token_secret_id` | Secret ID for the GitHub token |
| `tfvars_secret_id` | Secret ID for the canonical tfvars |
| `connection_name` | Connection name; empty until the installation ID is set |
| `trigger_names` | All trigger names; empty until the installation ID is set |

## Notes

- **The PR plan is not the applied plan.** Cloud Build asks for approval
  before a build starts, so `co-terraform-apply-dev` re-plans after
  approval and applies that. Its log is the record of what changed.
- **Plans and applies take the state lock.** A PR plan racing an apply
  waits up to 10 minutes (`-lock-timeout`), then fails; re-run it.
- **Build logs stay in Cloud Logging**, not on GitHub. Plans print the
  tfvars inputs (billing account, emails) and the repository is public.
- **Image tags are full commit SHAs; deploys use digests.** Terraform
  ignores the job images — see `modules/cloud_run_jobs/README.md`.
