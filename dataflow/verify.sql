-- Reproducibility fingerprint of the events table.
--
-- The project's guarantee is that replaying the same data twice yields an
-- identical set of rows in events, "modulo model_version and
-- processed_at". Those two columns differ between runs by construction —
-- processed_at is wall-clock, and model_version changes when the model
-- does — so the fingerprint below excludes them and hashes everything
-- else. Two replays of the same staged data must produce the same
-- row_count and the same fingerprint.
--
-- SUM over per-row hashes is deliberate: it is order-independent, so the
-- fingerprint compares the row *set* without depending on scan order. The
-- cast to NUMERIC is not cosmetic — FARM_FINGERPRINT returns a full-range
-- INT64, so summing a few thousand of them overflows a 64-bit accumulator
-- and the query fails outright.
--
-- Placeholders are substituted by dataflow/promote.sh from terraform
-- output.
SELECT
  COUNT(*)                                        AS row_count,
  COUNT(DISTINCT id)                              AS distinct_ids,
  COUNTIF(sentiment_label IS NULL)                AS missing_sentiment,
  SUM(
    CAST(
      FARM_FINGERPRINT(
        TO_JSON_STRING(
          (SELECT AS STRUCT e.* EXCEPT (model_version, processed_at))
        )
      ) AS NUMERIC
    )
  )                                               AS fingerprint
FROM `${EVENTS_TABLE}` AS e
