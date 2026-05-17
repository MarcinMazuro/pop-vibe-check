terraform {
  # Remote state lives in the GCS bucket provisioned by terraform/bootstrap.
  # The bucket name is intentionally hard-coded here because the GCS backend
  # block does not accept variable interpolation. State for this environment
  # is namespaced under the 'dev/' prefix so 'prod' can use the same bucket
  # without collisions when it lands.
  backend "gcs" {
    bucket = "co-tf-state-dev"
    prefix = "dev/"
  }
}
