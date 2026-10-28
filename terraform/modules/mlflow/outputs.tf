output "service_name" {
  description = "Short name of the MLflow Cloud Run service (e.g. 'co-mlflow-dev')."
  value       = google_cloud_run_v2_service.mlflow.name
}

output "service_url" {
  description = "run.app URL of the MLflow server. Opens through IAP once it is enabled on the service; clients set MLFLOW_TRACKING_URI to it."
  value       = google_cloud_run_v2_service.mlflow.uri
}

output "instance_connection_name" {
  description = "Cloud SQL connection name (project:region:instance), for the Cloud SQL Auth Proxy."
  value       = google_sql_database_instance.mlflow.connection_name
}
