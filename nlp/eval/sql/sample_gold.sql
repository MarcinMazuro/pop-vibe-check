-- Gold-set candidates from raw_staging (YouTube first; Reddit when collected).
-- Target ~300 rows, stratified by source and language, preferring English
-- but keeping a slice of FR (and any ZH/RU/KO) so the eval report can
-- show the English DistilBERT limit.
--
-- Substitute PROJECT.DATASET. Run from the repo root:
--   bq query --use_legacy_sql=false < nlp/eval/sql/sample_gold.sql

DECLARE sample_size INT64 DEFAULT 300;

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
LIMIT 300;
