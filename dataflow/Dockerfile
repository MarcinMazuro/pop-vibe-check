# Flex Template image for the streaming sentiment pipeline.
#
# Build context MUST be the repository root (not dataflow/) so the nlp
# package is available alongside the pipeline:
#
#   docker build -f dataflow/Dockerfile -t sentiment-pipeline .
#
# ---------------------------------------------------------------------------
# One image, two roles
# ---------------------------------------------------------------------------
# This image is used both as the Flex Template *launcher* and as the Beam
# SDK *worker harness* (passed to the launch as --sdk_container_image).
# Building on the Beam SDK base and copying the template launcher binary
# in is what makes that possible.
#
# The alternative — a launcher-only image plus the stock SDK image — would
# make the workers install this pipeline's dependencies at start-up. That
# cannot work here: workers run with --disable-public-ips and reach Google
# APIs over Private Google Access only, so there is no PyPI to install
# from. A worker that tries hangs until it times out.
#
# The same constraint applies to Hugging Face / torch weights. DistilBERT
# is served from a Vertex AI Endpoint (aiplatform.googleapis.com is a
# Google API, so PGA is enough). This image does not COPY checkpoints and
# does not install torch.
# ---------------------------------------------------------------------------

FROM gcr.io/dataflow-templates-base/python312-template-launcher-base:20260901-rc00 AS launcher

FROM docker.io/apache/beam_python3.12_sdk:2.76.0

ARG WORKDIR=/dataflow/template
WORKDIR ${WORKDIR}

# The Flex Template launcher binary, taken from the launcher base image.
COPY --from=launcher /opt/google/dataflow/python_template_launcher \
     /opt/google/dataflow/python_template_launcher

# Dependencies first, so edits to the pipeline do not invalidate the
# (much slower) install layer.
COPY dataflow/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# The pipeline and the models it loads. Training notebooks, eval gold, and
# MLflow helpers are not part of the runtime image — workers only need
# the classifier contract, the stub, and the Vertex Endpoint client.
COPY dataflow/ ./dataflow/
COPY nlp/ ./nlp/

# Tests and Workbench-only trees are for CI / training, not the harness.
RUN rm -rf ./dataflow/tests ./nlp/tests ./nlp/notebooks ./nlp/training ./nlp/eval ./nlp/tracking

ENV FLEX_TEMPLATE_PYTHON_PY_FILE="${WORKDIR}/dataflow/pipeline.py" \
    PYTHONPATH="${WORKDIR}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Deliberately no FLEX_TEMPLATE_PYTHON_REQUIREMENTS_FILE: setting it makes
# the launcher run pip at launch time, which is exactly the runtime fetch
# this image exists to avoid. Everything is installed above.

# Fail the build rather than a launch if the image cannot import its own
# pipeline — a missing dependency is far cheaper to find here.
RUN python -c "import dataflow.pipeline, nlp; print('pipeline imports OK')"

# The Beam SDK boot entrypoint. Dataflow overrides it when this image runs
# in the launcher role.
ENTRYPOINT ["/opt/apache/beam/boot"]
