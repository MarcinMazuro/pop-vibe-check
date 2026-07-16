"""Shared utilities imported by both collectors.

Exposes author hashing, the GCS writer, the event-config loader, the retry
helper, and the record builder so callers can import them directly from
``collectors.common``.

``write_batch`` and ``retry_transient`` are exported lazily (PEP 562):
their modules pull in google-cloud-storage and tenacity, which the replay
publisher image deliberately does not ship. Importing this package must
therefore not import them eagerly — the publisher only needs the
event-config loader.
"""

from __future__ import annotations

from typing import Any

from collectors.common.author_hash import hash_author
from collectors.common.events_config import Event, load_events, resolve_event
from collectors.common.records import build_record

__all__ = [
    "Event",
    "build_record",
    "hash_author",
    "load_events",
    "resolve_event",
    "retry_transient",
    "write_batch",
]

_LAZY_EXPORTS = ("retry_transient", "write_batch")


def __getattr__(name: str) -> Any:
    """Resolve the lazy exports on first access.

    Args:
        name: Attribute being looked up on the package.

    Returns:
        The lazily imported callable.

    Raises:
        AttributeError: If ``name`` is not a known export.
    """
    if name == "write_batch":
        from collectors.common.gcs_writer import write_batch

        return write_batch
    if name == "retry_transient":
        from collectors.common.retry import retry_transient

        return retry_transient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
