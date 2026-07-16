output "reddit_job_name" {
  description = "Short name of the Reddit collector job (e.g. 'co-reddit-collector-dev'). Use in `gcloud run jobs execute`."
  value       = google_cloud_run_v2_job.reddit_collector.name
}

output "youtube_job_name" {
  description = "Short name of the YouTube collector job."
  value       = google_cloud_run_v2_job.youtube_collector.name
}

output "reddit_job_id" {
  description = "Fully-qualified job resource ID (projects/.../locations/.../jobs/...)."
  value       = google_cloud_run_v2_job.reddit_collector.id
}

output "youtube_job_id" {
  description = "Fully-qualified job resource ID for the YouTube collector."
  value       = google_cloud_run_v2_job.youtube_collector.id
}

output "publisher_job_name" {
  description = "Short name of the replay publisher job (e.g. 'co-publisher-dev'). Use in `gcloud run jobs execute`."
  value       = google_cloud_run_v2_job.publisher.name
}

output "publisher_job_id" {
  description = "Fully-qualified job resource ID for the replay publisher."
  value       = google_cloud_run_v2_job.publisher.id
}
