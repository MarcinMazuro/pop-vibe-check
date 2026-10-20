output "service_name" {
  description = "Short name of the dashboard Cloud Run service (e.g. 'co-dashboard-dev')."
  value       = google_cloud_run_v2_service.dashboard.name
}

output "service_url" {
  description = "run.app URL of the dashboard. Opens through IAP once it is enabled on the service."
  value       = google_cloud_run_v2_service.dashboard.uri
}
