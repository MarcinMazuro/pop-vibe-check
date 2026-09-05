-- Promote events_landing -> events: one row per id, freshest processed_at wins.
--
-- The pipeline appends to events_landing and never writes events. This
-- statement is what makes events the analytical source of truth, and what
-- lets the pipeline be at-least-once: duplicate deliveries and repeated
-- passes over the same id collapse here.
--
-- processed_at is the tiebreaker, not collected_at: two replays over the
-- same staged data carry identical collected_at values and so cannot
-- distinguish a fresher pass.
--
-- Placeholders are substituted by dataflow/promote.sh from terraform
-- output; run that rather than editing this file.
MERGE `${EVENTS_TABLE}` AS t
USING (
  SELECT * EXCEPT (rn)
  FROM (
    SELECT
      *,
      ROW_NUMBER() OVER (PARTITION BY id ORDER BY processed_at DESC) AS rn
    FROM `${EVENTS_LANDING_TABLE}`
  )
  WHERE rn = 1
) AS s
ON t.id = s.id
WHEN MATCHED AND s.processed_at > t.processed_at THEN UPDATE SET
  source          = s.source,
  parent_id       = s.parent_id,
  created_utc     = s.created_utc,
  collected_at    = s.collected_at,
  author_hash     = s.author_hash,
  text            = s.text,
  language        = s.language,
  score           = s.score,
  context_id      = s.context_id,
  event_tag       = s.event_tag,
  sentiment_label = s.sentiment_label,
  sentiment_score = s.sentiment_score,
  model_version   = s.model_version,
  processed_at    = s.processed_at
WHEN NOT MATCHED THEN
  INSERT ROW
