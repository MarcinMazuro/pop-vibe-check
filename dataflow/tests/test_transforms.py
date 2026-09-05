import json
from datetime import UTC, datetime

import pytest
from nlp.base import Sentiment

from dataflow.transforms import (
    EVENT_COLUMNS,
    RecordError,
    build_dead_letter,
    build_event_row,
    detect_language,
    iso_utc,
    parse_message,
    parse_timestamp,
    validate_record,
)

VALID = {
    "id": "youtube:Ugx123",
    "source": "youtube",
    "parent_id": None,
    "created_utc": "2025-04-24T12:00:00Z",
    "collected_at": "2026-07-05T09:00:00Z",
    "author_hash": "0123456789abcdef",
    "text": "This game is a masterpiece",
    "language": "en",
    "score": 12,
    "context_id": "dQw4w9WgXcQ",
    "event_tag": "launch",
}


def _encode(record):
    return json.dumps(record).encode("utf-8")


class TestParseMessage:
    def test_parses_a_record(self):
        assert parse_message(_encode(VALID)) == VALID

    def test_rejects_malformed_json(self):
        with pytest.raises(RecordError, match="not valid JSON"):
            parse_message(b'{"id": ')

    def test_rejects_non_utf8(self):
        with pytest.raises(RecordError, match="not valid UTF-8"):
            parse_message(b"\xff\xfe\x00")

    @pytest.mark.parametrize("payload", [b"[1, 2]", b'"a string"', b"42", b"null"])
    def test_rejects_non_object_payloads(self, payload):
        with pytest.raises(RecordError, match="expected object"):
            parse_message(payload)

    def test_preserves_non_ascii_text(self):
        record = {**VALID, "text": "znakomita gra — bardzo dobra"}
        assert parse_message(_encode(record))["text"] == record["text"]


class TestParseTimestamp:
    def test_parses_trailing_z(self):
        assert parse_timestamp("2025-04-24T12:00:00Z", "created_utc") == datetime(
            2025, 4, 24, 12, 0, tzinfo=UTC
        )

    def test_parses_offset_and_normalises_to_utc(self):
        assert parse_timestamp("2025-04-24T14:00:00+02:00", "created_utc") == datetime(
            2025, 4, 24, 12, 0, tzinfo=UTC
        )

    def test_naive_is_read_as_utc(self):
        assert parse_timestamp("2025-04-24T12:00:00", "created_utc") == datetime(
            2025, 4, 24, 12, 0, tzinfo=UTC
        )

    @pytest.mark.parametrize("value", ["", None, 1745496000, "not-a-date", []])
    def test_rejects_unusable_values(self, value):
        with pytest.raises(RecordError):
            parse_timestamp(value, "created_utc")


class TestValidateRecord:
    def test_passes_a_valid_record(self):
        assert validate_record(VALID)["id"] == "youtube:Ugx123"

    def test_normalises_created_utc(self):
        record = validate_record({**VALID, "created_utc": "2025-04-24T14:00:00+02:00"})
        assert record["created_utc"] == "2025-04-24T12:00:00Z"

    def test_coerces_a_numeric_id_to_string(self):
        assert validate_record({**VALID, "id": 12345})["id"] == "12345"

    @pytest.mark.parametrize("field", ["id", "created_utc"])
    @pytest.mark.parametrize("bad", [None, ""])
    def test_rejects_missing_required_fields(self, field, bad):
        with pytest.raises(RecordError, match="required field"):
            validate_record({**VALID, field: bad})

    def test_does_not_mutate_the_input(self):
        record = dict(VALID)
        validate_record(record)
        assert record == VALID


class TestDetectLanguage:
    def test_detects_english(self):
        assert detect_language("This game is an absolute masterpiece, truly.") == "en"

    @pytest.mark.parametrize("value", ["", "   ", None, 42, []])
    def test_undetectable_input_yields_none(self, value):
        assert detect_language(value) is None

    def test_is_deterministic(self):
        text = "Bardzo dobra gra, polecam każdemu"
        assert len({detect_language(text) for _ in range(20)}) == 1

    def test_long_text_is_capped_not_rejected(self):
        assert detect_language("the game is truly wonderful. " * 500) == "en"


class TestBuildEventRow:
    def _row(self, record=None, **kwargs):
        return build_event_row(
            record=validate_record(record or VALID),
            sentiment=kwargs.get("sentiment", Sentiment("pos", 0.75, "stub/1")),
            processed_at=kwargs.get("processed_at", datetime(2026, 9, 5, tzinfo=UTC)),
            language=kwargs.get("language", "en"),
        )

    def test_writes_exactly_the_schema_columns(self):
        assert tuple(self._row()) == EVENT_COLUMNS

    def test_carries_the_sentiment(self):
        row = self._row(sentiment=Sentiment("neg", 0.5, "stub/9"))
        assert row["sentiment_label"] == "neg"
        assert row["sentiment_score"] == 0.5
        assert row["model_version"] == "stub/9"

    def test_stamps_processed_at(self):
        assert self._row()["processed_at"] == "2026-09-05T00:00:00Z"

    def test_language_argument_overrides_the_advisory_value(self):
        # The collector's langdetect output is advisory; the pipeline's is
        # authoritative in the events table.
        assert (
            self._row(record={**VALID, "language": "de"}, language="fr")["language"]
            == "fr"
        )

    def test_drops_unknown_fields(self):
        row = self._row(record={**VALID, "surprise": "value", "score2": 1})
        assert "surprise" not in row and "score2" not in row

    def test_missing_optional_fields_become_none(self):
        row = self._row(record={"id": "x", "created_utc": "2025-04-24T12:00:00Z"})
        assert row["source"] is None
        assert row["collected_at"] is None
        assert row["score"] is None

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("12", 12), (12.9, 12), (None, None), ("x", None), (True, None)],
    )
    def test_score_coercion(self, value, expected):
        assert self._row(record={**VALID, "score": value})["score"] == expected

    def test_sentiment_score_is_a_float(self):
        assert isinstance(self._row()["sentiment_score"], float)


class TestBuildDeadLetter:
    def test_preserves_the_original_payload(self):
        data, _ = build_dead_letter(b'{"id": ', {"source": "youtube"}, "bad JSON")
        assert data == b'{"id": '

    def test_preserves_original_attributes(self):
        _, attrs = build_dead_letter(b"x", {"source": "youtube"}, "bad")
        assert attrs["source"] == "youtube"

    def test_adds_diagnostics(self):
        _, attrs = build_dead_letter(b"x", None, "because reasons")
        assert attrs["dlq_error"] == "because reasons"
        assert attrs["dlq_at"].endswith("Z")

    def test_truncates_a_huge_error(self):
        _, attrs = build_dead_letter(b"x", None, "e" * 5000)
        assert len(attrs["dlq_error"]) == 1024

    def test_handles_non_utf8_payloads(self):
        data, attrs = build_dead_letter(b"\xff\xfe", None, "not UTF-8")
        assert data == b"\xff\xfe"
        assert attrs["dlq_error"] == "not UTF-8"


class TestIsoUtc:
    def test_formats_with_trailing_z(self):
        assert iso_utc(datetime(2025, 4, 24, 12, 0, tzinfo=UTC)) == (
            "2025-04-24T12:00:00Z"
        )

    def test_naive_is_read_as_utc(self):
        assert iso_utc(datetime(2025, 4, 24, 12, 0)) == "2025-04-24T12:00:00Z"
