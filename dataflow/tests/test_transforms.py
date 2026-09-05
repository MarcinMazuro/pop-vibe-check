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
    warm_up_language_detection,
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


class TestDetectLanguageDeterminism:
    """Regression guard for the reproducibility bug found on the first run.

    Two replays of identical data disagreed on the language of 68 short
    comments. The cause was a seed set as an import-time side effect,
    which did not take effect on the Dataflow workers, leaving langdetect
    to seed from system entropy. These tests clear the seed first, so they
    fail if determinism ever depends on module import again.
    """

    # Short texts whose detection is unstable when unseeded.
    UNSTABLE = ["Hell yeah!", "so hype wtfff", "RPG TIME", "what is this?"]

    def _clear_seed(self):
        from langdetect import DetectorFactory

        DetectorFactory.seed = None

    @pytest.mark.parametrize("text", UNSTABLE)
    def test_stable_after_the_seed_is_cleared(self, text):
        self._clear_seed()
        assert len({detect_language(text) for _ in range(25)}) == 1

    def test_interleaved_calls_do_not_affect_each_other(self):
        # Workers batch records in different orders between runs, so a
        # detector whose result depends on call history is not reproducible.
        self._clear_seed()
        alone = [detect_language(t) for t in self.UNSTABLE]
        self._clear_seed()
        for filler in ("some unrelated english sentence here", "ein deutscher satz"):
            detect_language(filler)
        interleaved = []
        for text in self.UNSTABLE:
            detect_language("noise between detections")
            interleaved.append(detect_language(text))
        assert alone == interleaved


class TestLanguageDetectionUnderConcurrency:
    """The cold-start race that broke reproducibility on the first live run.

    langdetect publishes its factory global before the language profiles
    finish loading, so concurrent first calls detect against a partial
    profile set — plain English text comes back as "af" or "da", or the
    detector raises and the language is lost entirely. Dataflow runs
    several bundle threads per worker, so a cold worker hits this almost
    every time.

    Each test resets langdetect to its cold state first, so they fail if
    the serialised warm-up is ever removed.
    """

    TEXTS = [
        "Damage numbers...",
        "It going on gamepass day one is wild",
        "Best art direction of 2024 ? I'm impressed. I usually don't play "
        "turn based game but I may give it a try on easy mode.",
    ]

    def _go_cold(self):
        import langdetect.detector_factory as factory

        import dataflow.transforms as mod

        factory._factory = None
        mod._langdetect_ready = False

    def _detect_concurrently(self, threads=12):
        import threading

        results, errors = {}, []

        def work(i):
            try:
                results[i] = detect_language(self.TEXTS[i % len(self.TEXTS)])
            except Exception as exc:  # pragma: no cover - must stay empty
                errors.append(exc)

        workers = [threading.Thread(target=work, args=(i,)) for i in range(threads)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        return results, errors

    def test_cold_concurrent_detection_agrees_with_warm_detection(self):
        self._go_cold()
        results, errors = self._detect_concurrently()
        assert errors == []
        assert set(results.values()) == {"en"}

    def test_no_language_is_lost_to_the_race(self):
        # Threads that lost the race used to raise "Need to load profiles",
        # which this module turns into a null language.
        self._go_cold()
        results, _ = self._detect_concurrently()
        assert None not in results.values()

    def test_repeated_cold_starts_give_the_same_answer(self):
        runs = []
        for _ in range(3):
            self._go_cold()
            results, _ = self._detect_concurrently()
            runs.append(sorted(results.items()))
        assert runs[0] == runs[1] == runs[2]

    def test_warm_up_is_idempotent(self):
        self._go_cold()
        for _ in range(5):
            warm_up_language_detection()
        assert detect_language(self.TEXTS[0]) == "en"
