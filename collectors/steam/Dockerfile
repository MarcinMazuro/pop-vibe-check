# Steam collector image.
#
# Build context MUST be the repository root (not collectors/steam/) so the
# shared collectors.common package is available to
# `python -m collectors.steam.main`:
#
#   docker build -f collectors/steam/Dockerfile -t steam-collector .
#
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY collectors/steam/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Only the packages this collector needs (common + steam + config).
COPY collectors/__init__.py ./collectors/__init__.py
COPY collectors/common/ ./collectors/common/
COPY collectors/config/ ./collectors/config/
COPY collectors/steam/ ./collectors/steam/

ENTRYPOINT ["python", "-m", "collectors.steam.main"]
