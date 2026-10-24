terraform {
  required_version = ">= 1.7, < 2.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0, < 6.0"
    }
    # Dataform repositories are beta-only in provider 5.x (modules/dataform).
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 5.0, < 6.0"
    }
  }
}
