-- Throughput of past replays (E0): one run = processing with no gap > 10 min.
-- Reads ~17 MB. Results in docs/performance-plan.md.
WITH gaps AS (
  SELECT model_version, processed_at,
    IF(TIMESTAMP_DIFF(processed_at,
         LAG(processed_at) OVER (PARTITION BY model_version ORDER BY processed_at),
         MINUTE) > 10, 1, 0) AS new_run
  FROM `pop-vibe-check.co_analytics_dev.events_landing`),
runs AS (
  SELECT model_version, processed_at,
    SUM(new_run) OVER (PARTITION BY model_version ORDER BY processed_at) AS run_id
  FROM gaps),
per_min AS (
  SELECT model_version, run_id, TIMESTAMP_TRUNC(processed_at, MINUTE) AS m, COUNT(*) AS n
  FROM runs GROUP BY 1, 2, 3)
SELECT model_version, run_id, MIN(m) AS start_min, SUM(n) AS rows_total,
  COUNT(*) AS active_minutes,
  ROUND(SUM(n) / COUNT(*) / 60, 1) AS avg_rows_per_s,
  ROUND(APPROX_QUANTILES(n, 100)[OFFSET(50)] / 60, 1) AS p50_rows_per_s,
  ROUND(MAX(n) / 60, 1) AS peak_rows_per_s
FROM per_min GROUP BY 1, 2 HAVING rows_total > 500 ORDER BY start_min;
