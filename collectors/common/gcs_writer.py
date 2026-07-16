"""Serialise records to gzipped JSONL and upload them to the raw archive bucket.

The writer is the single egress point to GCS for both collectors. It enforces
the immutable-raw-archive path convention and guarantees one valid JSON object
per line, gzipped, with a per-invocation-unique object name so concurrent runs
never collide.
"""

from __future__ import annotations

import gzip
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

# Module-style import: google-cloud-storage ships no py.typed marker, so
# the `from google.cloud import storage` form trips mypy's attr-defined
# check once any typed google.cloud package (e.g. bigquery) is installed.
import google.cloud.storage as storage

_BUCKET_ENV_VAR = "TARGET_BUCKET"


def _resolve_bucket(bucket: str | None) -> str:
    """Return the target bucket name from the argument or environment.

    Args:
        bucket: Explicit bucket name, or ``None`` to read ``TARGET_BUCKET``.

    Returns:
        The resolved bucket name.

    Raises:
        ValueError: If no bucket is supplied and ``TARGET_BUCKET`` is unset.
    """
    resolved = bucket if bucket is not None else os.environ.get(_BUCKET_ENV_VAR)
    if not resolved:
        raise ValueError(f"No bucket provided and {_BUCKET_ENV_VAR} is unset or empty.")
    return resolved


def build_object_path(source: str, event_id: str, batch_id: str) -> str:
    """Build the partitioned object path for a batch.

    The layout is ``{source}/{event_id}/{YYYY}/{MM}/{DD}/{HH}/{batch_id}.jsonl.gz``
    using the current UTC time, matching the raw-archive convention.

    Args:
        source: Data source, e.g. ``"reddit"`` or ``"youtube"``.
        event_id: Lifecycle event id (or ``"general"`` when not event-scoped).
        batch_id: Unique id for this batch (typically a UUID4 hex string).

    Returns:
        The object path relative to the bucket root (no leading slash).
    """
    now = datetime.now(UTC)
    return (
        f"{source}/{event_id}/"
        f"{now:%Y}/{now:%m}/{now:%d}/{now:%H}/"
        f"{batch_id}.jsonl.gz"
    )


def serialise_jsonl_gz(records: list[dict[str, Any]]) -> bytes:
    """Serialise records to gzipped JSON Lines.

    Each record is written as a single compact JSON object on its own line
    (no pretty-printing, no trailing comma), then the whole payload is gzipped.

    Args:
        records: The records to serialise.

    Returns:
        The gzip-compressed JSONL payload as bytes.
    """
    lines = (
        json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        for record in records
    )
    payload = "\n".join(lines).encode("utf-8")
    return gzip.compress(payload)


def write_batch(
    records: list[dict[str, Any]],
    source: str,
    event_id: str,
    *,
    bucket: str | None = None,
    client: storage.Client | None = None,
) -> str:
    """Serialise a batch and upload it to the raw archive bucket.

    Args:
        records: Records to write. An empty list is a no-op that still returns
            the (unused) target path for logging symmetry.
        source: Data source, e.g. ``"reddit"`` or ``"youtube"``.
        event_id: Lifecycle event id used as the path segment.
        bucket: Target bucket name. Defaults to the ``TARGET_BUCKET`` env var.
        client: Optional pre-built storage client (useful for testing). A
            default client is created when omitted.

    Returns:
        The full ``gs://`` URI of the uploaded object.

    Raises:
        ValueError: If the bucket cannot be resolved.
    """
    bucket_name = _resolve_bucket(bucket)
    batch_id = uuid.uuid4().hex
    object_path = build_object_path(source, event_id, batch_id)
    gs_uri = f"gs://{bucket_name}/{object_path}"

    if not records:
        return gs_uri

    payload = serialise_jsonl_gz(records)
    storage_client = client if client is not None else storage.Client()
    blob = storage_client.bucket(bucket_name).blob(object_path)
    blob.upload_from_string(payload, content_type="application/gzip")
    return gs_uri
