#!/usr/bin/env bash
#
# Collect the full Steam review history for one release, as a set of
# passes. This script *is* the definition of the dataset: the endpoint
# cannot serve the whole history in one walk, so what was collected is
# exactly the union of the streams listed here.
#
# Why passes at all
# -----------------
# Steam ends pagination of a result stream long before the data runs out.
# Measured on appid 1903340 (2026-10-12): an all-languages `recent` walk
# stopped by itself at page 1243 — 124,187 of 280,699 reviews — reaching
# only September 2025 for an April 2025 launch. Nothing failed; the next
# page was simply empty.
#
# A narrower stream has fewer reviews than the cap, so it reaches the
# launch. Review ids are stable, so passes may overlap: the raw archive
# keeps every copy and the landing -> staging MERGE keeps one row per id.
#
# The axes, measured 2026-10-14:
#
#   review_type=negative          13,409  (all languages, reaches launch)
#   language=english              140,654 (ABOVE the cap — must be split)
#     + purchase_type=steam       103,218 (fits)
#     + purchase_type=non_steam    37,411 (fits)
#   language=schinese              39,575
#   language=french                23,607
#   language=russian               17,160
#   language=spanish                9,971
#   language=german                 8,463
#   language=korean                 6,057
#   language=polish                 5,493
#   language=tchinese               4,695
#   language=turkish                1,781
#   language=japanese               1,225
#   language=portuguese               522
#
# What does NOT work, both checked: `day_range` is clamped to roughly 365
# days, so it cannot reach an 18-month-old launch; and `filter=updated`
# is a tiny stream (400 records before it ends), useful as a sample, not
# for volume.
#
# Usage:
#   collectors/steam/collect_history.sh [--job NAME] [--region REGION] \
#       [--window-from ISO] [--window-to ISO] [--dry-run]
#
# Each pass is one Cloud Run Job execution, run one at a time: the point
# of the pacing inside the collector is to be polite to an undocumented
# endpoint, and running passes in parallel would undo it.

set -euo pipefail

JOB="co-steam-collector-dev"
REGION="europe-central2"
WINDOW_FROM="2025-04-23T00:00:00Z"
WINDOW_TO="2026-12-31T00:00:00Z"
DRY_RUN="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --job) JOB="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --window-from) WINDOW_FROM="$2"; shift 2 ;;
    --window-to) WINDOW_TO="$2"; shift 2 ;;
    --dry-run) DRY_RUN="true"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

# One pass per line: "LANGUAGE REVIEW_TYPE PURCHASE_TYPE".
# Ordered cheapest first, so a failure early costs little and the long
# English passes run last.
PASSES=(
  "all negative all"
  "portuguese all all"
  "japanese all all"
  "turkish all all"
  "tchinese all all"
  "polish all all"
  "korean all all"
  "german all all"
  "spanish all all"
  "russian all all"
  "french all all"
  "schinese all all"
  "english all non_steam_purchase"
  "english all steam"
)

echo "Collecting Steam history into ${JOB} (${REGION})"
echo "Window: ${WINDOW_FROM} .. ${WINDOW_TO}"
echo "Passes: ${#PASSES[@]}"
echo

for pass in "${PASSES[@]}"; do
  read -r language review_type purchase_type <<< "$pass"
  label="language=${language} review_type=${review_type} purchase_type=${purchase_type}"
  echo "=== ${label}"

  # STEAM_RESUME=false: each pass is its own stream, so a checkpoint from
  # the previous pass must not be picked up. A pass that is interrupted
  # can be resumed by re-running it with STEAM_RESUME=true by hand.
  env_vars="EVENT_ID=auto"
  env_vars="${env_vars},WINDOW_FROM=${WINDOW_FROM},WINDOW_TO=${WINDOW_TO}"
  env_vars="${env_vars},STEAM_FILTER=recent,STEAM_RESUME=false"
  env_vars="${env_vars},STEAM_LANGUAGE=${language}"
  env_vars="${env_vars},STEAM_REVIEW_TYPE=${review_type}"
  env_vars="${env_vars},STEAM_PURCHASE_TYPE=${purchase_type}"

  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "    would run: gcloud run jobs execute ${JOB} --update-env-vars=${env_vars}"
    continue
  fi

  gcloud run jobs execute "${JOB}" --region="${REGION}" --wait \
    --update-env-vars="${env_vars}"
  echo "    done"
  echo
done

cat <<'NEXT'
All passes finished. The archive now holds the union of those streams;
duplicates across passes collapse in the landing -> staging MERGE.

Load it and check the coverage that actually resulted:

  gcloud run jobs execute co-publisher-dev --region=europe-central2 \
    --update-env-vars=RUN_LOAD=only --wait

  bq query --use_legacy_sql=false 'SELECT source, COUNT(*) records,
    MIN(DATE(created_utc)) oldest, MAX(DATE(created_utc)) newest
    FROM co_analytics_dev.raw_staging GROUP BY source'
NEXT
