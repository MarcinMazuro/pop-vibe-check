#!/usr/bin/env bash
#
# Promote a drained replay from events_landing into events.
#
# Order of operations, and why it matters:
#
#   1. coverage check  -- has every staged record actually landed?
#   2. MERGE           -- one row per id, freshest processed_at wins
#   3. fingerprint     -- the reproducibility check
#
# Step 1 exists because the publisher finishing does NOT mean the replay
# has been processed. Pub/Sub delivery and Beam's lag trail the publisher
# by seconds to minutes; promoting too early silently truncates the tail
# of the run. Run this only once the pipeline has drained.
#
# The fingerprint in step 3 is the number to record when demonstrating
# that the same replay twice produces the same rows: it hashes every
# column except model_version and processed_at, which differ per run by
# construction.
#
# Usage:
#   dataflow/promote.sh [--yes] [--check-only] [--env-dir DIR]

set -euo pipefail

ENV_DIR="terraform/envs/dev"
ASSUME_YES="false"
CHECK_ONLY="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) ASSUME_YES="true"; shift ;;
    --check-only) CHECK_ONLY="true"; shift ;;
    --env-dir) ENV_DIR="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -d "${ENV_DIR}" ]]; then
  echo "Environment directory '${ENV_DIR}' not found. Run from the repo root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

tf_output() {
  terraform -chdir="${ENV_DIR}" output -raw "$1"
}

PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
DATASET="$(tf_output analytics_dataset_id)"
RAW_STAGING_TABLE="${PROJECT_ID}.${DATASET}.$(tf_output raw_staging_table_id)"
EVENTS_LANDING_TABLE="${PROJECT_ID}.${DATASET}.$(tf_output events_landing_table_id)"
EVENTS_TABLE="${PROJECT_ID}.${DATASET}.$(tf_output events_table_id)"

export RAW_STAGING_TABLE EVENTS_LANDING_TABLE EVENTS_TABLE

run_sql() {
  # envsubst keeps the SQL files readable and runnable on their own; the
  # only substitutions are table references, never values (those would be
  # query parameters).
  local file="$1"
  envsubst < "${SCRIPT_DIR}/${file}" \
    | bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --format=pretty
}

echo "== Coverage: staged vs landed =="
run_sql coverage.sql

if [[ "${CHECK_ONLY}" == "true" ]]; then
  echo
  echo "Check-only run; nothing promoted."
  exit 0
fi

echo
echo "Promoting ${EVENTS_LANDING_TABLE} -> ${EVENTS_TABLE}."
echo "If 'missing_ids' above is non-zero the replay has not fully drained."

if [[ "${ASSUME_YES}" != "true" ]]; then
  read -r -p "Promote now? [y/N] " reply
  [[ "${reply}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
fi

echo
echo "== MERGE =="
run_sql promote.sql

echo
echo "== Fingerprint (compare across replays) =="
run_sql verify.sql
