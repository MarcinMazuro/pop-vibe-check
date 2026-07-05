"""Builder for the shared collector record schema.

Both collectors emit the same denormalised record shape. This module centralises
record construction so the schema stays consistent, timestamps are uniform ISO
8601 UTC, and the GDPR boundary holds: callers pass an already-computed
``author_hash``, never a raw handle.

The NLP fields (``sentiment_label``, ``sentiment_score``, ``model_version``) are
intentionally absent; they are populated by the Phase 1 Dataflow stage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

try:
    from langdetect import LangDetectException, detect
except ImportError:  # pragma: no cover - langdetect is an optional dependency.
    detect = None
    LangDetectException = Exception


def _epoch_to_iso_utc(epoch_seconds: float) -> str:
    """Convert a Unix epoch timestamp to an ISO 8601 UTC string.

    Args:
        epoch_seconds: Seconds since the Unix epoch (UTC).

    Returns:
        An ISO 8601 string with a trailing ``Z``, e.g. ``2025-04-24T12:34:56Z``.
    """
    moment = datetime.fromtimestamp(epoch_seconds, tz=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_iso_utc() -> str:
    """Return the current time as an ISO 8601 UTC string.

    Returns:
        The current UTC time formatted with a trailing ``Z``.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def detect_language(text: str) -> str | None:
    """Detect the language of a text, returning ``None`` on failure.

    Language detection is best-effort; the Phase 1 Dataflow stage may refine or
    fill it in. Any detection error yields ``None`` rather than raising.

    Args:
        text: The text to inspect.

    Returns:
        A two-letter language code (e.g. ``"en"``) or ``None`` when detection is
        unavailable or fails.
    """
    if detect is None or not text or not text.strip():
        return None
    try:
        return str(detect(text))
    except LangDetectException:
        return None


def build_record(
    *,
    record_id: str,
    source: str,
    author_hash: str,
    text: str,
    score: int,
    context_id: str,
    event_tag: str,
    created_utc_epoch: float,
    parent_id: str | None = None,
    language: str | None = None,
    detect_lang: bool = True,
) -> dict[str, Any]:
    """Build one collector record following the shared schema.

    Args:
        record_id: Source-prefixed unique id, e.g. ``"reddit:t3_abc123"`` or
            ``"youtube:Ugxabc123"``.
        source: Literal source name, ``"reddit"`` or ``"youtube"``.
        author_hash: Pre-computed 16-char author hash. Raw handles must never be
            passed here.
        text: The post body/title or comment body.
        score: Upvotes (Reddit) or like count (YouTube).
        context_id: Subreddit name (without ``r/``) or YouTube video id.
        event_tag: The ``EVENT_ID`` this run targets.
        created_utc_epoch: Author-side creation time as a Unix epoch in seconds.
        parent_id: Parent id for replies, or ``None`` for top-level items/posts.
        language: Explicit language code. When ``None`` and ``detect_lang`` is
            true, detection is attempted.
        detect_lang: Whether to attempt automatic language detection when
            ``language`` is not provided.

    Returns:
        A dict matching the collector record schema, ready to serialise.
    """
    resolved_language = language
    if resolved_language is None and detect_lang:
        resolved_language = detect_language(text)

    return {
        "id": record_id,
        "source": source,
        "parent_id": parent_id,
        "created_utc": _epoch_to_iso_utc(created_utc_epoch),
        "collected_at": _now_iso_utc(),
        "author_hash": author_hash,
        "text": text,
        "language": resolved_language,
        "score": int(score),
        "context_id": context_id,
        "event_tag": event_tag,
    }
