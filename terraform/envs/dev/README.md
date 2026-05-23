# terraform/envs/dev

Composition root for the **dev** GCP environment. Every Phase 0 and Phase 1
module is wired in from this directory. State is stored remotely in the GCS
bucket provisioned by `terraform/bootstrap`, and every apply impersonates the
long-lived `pvc-tf-runner-sa` service account.

This directory ships as an **empty composition**: the backend and provider
are configured, but no modules are wired up yet. A clean `terraform plan`
should report `No changes`. Modules are added incrementally in subsequent
PRs.

---

## Prerequisites

- `terraform/bootstrap` has been applied successfully against this project
  (state bucket `pvc-tf-state` and SA `pvc-tf-runner-sa` exist).
- `gcloud` and `terraform` (`>= 1.6, < 2.0`) installed.
- You hold `roles/iam.serviceAccountTokenCreator` on the runner SA. The
  provider impersonates the SA on every apply, and impersonation requires
  this role on your user identity. **`roles/owner` is not enough** — that
  role intentionally excludes `iam.serviceAccounts.getAccessToken` so an
  Owner cannot silently impersonate every SA in the project. Grant it
  once per operator with:

  ```bash
  gcloud iam service-accounts add-iam-policy-binding \
    pvc-tf-runner-sa@<PROJECT_ID>.iam.gserviceaccount.com \
    --member="user:<your-email>" \
    --role="roles/iam.serviceAccountTokenCreator" \
    --project=<PROJECT_ID>
  ```

### One-time auth

```bash
gcloud auth login                              # gcloud CLI
gcloud auth application-default login          # ADC, used by Terraform
gcloud config set project <PROJECT_ID>
```

### Configure variables

Copy the example file and fill in your project ID:

```bash
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars
```

`terraform.tfvars` is excluded by the repository `.gitignore`; the
`.tfvars.example` file is committed.

### Case-study prefix (`name_prefix`)

The composition takes an optional `name_prefix` variable (default `"co"`
for Clair Obscur: Expedition 33). It is prepended to every
release-specific resource name — buckets, datasets, topics, workload
service accounts — so multiple case studies can live in the same GCP
project without name collisions.

The universal state bucket (`pvc-tf-state`) and runner SA
(`pvc-tf-runner-sa`) created by `terraform/bootstrap` are **not** affected
by `name_prefix` — they are shared infrastructure across every release and
every environment. `name_prefix` only flows into release-scoped resources
(buckets, datasets, topics, workload SAs).

**If you want to analyse a different release** (e.g. `name_prefix = "w4"`
for Witcher 4): use a separate Terraform state by either creating a
sibling composition directory (e.g. `terraform/envs/dev-w4/` with its
own `backend.tf` prefix) or by using `terraform workspace`. Re-running
this directory with a different `name_prefix` against the **same** state
would replace the existing resources, which is almost never what you
want.

---

## Init

```bash
terraform init
```

Initial init pulls the provider plugin and configures the GCS backend
against the universal state bucket `pvc-tf-state` with prefix `dev/`. If
the bucket does not yet exist, init will fail with a clear error —
re-apply `terraform/bootstrap` first.

---

## Plan / apply

```bash
terraform plan
terraform apply
```

While this composition is empty, `terraform plan` should print
**`No changes. Your infrastructure matches the configuration.`** If it
does not, something in the backend / provider wiring is off — fix that
before adding modules.

---

## How to add a module

When a module under `terraform/modules/<name>/` is ready, wire it up here:

1. Add a `module "<name>" { source = "../../modules/<name>" ... }` block in
   [main.tf](main.tf), passing `env = local.env`, `project_id = var.project_id`,
   `region = var.region`, `labels = local.labels`, plus any module-specific
   inputs.
2. Surface anything downstream consumers need via [outputs.tf](outputs.tf).
3. Run `terraform plan` locally before opening the PR — every new module
   should produce a reviewable diff.

---

## Files

| File | Purpose |
|---|---|
| [versions.tf](versions.tf) | Pins Terraform and provider versions |
| [backend.tf](backend.tf) | GCS remote state configuration |
| [providers.tf](providers.tf) | Google provider + runner SA impersonation |
| [variables.tf](variables.tf) | Input variables (`project_id`, `region`) |
| [main.tf](main.tf) | Composition root (modules wired here) |
| [outputs.tf](outputs.tf) | Outputs (added alongside modules) |
| [terraform.tfvars.example](terraform.tfvars.example) | Template for local `terraform.tfvars` |
