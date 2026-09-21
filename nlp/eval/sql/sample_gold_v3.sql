-- Gold-v3 candidate pool from raw_staging (companion to sample_gold.sql).
-- Target ~1200 rows for local Cursor pre-labelling (prelabel_chunks.py split).
--
-- Exclude ids already labelled in nlp/eval/artifacts/gold.jsonl. Either
-- filter client-side after export, or bind those ids and uncomment
--   AND id NOT IN UNNEST(@gold_ids)
-- below. Do not use this file in place of the 300-row sample_gold.sql query.
--
-- Substitute PROJECT.DATASET. Run from the repo root:
--   bq query --use_legacy_sql=false < nlp/eval/sql/sample_gold_v3.sql

DECLARE sample_size INT64 DEFAULT 1200;

WITH usable AS (
  SELECT
    id,
    source,
    language,
    event_tag,
    created_utc,
    text
  FROM `pop-vibe-check.co_analytics_dev.raw_staging`
  WHERE text IS NOT NULL
    AND LENGTH(TRIM(text)) >= 8
    -- AND id NOT IN UNNEST(@gold_ids)
),
ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY source, IFNULL(language, "und")
      ORDER BY FARM_FINGERPRINT(id)
    ) AS rn,
    COUNT(*) OVER (PARTITION BY source, IFNULL(language, "und")) AS stratum_n
  FROM usable
)
SELECT
  id,
  source,
  language,
  event_tag,
  created_utc,
  text,
  CAST(NULL AS STRING) AS label,
  CAST(NULL AS STRING) AS split
FROM ranked
WHERE rn <= GREATEST(1, DIV(sample_size, (
  SELECT COUNT(DISTINCT CONCAT(source, "|", IFNULL(language, "und"))) FROM usable
)))
ORDER BY source, language, id
LIMIT 1200;
