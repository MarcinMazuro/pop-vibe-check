#!/usr/bin/env bash
#
# Launch the streaming sentiment pipeline from the built Flex Template.
#
# Every infrastructure value comes from `terraform output` rather than
# being hardcoded here, so this script cannot drift from what is deployed.
#
# COST WARNING. A streaming Dataflow job runs and bills continuously until
# it is drained — it is the most expensive resource in this project. This
# script asks for confirmation before launching; pass --yes to skip that
# in automation. To stop a job:
#
#   gcloud dataflow jobs drain JOB_ID --region=REGION
#
# Drain (not cancel) lets in-flight records finish and reach BigQuery.
#
# Usage:
#   dataflow/launch.sh [--yes] [--model NAME] [--env-dir DIR]

set -euo pipefail

ENV_DIR="terraform/envs/dev"
NLP_MODEL="stub"
ASSUME_YES="false"

# Cost guards. Small and few by default: this pipeline processes a paced
# replay of a few thousand records, not a firehose.
MAX_WORKERS="${MAX_WORKERS:-2}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-standard-2}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) ASSUME_YES="true"; shift ;;
    --model) NLP_MODEL="$2"; shift 2 ;;
    --env-dir) ENV_DIR="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -d "${ENV_DIR}" ]]; then
  echo "Environment directory '${ENV_DIR}' not found. Run from the repo root." >&2
  exit 1
fi

tf_output() {
  terraform -chdir="${ENV_DIR}" output -raw "$1"
}

REGION="$(tf_output dataflow_region)"
WORKER_SA="$(tf_output dataflow_worker_sa_email)"
SUBNETWORK="$(tf_output dataflow_subnetwork)"
TEMP_LOCATION="$(tf_output dataflow_temp_location)"
STAGING_LOCATION="$(tf_output dataflow_staging_location)"
SPEC_DIR="$(tf_output dataflow_template_spec_dir)"
INPUT_SUBSCRIPTION="$(tf_output dataflow_input_subscription)"
OUTPUT_TABLE="$(tf_output dataflow_events_landing_table)"
DLQ_TOPIC="$(tf_output dataflow_dlq_topic)"

TEMPLATE_SPEC="${SPEC_DIR}/sentiment-pipeline.json"
JOB_NAME="co-sentiment-$(date -u +%Y%m%d-%H%M%S)"

# The image the workers run. Read back out of the template spec so the
# harness is byte-identical to the launcher — the whole point of building
# one image for both roles.
SDK_IMAGE="$(gcloud storage cat "${TEMPLATE_SPEC}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["image"])')"

cat <<SUMMARY
About to launch a STREAMING Dataflow job. It bills until drained.

  job name      ${JOB_NAME}
  region        ${REGION}
  template      ${TEMPLATE_SPEC}
  sdk image     ${SDK_IMAGE}
  worker SA     ${WORKER_SA}
  max workers   ${MAX_WORKERS} x ${MACHINE_TYPE}
  subscription  ${INPUT_SUBSCRIPTION}
  write target  ${OUTPUT_TABLE}
  dead letters  ${DLQ_TOPIC}
  model         ${NLP_MODEL}

SUMMARY

if [[ "${ASSUME_YES}" != "true" ]]; then
  read -r -p "Launch? [y/N] " reply
  [[ "${reply}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
fi

# --disable-public-ips is not optional: it is what keeps workers off the
# public internet, and the image is built self-contained to suit it.
# --enable-streaming-engine is a cost decision — without it each streaming
# worker provisions a 400 GB persistent disk instead of 30 GB.
gcloud dataflow flex-template run "${JOB_NAME}" \
  --template-file-gcs-location="${TEMPLATE_SPEC}" \
  --region="${REGION}" \
  --service-account-email="${WORKER_SA}" \
  --subnetwork="${SUBNETWORK}" \
  --temp-location="${TEMP_LOCATION}" \
  --staging-location="${STAGING_LOCATION}" \
  --disable-public-ips \
  --enable-streaming-engine \
  --max-workers="${MAX_WORKERS}" \
  --worker-machine-type="${MACHINE_TYPE}" \
  --parameters="input_subscription=${INPUT_SUBSCRIPTION}" \
  --parameters="output_table=${OUTPUT_TABLE}" \
  --parameters="dlq_topic=${DLQ_TOPIC}" \
  --parameters="nlp_model=${NLP_MODEL}" \
  --parameters="sdk_container_image=${SDK_IMAGE}"

cat <<NEXT

Launched ${JOB_NAME}.

Watch it:
  gcloud dataflow jobs list --region=${REGION} --status=active

Stop it (drain, so in-flight records still land in BigQuery):
  gcloud dataflow jobs drain \$(gcloud dataflow jobs list \\
    --region=${REGION} --status=active --format='value(JOB_ID)' \\
    --filter="name=${JOB_NAME}") --region=${REGION}
NEXT
