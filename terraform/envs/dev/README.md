# terraform/envs/dev

Composition root for the **dev** GCP environment. Every Phase 0 and Phase 1
module is wired in from this directory. State is stored remotely in the GCS
bucket provisioned by `terraform/bootstrap`, and every apply impersonates the
long-lived `co-tf-runner-sa` service account.

This directory ships as an **empty composition**: the backend and provider
are configured, but no modules are wired up yet. A clean `terraform plan`
should report `No changes`. Modules are added incrementally in subsequent
PRs.

---

## Prerequisites

- `terraform/bootstrap` has been applied successfully against this project
  (state bucket `co-tf-state-dev` and SA `co-tf-runner-sa` exist).
- `gcloud` and `terraform` (`>= 1.6, < 2.0`) installed.
- You have either `roles/owner` on the project, **or** the role
  `roles/iam.serviceAccountTokenCreator` on the runner SA. The provider is
  configured to impersonate the runner SA, and impersonation requires that
  role on your user identity.

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

---

## Init

```bash
terraform init
```

Initial init pulls the provider plugin and configures the GCS backend
against `co-tf-state-dev` with prefix `dev/`. If the bucket does not yet
exist, init will fail with a clear error — re-apply `terraform/bootstrap`
first.

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
