# ----------------------------------------------------------------------------
# Vertex NLP module — Workbench (fine-tune), Endpoint (serve), IAM.
#
# Both the T4 Workbench instance and the serving Endpoint are gated
# (count = 0 by default). A routine `terraform apply` must never start a
# GPU: Workbench T4 and a deployed Endpoint replica are the second-largest
# cost line after streaming Dataflow. IAM for the trainer SA and the
# Dataflow worker SA is *not* gated — predict/upload grants are cheap and
# must already exist when an operator flips a gate on.
#
# Model versions live in Vertex AI Model Registry as training artifacts.
# Terraform does not upload or deploy them; see this module's README.
# ----------------------------------------------------------------------------

data "google_project" "current" {
  project_id = var.project_id
}

locals {
  workbench_name = "${var.name_prefix}-nlp-workbench-${var.env}"
  endpoint_id    = "${var.name_prefix}-nlp-endpoint-${var.env}"

  # Google-managed notebooks service agent. Needs actAs on the trainer SA
  # so it can attach that identity to the Workbench GCE VM.
  notebooks_service_agent = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-notebooks.iam.gserviceaccount.com"
}

# ----------------------------------------------------------------------------
# Trainer SA — Vertex user.
#
# roles/aiplatform.user covers Model.upload, Endpoint.deploy, and the
# Workbench-side Vertex client. Resource-level GCS / BigQuery / Artifact
# Registry grants live in those modules, next to what they protect.
# ----------------------------------------------------------------------------
resource "google_project_iam_member" "trainer_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${var.trainer_sa_email}"
}

# The notebooks service agent must actAs the trainer SA to boot Workbench
# as that identity. Harmless while the instance is gated off.
resource "google_service_account_iam_member" "notebooks_act_as_trainer" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${var.trainer_sa_email}"
  role               = "roles/iam.serviceAccountUser"
  member             = local.notebooks_service_agent
}

# ----------------------------------------------------------------------------
# Dataflow worker SA — predict.
#
# roles/aiplatform.user is what Endpoint.predict checks. Granted at project
# scope (always, not gated on the Endpoint resource) so flipping
# enable_endpoint does not race a Dataflow launch. The worker still cannot
# call a missing endpoint; it just has permission when one exists.
# ----------------------------------------------------------------------------
resource "google_project_iam_member" "dataflow_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${var.dataflow_worker_sa_email}"
}

# ----------------------------------------------------------------------------
# Workbench T4 — gated.
#
# n1-standard-8 + NVIDIA_TESLA_T4 x1 in europe-central2-b/c. No public IP:
# Jupyter is reached through the Vertex console proxy; Google APIs go over
# Private Google Access on the existing subnet. desired_state defaults to
# STOPPED even when count = 1, so creating the VM does not start the GPU.
# ----------------------------------------------------------------------------
resource "google_workbench_instance" "nlp" {
  count = var.enable_workbench ? 1 : 0

  project  = var.project_id
  name     = local.workbench_name
  location = var.workbench_zone

  instance_owners = var.workbench_owners
  desired_state   = var.workbench_desired_state
  labels          = var.labels

  gce_setup {
    machine_type      = var.workbench_machine_type
    disable_public_ip = true

    accelerator_configs {
      type       = "NVIDIA_TESLA_T4"
      core_count = 1
    }

    service_accounts {
      email = var.trainer_sa_email
    }

    boot_disk {
      disk_type    = "PD_SSD"
      disk_size_gb = 150
    }

    data_disks {
      disk_type    = "PD_STANDARD"
      disk_size_gb = 100
    }

    network_interfaces {
      network = var.network_id
      subnet  = var.subnet_id
    }

    metadata = {
      idle-timeout-seconds = tostring(var.workbench_idle_timeout_seconds)
    }

    tags = ["workbench"]
  }

  timeouts {
    create = "20m"
    update = "20m"
    delete = "20m"
  }
}

# ----------------------------------------------------------------------------
# Serving Endpoint — gated.
#
# Creates an empty Endpoint. Deploying a Model Registry version onto it
# (the replica that actually bills for GPU/CPU) is `nlp/endpoint/register.py`
# plus the runbook, not this resource. traffic_split stays unset until a
# deploy writes it.
# ----------------------------------------------------------------------------
resource "google_vertex_ai_endpoint" "nlp" {
  count = var.enable_endpoint ? 1 : 0

  project      = var.project_id
  name         = local.endpoint_id
  display_name = local.endpoint_id
  description  = "DistilBERT sentiment serving endpoint for release ${var.name_prefix} (${var.env}). Models are deployed out of band; Terraform only holds the Endpoint."
  location     = var.region
  labels       = var.labels
}
