# Reddit collector image.
#
# Build context MUST be the repository root (not collectors/reddit/) so the
# shared collectors.common package is available to `python -m collectors.reddit.main`:
#
#   docker build -f collectors/reddit/Dockerfile -t reddit-collector .
#
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY collectors/reddit/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Only the packages this collector needs (common + reddit + config).
COPY collectors/__init__.py ./collectors/__init__.py
COPY collectors/common/ ./collectors/common/
COPY collectors/config/ ./collectors/config/
COPY collectors/reddit/ ./collectors/reddit/

ENTRYPOINT ["python", "-m", "collectors.reddit.main"]
