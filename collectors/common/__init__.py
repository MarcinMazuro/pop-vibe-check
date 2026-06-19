"""Shared utilities imported by both collectors.

Exposes author hashing, the GCS writer, the event-config loader, the retry
helper, and the record builder so callers can import them directly from
``collectors.common``.
"""

from __future__ import annotations

from collectors.common.author_hash import hash_author
from collectors.common.events_config import Event, load_events, resolve_event
from collectors.common.gcs_writer import write_batch
from collectors.common.records import build_record
from collectors.common.retry import retry_transient

__all__ = [
    "Event",
    "build_record",
    "hash_author",
    "load_events",
    "resolve_event",
    "retry_transient",
    "write_batch",
]
