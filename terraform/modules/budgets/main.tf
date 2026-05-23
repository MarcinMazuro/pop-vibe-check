# ----------------------------------------------------------------------------
# Email notification channels for budget alerts.
#
# Each email becomes a Cloud Monitoring email channel scoped to this project.
# IMPORTANT: GCP sends a verification email to every new address on first
# create; the channel exists immediately but does NOT deliver until the
# recipient clicks the verification link. Document this in the module
# README so operators are not surprised by silent budgets.
# ----------------------------------------------------------------------------
resource "google_monitoring_notification_channel" "email" {
  for_each = toset(var.notification_emails)

  project      = var.project_id
  display_name = "${var.name_prefix} ${var.env} budget alerts → ${each.value}"
  type         = "email"

  labels = {
    email_address = each.value
  }
}

# ----------------------------------------------------------------------------
# Monthly billing budget with multi-threshold alerts.
#
# Filter is scoped to this project so a budget on the shared billing
# account does not fire on spend from other GCP projects under the same
# billing account.
#
# disable_default_iam_recipients = true means *only* the listed email
# channels get the alert — billing admins on the account do not, by
# default, get notified. Cleaner for thesis-scale, prevents the project
# owner inbox from getting alerts they did not opt in to.
# ----------------------------------------------------------------------------
resource "google_billing_budget" "monthly" {
  billing_account = var.billing_account_id
  display_name    = "${var.name_prefix} ${var.env} monthly budget"

  budget_filter {
    projects               = ["projects/${var.project_id}"]
    credit_types_treatment = var.include_credits ? "INCLUDE_ALL_CREDITS" : "EXCLUDE_ALL_CREDITS"
  }

  amount {
    specified_amount {
      units = tostring(var.monthly_amount)
    }
  }

  dynamic "threshold_rules" {
    for_each = toset(var.threshold_percentages)
    content {
      threshold_percent = threshold_rules.value
      spend_basis       = "CURRENT_SPEND"
    }
  }

  all_updates_rule {
    monitoring_notification_channels = [
      for c in google_monitoring_notification_channel.email : c.id
    ]
    disable_default_iam_recipients = true
  }
}
