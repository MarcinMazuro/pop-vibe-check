-- Real-world arrival rate per source: peak records per minute and per hour.
WITH per_min AS (
  SELECT source, TIMESTAMP_TRUNC(created_utc, MINUTE) AS m, COUNT(*) AS n
  FROM `pop-vibe-check.co_analytics_dev.raw_staging` GROUP BY 1, 2),
per_hour AS (
  SELECT source, TIMESTAMP_TRUNC(created_utc, HOUR) AS h, COUNT(*) AS n
  FROM `pop-vibe-check.co_analytics_dev.raw_staging` GROUP BY 1, 2)
SELECT p.source, SUM(p.n) AS records,
  MAX(p.n) AS peak_per_minute,
  (SELECT MAX(n) FROM per_hour WHERE source = p.source) AS peak_per_hour
FROM per_min p GROUP BY p.source;
