locals {
  # Universal Terraform runner SA provisioned by terraform/bootstrap — one
  # SA shared across every environment and every case study. Every apply
  # against this composition impersonates this identity so that the human
  # operator's standing project permissions are not what actually creates
  # the resources. Same flow is used by Cloud Build once that wiring lands.
  #
  # The 'pvc-' prefix is the bootstrap name_prefix default; if bootstrap
  # was applied with a different value, edit this string to match.
  terraform_runner_sa_email = "pvc-tf-runner-sa@${var.project_id}.iam.gserviceaccount.com"
}

provider "google" {
  project                     = var.project_id
  region                      = var.region
  impersonate_service_account = local.terraform_runner_sa_email
}
