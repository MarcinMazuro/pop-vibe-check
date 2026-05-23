terraform {
  # Remote state lives in the universal state bucket provisioned by
  # terraform/bootstrap (one bucket per GCP project, shared by every
  # environment and every case study). The bucket name is hard-coded
  # because the GCS backend block does not accept variable interpolation.
  # State for this composition is namespaced under the 'dev/' prefix; a
  # future envs/prod/ would use 'prod/', envs/dev-w4/ would use 'dev-w4/'.
  backend "gcs" {
    bucket = "pvc-tf-state"
    prefix = "dev/"
  }
}
