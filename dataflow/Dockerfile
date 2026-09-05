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
# services over Private Google Access only, so there is no PyPI to install
# from. A worker that tries hangs until it times out.
#
# The same constraint applies to model weights. When a real model replaces
# the stub, its files are COPYed in below, never downloaded at runtime.
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

# The pipeline and the models it loads. Only these two packages — the
# collectors and the publisher are not part of this image.
COPY dataflow/ ./dataflow/
COPY nlp/ ./nlp/

# Tests are for CI, not for the runtime image.
RUN rm -rf ./dataflow/tests ./nlp/tests

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
