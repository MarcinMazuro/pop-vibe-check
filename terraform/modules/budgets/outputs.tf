output "budget_id" {
  description = "Fully-qualified budget resource name (billingAccounts/.../budgets/...). Useful for adding the resource to GCP audit log filters."
  value       = google_billing_budget.monthly.id
}

output "notification_channel_ids" {
  description = "Map of email → notification channel resource ID. Re-usable if a future module (e.g. uptime checks) wants to send alerts to the same recipients without re-declaring channels."
  value = {
    for email, channel in google_monitoring_notification_channel.email :
    email => channel.id
  }
}
