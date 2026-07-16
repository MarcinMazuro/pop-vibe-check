# Replay publisher image.
#
# Build context MUST be the repository root (not publisher/) so the shared
# collectors.common package is available to `python -m publisher.main`:
#
#   docker build -f publisher/Dockerfile -t publisher .
#
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY publisher/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Only what the publisher needs: the events config loader from
# collectors.common (imported as a submodule so the collector-only
# dependencies never enter this image) plus the config files.
COPY collectors/__init__.py ./collectors/__init__.py
COPY collectors/common/ ./collectors/common/
COPY collectors/config/ ./collectors/config/
COPY publisher/ ./publisher/

ENTRYPOINT ["python", "-m", "publisher.main"]
