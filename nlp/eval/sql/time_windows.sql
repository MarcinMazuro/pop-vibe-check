-- Sentiment aggregates around Clair Obscur: Expedition 33's worldwide
-- launch (collectors/config/events.yaml → launch / 2025-04-24).
--
-- Windows (half-open, UTC):
--   week_before  [launch - 7d, launch)
--   launch_day   [launch,      launch + 1d)
--   hours_48     [launch,      launch + 48h)
--   week_after   [launch,      launch + 7d)
--
-- Run after the promotion MERGE has populated `events`. Per-event_tag
-- slices use the collector tag, not the window — both are reported.
-- Substitute PROJECT.DATASET.

DECLARE launch_ts TIMESTAMP DEFAULT TIMESTAMP("2025-04-24 00:00:00 UTC");

WITH windows AS (
  SELECT "week_before" AS window_id, TIMESTAMP_SUB(launch_ts, INTERVAL 7 DAY) AS start_ts, launch_ts AS end_ts
  UNION ALL
  SELECT "launch_day", launch_ts, TIMESTAMP_ADD(launch_ts, INTERVAL 1 DAY)
  UNION ALL
  SELECT "hours_48", launch_ts, TIMESTAMP_ADD(launch_ts, INTERVAL 48 HOUR)
  UNION ALL
  SELECT "week_after", launch_ts, TIMESTAMP_ADD(launch_ts, INTERVAL 7 DAY)
),
labelled AS (
  SELECT
    w.window_id,
    e.event_tag,
    e.source,
    e.language,
    e.sentiment_label,
    e.sentiment_score,
    e.model_version
  FROM `pop-vibe-check.co_analytics_dev.events` AS e
  CROSS JOIN windows AS w
  WHERE e.created_utc >= w.start_ts
    AND e.created_utc < w.end_ts
)
SELECT
  window_id,
  event_tag,
  source,
  COUNT(*) AS n,
  COUNTIF(sentiment_label = "pos") AS n_pos,
  COUNTIF(sentiment_label = "neu") AS n_neu,
  COUNTIF(sentiment_label = "neg") AS n_neg,
  SAFE_DIVIDE(COUNTIF(sentiment_label = "pos"), COUNT(*)) AS share_pos,
  SAFE_DIVIDE(COUNTIF(sentiment_label = "neg"), COUNT(*)) AS share_neg,
  AVG(sentiment_score) AS avg_score,
  -- pos=1, neu=0, neg=-1 so a window mean is comparable to Metacritic/100.
  AVG(CASE sentiment_label
        WHEN "pos" THEN 1.0
        WHEN "neu" THEN 0.0
        WHEN "neg" THEN -1.0
      END) AS mean_polarity
FROM labelled
GROUP BY window_id, event_tag, source
ORDER BY window_id, event_tag, source;

-- Per-event_tag over the whole table (calendar of collectors/config/events.yaml).
-- Uncomment to run as a second statement in the bq CLI (or run separately):
--
-- SELECT
--   event_tag,
--   source,
--   COUNT(*) AS n,
--   SAFE_DIVIDE(COUNTIF(sentiment_label = "pos"), COUNT(*)) AS share_pos,
--   SAFE_DIVIDE(COUNTIF(sentiment_label = "neg"), COUNT(*)) AS share_neg,
--   AVG(CASE sentiment_label
--         WHEN "pos" THEN 1.0 WHEN "neu" THEN 0.0 WHEN "neg" THEN -1.0
--       END) AS mean_polarity
-- FROM `pop-vibe-check.co_analytics_dev.events`
-- GROUP BY event_tag, source
-- ORDER BY event_tag, source;
