locals {
  # Long-lived runner service account provisioned by terraform/bootstrap.
  # Every apply against this environment impersonates this identity so that
  # the human operator's standing project permissions are not what actually
  # creates the resources. Same flow is used by Cloud Build once that wiring
  # is added.
  terraform_runner_sa_email = "co-tf-runner-sa@${var.project_id}.iam.gserviceaccount.com"
}

provider "google" {
  project                     = var.project_id
  region                      = var.region
  impersonate_service_account = local.terraform_runner_sa_email
}
