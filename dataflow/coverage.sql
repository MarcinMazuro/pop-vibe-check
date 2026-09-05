-- Did every staged record make it through the pipeline?
--
-- Run before promoting. The publisher finishing means "all published",
-- not "all processed": Pub/Sub delivery and Beam's own lag trail the
-- publisher by seconds to minutes, so promoting too early silently
-- truncates the tail of a replay. When landed equals staged, the replay
-- has fully drained.
--
-- Placeholders are substituted by dataflow/promote.sh from terraform
-- output.
SELECT
  (SELECT COUNT(DISTINCT id) FROM `${RAW_STAGING_TABLE}`)   AS staged_ids,
  (SELECT COUNT(DISTINCT id) FROM `${EVENTS_LANDING_TABLE}`) AS landed_ids,
  (SELECT COUNT(*) FROM `${EVENTS_LANDING_TABLE}`)           AS landed_rows,
  (SELECT COUNT(DISTINCT id) FROM `${RAW_STAGING_TABLE}`)
    - (SELECT COUNT(DISTINCT id) FROM `${EVENTS_LANDING_TABLE}`) AS missing_ids
