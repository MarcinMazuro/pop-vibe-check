# ----------------------------------------------------------------------------
# Performance experiments (perf/, docs/performance-plan.md).
#
# Experiments get their own staging and landing tables because the real
# ones are not safe to load-test against:
#
#   - promote.sql MERGEs *all* of events_landing into events. An
#     experiment writing to events_landing would, at the next real replay's
#     promote, insert its synthetic ids into events and overwrite real
#     model labels with whatever the experiment ran (the stub, say), since
#     the experiment's processed_at is fresher.
#   - raw_staging is what every real replay reads. Amplified copies of it
#     must live elsewhere.
#
# Nothing here is promoted, read by Dataform, or shown on the dashboard.
# The existing dataset-level grants already cover these tables: the
# Dataflow worker and the publisher hold dataEditor on the dataset.
# ----------------------------------------------------------------------------

# Amplified copies of raw_staging (k copies with suffixed ids), rewritten
# by perf/amplify.py. Same schema, partitioning and clustering as
# raw_staging, so the publisher's replay query behaves identically.
resource "google_bigquery_table" "raw_staging_perf" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = "raw_staging_perf"

  description = "Load-test input: amplified copies of raw_staging written by perf/amplify.py. Never read by real replays."

  schema = local.raw_schema

  time_partitioning {
    type  = "DAY"
    field = "created_utc"
  }

  clustering = ["source", "event_tag"]

  deletion_protection = false

  labels = var.labels
}

# Dataflow write target during experiments. Same schema as events_landing;
# never promoted into events.
resource "google_bigquery_table" "events_landing_perf" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = "events_landing_perf"

  description = "Load-test output: the pipeline's write target during perf experiments. Never promoted into events."

  schema = local.events_schema

  time_partitioning {
    type  = "DAY"
    field = "created_utc"
  }

  deletion_protection = false

  labels = var.labels
}

# One row per experiment run: parameters, throughput, correctness counts,
# Dataflow resource metrics and the cost estimate. Written by perf/collect.py.
resource "google_bigquery_table" "perf_runs" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = "perf_runs"

  description = "Performance experiment results, one row per run. Written by perf/collect.py."

  schema = jsonencode([
    { name = "run_id", type = "STRING", mode = "REQUIRED", description = "Experiment run id, e.g. 'e1-w2-s2000'." },
    { name = "experiment", type = "STRING", mode = "REQUIRED", description = "Experiment id from docs/performance-plan.md (e1 … e6)." },
    { name = "build_id", type = "STRING", mode = "NULLABLE", description = "Cloud Build id of the replay build that ran it." },
    { name = "job_id", type = "STRING", mode = "NULLABLE", description = "Dataflow job id." },
    { name = "job_name", type = "STRING", mode = "NULLABLE", description = "Dataflow job name." },
    { name = "git_commit", type = "STRING", mode = "NULLABLE", description = "Commit of the code that ran (HEAD of the submitted source)." },
    { name = "started_at", type = "TIMESTAMP", mode = "NULLABLE", description = "Dataflow job creation time." },
    { name = "finished_at", type = "TIMESTAMP", mode = "NULLABLE", description = "Dataflow job final state time." },
    { name = "model", type = "STRING", mode = "NULLABLE", description = "Classifier: stub or vertex." },
    { name = "speedup", type = "FLOAT", mode = "NULLABLE", description = "Publisher time-compression factor." },
    { name = "max_workers", type = "INTEGER", mode = "NULLABLE", description = "Dataflow max workers." },
    { name = "machine_type", type = "STRING", mode = "NULLABLE", description = "Dataflow worker machine type." },
    { name = "max_batch_size", type = "INTEGER", mode = "NULLABLE", description = "Records per classifier call; null = template default." },
    { name = "endpoint_replicas", type = "INTEGER", mode = "NULLABLE", description = "Vertex replicas deployed during the run (recorded by hand for vertex runs)." },
    { name = "staging_table", type = "STRING", mode = "NULLABLE", description = "Staging table the publisher replayed." },
    { name = "copies", type = "INTEGER", mode = "NULLABLE", description = "Amplification factor of the staging table (1 = real data)." },
    { name = "records_expected", type = "INTEGER", mode = "NULLABLE", description = "Distinct ids in the staging table replayed." },
    { name = "records_landed", type = "INTEGER", mode = "NULLABLE", description = "Rows the job wrote to events_landing_perf." },
    { name = "distinct_ids_landed", type = "INTEGER", mode = "NULLABLE", description = "Distinct ids the job wrote." },
    { name = "active_minutes", type = "INTEGER", mode = "NULLABLE", description = "Minutes with at least one row written." },
    { name = "mean_rps", type = "FLOAT", mode = "NULLABLE", description = "Mean records per second over active minutes." },
    { name = "p50_rps", type = "FLOAT", mode = "NULLABLE", description = "Median of per-minute records per second." },
    { name = "peak_rps", type = "FLOAT", mode = "NULLABLE", description = "Highest per-minute records per second." },
    {
      name        = "job_metrics"
      type        = "RECORD"
      mode        = "REPEATED"
      description = "Dataflow service metrics at the end of the job (vCPU time, memory, disk, Streaming Engine data …)."
      fields      = [
        { name = "name", type = "STRING", mode = "REQUIRED" },
        { name = "value", type = "FLOAT", mode = "NULLABLE" },
      ]
    },
    { name = "estimated_cost_usd", type = "FLOAT", mode = "NULLABLE", description = "Cost estimated from resource usage and perf/prices.yaml; null if prices are not filled in." },
    { name = "notes", type = "STRING", mode = "NULLABLE", description = "Free-text notes for the run." },
    { name = "collected_at", type = "TIMESTAMP", mode = "REQUIRED", description = "When perf/collect.py wrote the row." },
    { name = "num_workers", type = "INTEGER", mode = "NULLABLE", description = "Fixed worker count with autoscaling off; null = autoscaling." },
    { name = "load_source", type = "STRING", mode = "NULLABLE", description = "publisher (ordered replay) or loadgen (perf/loadgen.py)." },
    { name = "target_rps", type = "FLOAT", mode = "NULLABLE", description = "Load-generator target rate; null = unlimited or publisher." },
    { name = "publish_mean_rps", type = "FLOAT", mode = "NULLABLE", description = "Messages per second the load generator achieved." },
    { name = "publish_peak_rps", type = "INTEGER", mode = "NULLABLE", description = "Highest messages in one second the load generator achieved." },
  ])

  deletion_protection = false

  labels = var.labels
}

# Cloud Monitoring time series captured for each run (vCPUs, backlog,
# freshness, endpoint replicas and latency). Dataflow history expires after
# about 30 days, so this is the durable copy.
resource "google_bigquery_table" "perf_timeseries" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = "perf_timeseries"

  description = "Cloud Monitoring time series per performance experiment run. Written by perf/collect.py."

  schema = jsonencode([
    { name = "run_id", type = "STRING", mode = "REQUIRED", description = "Experiment run id (perf_runs.run_id)." },
    { name = "metric_type", type = "STRING", mode = "REQUIRED", description = "Cloud Monitoring metric type." },
    { name = "resource_labels", type = "STRING", mode = "NULLABLE", description = "Monitored resource labels as JSON." },
    { name = "point_time", type = "TIMESTAMP", mode = "REQUIRED", description = "End time of the sample interval." },
    { name = "value", type = "FLOAT", mode = "NULLABLE", description = "Sample value (mean for distributions)." },
  ])

  time_partitioning {
    type  = "DAY"
    field = "point_time"
  }

  deletion_protection = false

  labels = var.labels
}
