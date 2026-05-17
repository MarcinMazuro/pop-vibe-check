terraform {
  required_version = ">= 1.6, < 2.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0, < 6.0"
    }
  }

  # Local backend is the deliberate exception for this configuration: it
  # creates the GCS bucket that hosts remote state for every other Terraform
  # configuration in the repo, so it cannot itself use remote state. Once
  # terraform/envs/dev exists, the local state file here is archived and
  # bootstrap is not re-applied except for explicit recovery work.
  backend "local" {}
}
