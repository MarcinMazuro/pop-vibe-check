# Bluesky collector image.
#
# Build context MUST be the repository root (not collectors/bluesky/) so the
# shared collectors.common package is available to
# `python -m collectors.bluesky.main`:
#
#   docker build -f collectors/bluesky/Dockerfile -t bluesky-collector .
#
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY collectors/bluesky/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Only the packages this collector needs (common + bluesky + config).
COPY collectors/__init__.py ./collectors/__init__.py
COPY collectors/common/ ./collectors/common/
COPY collectors/config/ ./collectors/config/
COPY collectors/bluesky/ ./collectors/bluesky/

ENTRYPOINT ["python", "-m", "collectors.bluesky.main"]
