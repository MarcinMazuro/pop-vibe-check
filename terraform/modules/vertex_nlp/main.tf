# ----------------------------------------------------------------------------
# Vertex NLP module — Workbench (fine-tune), Endpoint (serve), IAM.
#
# Both the Workbench instance and the serving Endpoint are gated
# (count = 0 by default). A routine `terraform apply` must never start a
# GPU: Workbench defaults to CPU-only (no guest_accelerator) and a
# deployed Endpoint replica is still the second-largest cost line after
# streaming Dataflow. IAM for the trainer SA and the Dataflow worker SA
# is *not* gated — predict/upload grants are cheap and must already exist
# when an operator flips a gate on.
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
# Workbench — gated, CPU-only by default.
#
# e2-standard-4, no guest_accelerator. Omit accelerator_configs entirely
# when workbench_accelerator_count is 0 so terraform plan cannot mention
# NVIDIA / T4. GPU training is opt-in (count=1 + NVIDIA_TESLA_T4) and is
# blocked on free-tier billing. No public IP: Jupyter goes through the
# Vertex console proxy; SSH uses IAP (firewall below). Google APIs go
# over Private Google Access. desired_state defaults to STOPPED even
# when count = 1, so creating the VM does not start billing until ACTIVE.
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

    dynamic "accelerator_configs" {
      for_each = var.workbench_accelerator_count > 0 ? [1] : []
      content {
        type       = var.workbench_accelerator_type
        core_count = var.workbench_accelerator_count
      }
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

  lifecycle {
    precondition {
      condition     = var.workbench_accelerator_count == 0 || trimspace(var.workbench_accelerator_type) != ""
      error_message = "workbench_accelerator_type is required when workbench_accelerator_count > 0."
    }
  }

  timeouts {
    create = "20m"
    update = "20m"
    delete = "20m"
  }
}

# IAP TCP forwarding range (https://cloud.google.com/iap/docs/using-tcp-forwarding).
# Custom-mode VPC has no default allow-ssh; without this, a Workbench VM
# with disable_public_ip cannot be reached by `gcloud compute ssh --tunnel-through-iap`.
resource "google_compute_firewall" "workbench_iap_ssh" {
  count = var.enable_workbench ? 1 : 0

  project = var.project_id
  name    = "${var.name_prefix}-allow-workbench-iap-ssh-${var.env}"
  network = var.network_id

  description = "Allow IAP-tunneled SSH to Workbench (no public IP)."

  direction     = "INGRESS"
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["workbench"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
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
