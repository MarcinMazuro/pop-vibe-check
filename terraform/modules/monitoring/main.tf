# ----------------------------------------------------------------------------
# Alert policies for the streaming path.
#
# Four things can go wrong quietly between a replay being started and its
# rows landing in BigQuery, and each of them costs either money or data:
#
#   1. the Dataflow job fails — the replay silently stops mid-run;
#   2. the job is left running — a streaming job bills until drained and is
#      the most expensive resource in this project;
#   3. the pipeline falls behind (or is not running at all) while the
#      publisher keeps emitting — the backlog ages on the subscription;
#   4. records reach the dead-letter topic — they never make it into
#      events, so any chart built on it is quietly short.
#
# Notification channels are not created here: the budgets module already
# owns one per alert recipient, and two channels for the same address
# would mean two verification emails and two copies of every alert.
# ----------------------------------------------------------------------------

locals {
  # An alert on a gauge that stops being written (a drained job reports no
  # more elapsed_time) would otherwise stay open forever.
  auto_close = "604800s"

  common_documentation_suffix = "\n\nRaised by the ${var.name_prefix} ${var.env} monitoring module (terraform/modules/monitoring)."
}

# ----------------------------------------------------------------------------
# 1. Dataflow job failed.
# ----------------------------------------------------------------------------
resource "google_monitoring_alert_policy" "dataflow_job_failed" {
  project      = var.project_id
  display_name = "${var.name_prefix} ${var.env} — Dataflow job failed"
  combiner     = "OR"

  documentation {
    content   = "A Dataflow job entered the failed state. The replay stopped mid-run, so events_landing holds only part of it — do not promote. Check the job's logs, then relaunch.${local.common_documentation_suffix}"
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "job/is_failed > 0"

    condition_threshold {
      filter          = "resource.type = \"dataflow_job\" AND metric.type = \"dataflow.googleapis.com/job/is_failed\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_MAX"
        cross_series_reducer = "REDUCE_MAX"
        group_by_fields      = ["metric.label.job_name"]
      }
    }
  }

  notification_channels = var.notification_channel_ids

  alert_strategy {
    auto_close = local.auto_close
  }
}

# ----------------------------------------------------------------------------
# 2. Streaming job left running.
#
# The cost guard. Every replay in this project is minutes to hours, so a
# job still running after max_job_runtime_hours means someone forgot to
# drain it.
# ----------------------------------------------------------------------------
resource "google_monitoring_alert_policy" "dataflow_job_running_too_long" {
  project      = var.project_id
  display_name = "${var.name_prefix} ${var.env} — Dataflow job running too long"
  combiner     = "OR"

  documentation {
    content   = "A Dataflow job has been running for more than ${var.max_job_runtime_hours}h. Streaming jobs bill continuously until drained. Drain it with `gcloud dataflow jobs drain JOB_ID --region=${var.region}` (drain, not cancel — in-flight records still reach BigQuery).${local.common_documentation_suffix}"
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "job/elapsed_time > ${var.max_job_runtime_hours}h"

    condition_threshold {
      filter          = "resource.type = \"dataflow_job\" AND metric.type = \"dataflow.googleapis.com/job/elapsed_time\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.max_job_runtime_hours * 3600
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_MAX"
        cross_series_reducer = "REDUCE_MAX"
        group_by_fields      = ["metric.label.job_name"]
      }
    }
  }

  notification_channels = var.notification_channel_ids

  alert_strategy {
    auto_close = local.auto_close
  }
}

# ----------------------------------------------------------------------------
# 3. Replay backlog ageing on the Dataflow subscription.
#
# Oldest unacked age, not message count: a paced replay always has some
# backlog, but a healthy pipeline keeps it young. An ageing backlog means
# the pipeline is behind, stuck, or not running while the publisher is.
# ----------------------------------------------------------------------------
resource "google_monitoring_alert_policy" "pubsub_backlog_ageing" {
  project      = var.project_id
  display_name = "${var.name_prefix} ${var.env} — replay backlog ageing"
  combiner     = "OR"

  documentation {
    content   = "The oldest unacknowledged message on `${var.dataflow_subscription_name}` is older than ${var.backlog_age_alert_seconds}s. Either no Dataflow job is consuming the replay, or the running one is stuck. Check for an active job in ${var.region}.${local.common_documentation_suffix}"
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "oldest_unacked_message_age > ${var.backlog_age_alert_seconds}s"

    condition_threshold {
      filter          = "resource.type = \"pubsub_subscription\" AND resource.label.subscription_id = \"${var.dataflow_subscription_name}\" AND metric.type = \"pubsub.googleapis.com/subscription/oldest_unacked_message_age\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.backlog_age_alert_seconds
      duration        = "300s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  notification_channels = var.notification_channel_ids

  alert_strategy {
    auto_close = local.auto_close
  }
}

# ----------------------------------------------------------------------------
# 4. Dead letters.
#
# Any record here is a record missing from events. One is worth knowing
# about, hence a threshold of zero.
# ----------------------------------------------------------------------------
resource "google_monitoring_alert_policy" "dlq_not_empty" {
  project      = var.project_id
  display_name = "${var.name_prefix} ${var.env} — dead-letter records"
  combiner     = "OR"

  documentation {
    content   = "Records reached the dead-letter subscription `${var.dlq_subscription_name}`: the pipeline could not parse or validate them, so they are missing from events. Inspect with `gcloud pubsub subscriptions pull ${var.dlq_subscription_name} --limit=10 --auto-ack`.${local.common_documentation_suffix}"
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "num_undelivered_messages > 0"

    condition_threshold {
      filter          = "resource.type = \"pubsub_subscription\" AND resource.label.subscription_id = \"${var.dlq_subscription_name}\" AND metric.type = \"pubsub.googleapis.com/subscription/num_undelivered_messages\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "300s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  notification_channels = var.notification_channel_ids

  alert_strategy {
    auto_close = local.auto_close
  }
}
