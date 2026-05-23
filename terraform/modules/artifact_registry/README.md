# modules/artifact_registry

Provisions one Docker repository plus reader/writer IAM bindings.

## What this creates

- **`{name_prefix}-images-{env}`** — Docker-format Artifact Registry repository in the supplied region.
- **`roles/artifactregistry.writer`** for each SA in `writer_sa_emails` (typically the per-env Cloud Build SA — it pushes built collector / publisher / Dataflow images on every CI run).
- **`roles/artifactregistry.reader`** for each SA in `reader_sa_emails` (workload SAs that pull images at runtime — collector Cloud Run Jobs, publisher Cloud Run Job, Dataflow workers).

No cleanup policy is set on the repository. Image-version retention is unbounded by design: storage cost for an unpruned image set is negligible at thesis scale and an immutable record of what shipped beats disk savings.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | GCP project ID — used in the repository URL output |
| `name_prefix` | string | yes | — | Short release prefix (2-8 chars, lowercase alphanumeric/hyphen) |
| `env` | string | yes | — | Environment name; suffixed into the repository ID |
| `region` | string | yes | — | Region for the repository |
| `labels` | map(string) | yes | — | Labels applied to the repository |
| `writer_sa_emails` | list(string) | yes | — | SAs that push images (Cloud Build, future release-promotion job) |
| `reader_sa_emails` | list(string) | yes | — | SAs that pull images at runtime (collectors, publisher, Dataflow workers) |

## Outputs

| Name | Description |
|---|---|
| `repository_id` | Short repo ID, e.g. `co-images-dev` |
| `repository_full_id` | Fully-qualified resource ID (`projects/.../locations/.../repositories/...`) |
| `repository_url` | Image-URI prefix: `LOCATION-docker.pkg.dev/PROJECT/REPO` |

## Notes

- **Per env, per release.** Dev's Cloud Build SA can push to `co-images-dev` but not to `co-images-prod` — both repositories are independent and a build running in dev has no path to prod's registry.
- **Bindings sit here**, not in `iam/`, per the project's "bindings next to the resource" convention.
- **Image URIs in downstream modules**: use the `repository_url` output and append `/IMAGE_NAME:TAG`. Example for a Cloud Run Job: `${repository_url}/reddit-collector:${git_sha}`.
