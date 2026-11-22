-- Bootstrap for the perf tables, used once before terraform/modules/bigquery/perf.tf
-- was applied (so experiments could start before the PR merged). Schemas,
-- modes, partitioning and clustering mirror perf.tf exactly; once the PR
-- merges, import these tables into the Terraform state instead of applying
-- over them (see perf/README.md, "Tables created before Terraform").
--
-- Labels say managed_by=manual until the import; Terraform then sets its own.

CREATE TABLE IF NOT EXISTS `pop-vibe-check.co_analytics_dev.raw_staging_perf`
LIKE `pop-vibe-check.co_analytics_dev.raw_staging`
OPTIONS (
  description = "Load-test input: amplified copies of raw_staging written by perf/amplify.py. Never read by real replays.",
  labels = [("env", "dev"), ("managed_by", "manual"), ("owner", "team-198019-198265-198223"), ("project", "pop-vibe-check")]
);

CREATE TABLE IF NOT EXISTS `pop-vibe-check.co_analytics_dev.events_landing_perf`
LIKE `pop-vibe-check.co_analytics_dev.events_landing`
OPTIONS (
  description = "Load-test output: the pipeline's write target during perf experiments. Never promoted into events.",
  labels = [("env", "dev"), ("managed_by", "manual"), ("owner", "team-198019-198265-198223"), ("project", "pop-vibe-check")]
);

CREATE TABLE IF NOT EXISTS `pop-vibe-check.co_analytics_dev.perf_runs` (
  run_id STRING NOT NULL OPTIONS (description = "Experiment run id, e.g. 'e1-w2-s2000'."),
  experiment STRING NOT NULL OPTIONS (description = "Experiment id from docs/performance-plan.md (e1 … e6)."),
  build_id STRING OPTIONS (description = "Cloud Build id of the replay build that ran it."),
  job_id STRING OPTIONS (description = "Dataflow job id."),
  job_name STRING OPTIONS (description = "Dataflow job name."),
  git_commit STRING OPTIONS (description = "Commit of the code that ran (HEAD of the submitted source)."),
  started_at TIMESTAMP OPTIONS (description = "Dataflow job creation time."),
  finished_at TIMESTAMP OPTIONS (description = "Dataflow job final state time."),
  model STRING OPTIONS (description = "Classifier: stub or vertex."),
  speedup FLOAT64 OPTIONS (description = "Publisher time-compression factor."),
  max_workers INT64 OPTIONS (description = "Dataflow max workers."),
  machine_type STRING OPTIONS (description = "Dataflow worker machine type."),
  max_batch_size INT64 OPTIONS (description = "Records per classifier call; null = template default."),
  endpoint_replicas INT64 OPTIONS (description = "Vertex replicas deployed during the run (recorded by hand for vertex runs)."),
  staging_table STRING OPTIONS (description = "Staging table the publisher replayed."),
  copies INT64 OPTIONS (description = "Amplification factor of the staging table (1 = real data)."),
  records_expected INT64 OPTIONS (description = "Distinct ids in the staging table replayed."),
  records_landed INT64 OPTIONS (description = "Rows the job wrote to events_landing_perf."),
  distinct_ids_landed INT64 OPTIONS (description = "Distinct ids the job wrote."),
  active_minutes INT64 OPTIONS (description = "Minutes with at least one row written."),
  mean_rps FLOAT64 OPTIONS (description = "Mean records per second over active minutes."),
  p50_rps FLOAT64 OPTIONS (description = "Median of per-minute records per second."),
  peak_rps FLOAT64 OPTIONS (description = "Highest per-minute records per second."),
  job_metrics ARRAY<STRUCT<name STRING NOT NULL, value FLOAT64>> OPTIONS (description = "Dataflow service metrics at the end of the job (vCPU time, memory, disk, Streaming Engine data …)."),
  estimated_cost_usd FLOAT64 OPTIONS (description = "Cost estimated from resource usage and perf/prices.yaml; null if prices are not filled in."),
  notes STRING OPTIONS (description = "Free-text notes for the run."),
  collected_at TIMESTAMP NOT NULL OPTIONS (description = "When perf/collect.py wrote the row.")
)
OPTIONS (
  description = "Performance experiment results, one row per run. Written by perf/collect.py.",
  labels = [("env", "dev"), ("managed_by", "manual"), ("owner", "team-198019-198265-198223"), ("project", "pop-vibe-check")]
);

CREATE TABLE IF NOT EXISTS `pop-vibe-check.co_analytics_dev.perf_timeseries` (
  run_id STRING NOT NULL OPTIONS (description = "Experiment run id (perf_runs.run_id)."),
  metric_type STRING NOT NULL OPTIONS (description = "Cloud Monitoring metric type."),
  resource_labels STRING OPTIONS (description = "Monitored resource labels as JSON."),
  point_time TIMESTAMP NOT NULL OPTIONS (description = "End time of the sample interval."),
  value FLOAT64 OPTIONS (description = "Sample value (mean for distributions).")
)
PARTITION BY DATE(point_time)
OPTIONS (
  description = "Cloud Monitoring time series per performance experiment run. Written by perf/collect.py.",
  labels = [("env", "dev"), ("managed_by", "manual"), ("owner", "team-198019-198265-198223"), ("project", "pop-vibe-check")]
);
