# YouTube collector image.
#
# Build context MUST be the repository root (not collectors/youtube/) so the
# shared collectors.common package is available to `python -m collectors.youtube.main`:
#
#   docker build -f collectors/youtube/Dockerfile -t youtube-collector .
#
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY collectors/youtube/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Only the packages this collector needs (common + youtube + config).
COPY collectors/__init__.py ./collectors/__init__.py
COPY collectors/common/ ./collectors/common/
COPY collectors/config/ ./collectors/config/
COPY collectors/youtube/ ./collectors/youtube/

ENTRYPOINT ["python", "-m", "collectors.youtube.main"]
