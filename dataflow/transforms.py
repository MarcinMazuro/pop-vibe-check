"""Pure record-level logic for the streaming pipeline.

Deliberately free of any ``apache_beam`` import. Everything here is an
ordinary function over dicts, so the parsing, validation, language, and
row-building rules are unit-testable without a pipeline runner — and the
Beam layer in :mod:`dataflow.pipeline` stays thin enough to read in one
sitting.

The split between a *bad record* and a *bad classification* matters:
records that cannot be parsed or that lack the fields the events table
requires are dead-lettered, while a record that merely resists language
detection or sentiment analysis still lands in the table. Losing an
opinion because a model was unsure would silently bias the analysis.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from nlp.base import Sentiment

try:  # pragma: no cover - exercised implicitly wherever langdetect exists.
    from langdetect import DetectorFactory, LangDetectException
    from langdetect import detect as _detect
except ImportError:  # pragma: no cover - keeps the module importable bare.
    DetectorFactory = None
    _detect = None
    LangDetectException = Exception

# Columns of the events / events_landing tables, in schema order. The
# pipeline writes exactly these keys; anything else in an inbound record
# is dropped rather than passed through, so an upstream schema change
# cannot silently widen the write.
EVENT_COLUMNS: tuple[str, ...] = (
    "id",
    "source",
    "parent_id",
    "created_utc",
    "collected_at",
    "author_hash",
    "text",
    "language",
    "score",
    "context_id",
    "event_tag",
    "sentiment_label",
    "sentiment_score",
    "model_version",
    "processed_at",
)

# Fields the events table declares REQUIRED. A record missing either is
# unwritable, so it is dead-lettered rather than sent to BigQuery to fail.
REQUIRED_FIELDS: tuple[str, ...] = ("id", "created_utc")

# Cap on the text handed to language detection. Detection quality plateaus
# long before this; the cap bounds per-element cost on pathological input.
MAX_DETECT_CHARS = 1000


class RecordError(ValueError):
    """A message that cannot become an events row.

    Raised only for structural problems — malformed JSON, a non-object
    payload, a missing required field, an unparseable timestamp. Model
    uncertainty is never a :class:`RecordError`.
    """


def parse_message(data: bytes) -> dict[str, Any]:
    """Decode one Pub/Sub payload into a record dict.

    Args:
        data: Raw message bytes as published by the replay publisher —
            UTF-8 JSON of a single staging row.

    Returns:
        The decoded record.

    Raises:
        RecordError: If the bytes are not UTF-8, not valid JSON, or decode
            to something other than a JSON object.
    """
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RecordError(f"payload is not valid UTF-8: {exc}") from exc

    try:
        record = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise RecordError(f"payload is not valid JSON: {exc}") from exc

    if not isinstance(record, dict):
        raise RecordError(
            f"payload is a JSON {type(record).__name__}, expected object."
        )

    return record


def parse_timestamp(value: Any, field: str) -> datetime:
    """Parse a timestamp field into a timezone-aware UTC datetime.

    Accepts the ISO 8601 form the collectors and publisher emit (trailing
    ``Z``), any offset-bearing ISO string, and a naive string, which is
    read as UTC.

    Args:
        value: The raw field value.
        field: Field name, used in the error message.

    Returns:
        A timezone-aware :class:`datetime` in UTC.

    Raises:
        RecordError: If the value is absent or not a parseable timestamp.
    """
    if not isinstance(value, str) or not value:
        raise RecordError(
            f"{field} must be a non-empty ISO 8601 string, got {value!r}."
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecordError(f"{field} is not a parseable timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso_utc(moment: datetime) -> str:
    """Format a datetime as an ISO 8601 UTC string with a trailing ``Z``.

    Args:
        moment: The moment to format; naive values are read as UTC.

    Returns:
        A string such as ``2025-04-24T12:34:56Z``.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_record(record: dict[str, Any]) -> dict[str, Any]:
    """Check the fields the events table requires and normalise them.

    Args:
        record: A decoded record.

    Returns:
        The record with ``id`` coerced to ``str`` and ``created_utc``
        normalised to ISO 8601 UTC.

    Raises:
        RecordError: If a required field is missing, empty, or malformed.
    """
    for field in REQUIRED_FIELDS:
        if record.get(field) in (None, ""):
            raise RecordError(f"required field '{field}' is missing or empty.")

    normalised = dict(record)
    normalised["id"] = str(record["id"])
    normalised["created_utc"] = iso_utc(
        parse_timestamp(record["created_utc"], "created_utc")
    )
    return normalised


def detect_language(text: Any) -> str | None:
    """Detect the language of a text, returning ``None`` on failure.

    This is the authoritative language for the events table, superseding
    the collectors' advisory value. Detection failure is not an error:
    plenty of real comments are an emoji or a single word.

    Args:
        text: The record's text. Non-string values yield ``None``.

    Returns:
        A two-letter language code, or ``None`` when detection is
        unavailable or fails.
    """
    if _detect is None or not isinstance(text, str) or not text.strip():
        return None

    # Seed on every call, not once at import.
    #
    # langdetect samples n-grams randomly and seeds a fresh RNG per
    # detection from DetectorFactory.seed — a class attribute that
    # defaults to None, meaning "seed from system entropy". Setting it at
    # import time looks equivalent and is not: the first live run produced
    # different languages for 68 short comments across two replays of
    # identical data, because on the workers this module reached the
    # detector without that import-time assignment having taken effect.
    # Short text is exactly where the sampling matters — "Hell yeah!"
    # drifts between en, id and tr unseeded.
    #
    # Since `language` is authoritative in the events table and the
    # project guarantees a replay is reproducible, the seed cannot depend
    # on how the code was loaded. Setting it here costs an attribute
    # write and makes each call deterministic on its own.
    DetectorFactory.seed = 0
    try:
        return str(_detect(text[:MAX_DETECT_CHARS]))
    except LangDetectException:
        return None


def _as_int(value: Any) -> int | None:
    """Coerce a value to ``int``, or ``None`` when it is not numeric.

    Args:
        value: The raw field value.

    Returns:
        The integer value, or ``None``. Booleans yield ``None`` — a bool in
        a score column is upstream corruption, not a count.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    """Coerce a value to ``str``, preserving ``None``.

    Args:
        value: The raw field value.

    Returns:
        The string value, or ``None`` when the input is ``None``.
    """
    return None if value is None else str(value)


def build_event_row(
    record: dict[str, Any],
    sentiment: Sentiment,
    processed_at: datetime,
    language: str | None,
) -> dict[str, Any]:
    """Assemble one row for the events_landing table.

    Args:
        record: A record that has passed :func:`validate_record`.
        sentiment: The classification result.
        processed_at: Pipeline-side processing time — the tiebreaker the
            promotion MERGE uses to pick the freshest row per ``id``.
        language: Authoritative language code, or ``None``.

    Returns:
        A dict whose keys are exactly :data:`EVENT_COLUMNS`.
    """
    collected_at = record.get("collected_at")
    return {
        "id": str(record["id"]),
        "source": _as_str(record.get("source")),
        "parent_id": _as_str(record.get("parent_id")),
        "created_utc": str(record["created_utc"]),
        "collected_at": (
            iso_utc(parse_timestamp(collected_at, "collected_at"))
            if isinstance(collected_at, str) and collected_at
            else None
        ),
        "author_hash": _as_str(record.get("author_hash")),
        "text": _as_str(record.get("text")),
        "language": language,
        "score": _as_int(record.get("score")),
        "context_id": _as_str(record.get("context_id")),
        "event_tag": _as_str(record.get("event_tag")),
        "sentiment_label": sentiment.label,
        "sentiment_score": float(sentiment.score),
        "model_version": sentiment.model_version,
        "processed_at": iso_utc(processed_at),
    }


def build_dead_letter(
    data: bytes,
    attributes: dict[str, str] | None,
    error: str,
) -> tuple[bytes, dict[str, str]]:
    """Build the dead-letter message for a record the pipeline rejected.

    The original payload is republished unchanged so the DLQ subscription
    can be drained, fixed, and replayed. Diagnostics travel as attributes
    rather than being merged into the payload, which would corrupt the
    very bytes an operator needs to inspect. Payloads that are not valid
    UTF-8 are preserved verbatim, since that may be the defect itself.

    Args:
        data: The original message bytes.
        attributes: The original message attributes, if any.
        error: Human-readable reason the record was rejected.

    Returns:
        A ``(data, attributes)`` tuple ready to publish to the DLQ topic.
    """
    dlq_attributes = dict(attributes or {})
    dlq_attributes["dlq_error"] = error[:1024]
    dlq_attributes["dlq_at"] = iso_utc(datetime.now(UTC))
    return data, dlq_attributes
