"""Beam-level tests for the pipeline's DoFns.

Skipped wholesale when apache-beam is absent, so the rest of the suite
still runs in a bare environment. The Pub/Sub and BigQuery IOs are not
exercised here — they need real endpoints; these tests cover the logic
between them.
"""

import json

import pytest

beam = pytest.importorskip("apache_beam")

from apache_beam.io.gcp.pubsub import PubsubMessage  # noqa: E402
from apache_beam.options.pipeline_options import PipelineOptions  # noqa: E402
from apache_beam.testing.test_pipeline import (
    TestPipeline as BeamTestPipeline,
)  # noqa: E402
from apache_beam.testing.util import assert_that, equal_to, is_empty  # noqa: E402

from dataflow.pipeline import DEAD_LETTER, ClassifyBatch, ParseAndValidate  # noqa: E402
from dataflow.transforms import EVENT_COLUMNS  # noqa: E402

VALID = {
    "id": "youtube:Ugx123",
    "source": "youtube",
    "created_utc": "2025-04-24T12:00:00Z",
    "collected_at": "2026-07-05T09:00:00Z",
    "author_hash": "0123456789abcdef",
    "text": "An absolute masterpiece",
    "language": "en",
    "score": 12,
    "context_id": "dQw4w9WgXcQ",
    "event_tag": "launch",
}


# Beam merges the argparse arguments of every PipelineOptions subclass in
# the process, so importing dataflow.options makes our required launch
# parameters required for any pipeline built here. Supply placeholders:
# these tests exercise DoFns, never the IOs that would use them.
_TEST_ARGV = [
    "--input_subscription=projects/test/subscriptions/test",
    "--output_table=test:test.events_landing",
    "--dlq_topic=projects/test/topics/test-dlq",
]


def _pipeline() -> BeamTestPipeline:
    return BeamTestPipeline(options=PipelineOptions(_TEST_ARGV))


def _message(payload: bytes, **attributes) -> PubsubMessage:
    return PubsubMessage(data=payload, attributes=attributes or {})


def _encode(record: dict[str, object]) -> bytes:
    return json.dumps(record).encode("utf-8")


class TestParseAndValidateDoFn:
    def test_valid_message_reaches_the_main_output(self):
        with _pipeline() as p:
            outputs = (
                p
                | beam.Create([_message(_encode(VALID))])
                | beam.ParDo(ParseAndValidate()).with_outputs(
                    DEAD_LETTER, main="records"
                )
            )
            assert_that(
                outputs.records | beam.Map(lambda r: r["id"]),
                equal_to(["youtube:Ugx123"]),
            )
            assert_that(outputs[DEAD_LETTER], is_empty(), label="no-dead-letters")

    def test_malformed_message_is_dead_lettered(self):
        with _pipeline() as p:
            outputs = (
                p
                | beam.Create([_message(b'{"id": ', source="youtube")])
                | beam.ParDo(ParseAndValidate()).with_outputs(
                    DEAD_LETTER, main="records"
                )
            )
            assert_that(outputs.records, is_empty(), label="no-records")
            assert_that(
                outputs[DEAD_LETTER] | beam.Map(lambda m: m.data),
                equal_to([b'{"id": ']),
                label="payload-preserved",
            )

    def test_dead_letter_keeps_original_attributes_and_adds_the_reason(self):
        with _pipeline() as p:
            outputs = (
                p
                | beam.Create([_message(b"not json", source="youtube")])
                | beam.ParDo(ParseAndValidate()).with_outputs(
                    DEAD_LETTER, main="records"
                )
            )
            assert_that(
                outputs[DEAD_LETTER]
                | beam.Map(
                    lambda m: (m.attributes["source"], "dlq_error" in m.attributes)
                ),
                equal_to([("youtube", True)]),
            )

    def test_record_missing_created_utc_is_dead_lettered(self):
        record = {k: v for k, v in VALID.items() if k != "created_utc"}
        with _pipeline() as p:
            outputs = (
                p
                | beam.Create([_message(_encode(record))])
                | beam.ParDo(ParseAndValidate()).with_outputs(
                    DEAD_LETTER, main="records"
                )
            )
            assert_that(outputs.records, is_empty(), label="no-records")
            assert_that(
                outputs[DEAD_LETTER] | beam.Map(lambda m: 1), equal_to([1]), label="one"
            )

    def test_a_bad_message_does_not_take_out_the_good_ones(self):
        messages = [
            _message(_encode(VALID)),
            _message(b"garbage"),
            _message(_encode({**VALID, "id": "youtube:Ugx456"})),
        ]
        with _pipeline() as p:
            outputs = (
                p
                | beam.Create(messages)
                | beam.ParDo(ParseAndValidate()).with_outputs(
                    DEAD_LETTER, main="records"
                )
            )
            assert_that(
                outputs.records | beam.Map(lambda r: r["id"]),
                equal_to(["youtube:Ugx123", "youtube:Ugx456"]),
            )


class TestClassifyBatchDoFn:
    def test_emits_one_schema_shaped_row_per_record(self):
        batch = [VALID, {**VALID, "id": "youtube:Ugx456", "text": "terrible, refund"}]
        with _pipeline() as p:
            rows = p | beam.Create([batch]) | beam.ParDo(ClassifyBatch("stub"))
            assert_that(
                rows | beam.Map(lambda r: (r["id"], r["sentiment_label"])),
                equal_to([("youtube:Ugx123", "pos"), ("youtube:Ugx456", "neg")]),
            )

    def test_rows_have_exactly_the_schema_columns(self):
        with _pipeline() as p:
            rows = p | beam.Create([[VALID]]) | beam.ParDo(ClassifyBatch("stub"))
            assert_that(rows | beam.Map(lambda r: tuple(r)), equal_to([EVENT_COLUMNS]))

    def test_model_version_is_carried_onto_every_row(self):
        with _pipeline() as p:
            rows = p | beam.Create([[VALID]]) | beam.ParDo(ClassifyBatch("stub"))
            assert_that(
                rows | beam.Map(lambda r: r["model_version"]), equal_to(["stub/1"])
            )

    def test_language_is_recomputed_not_copied(self):
        # The record claims German; the pipeline's own detection wins.
        record = {
            **VALID,
            "language": "de",
            "text": "This is clearly written in English.",
        }
        with _pipeline() as p:
            rows = p | beam.Create([[record]]) | beam.ParDo(ClassifyBatch("stub"))
            assert_that(rows | beam.Map(lambda r: r["language"]), equal_to(["en"]))

    def test_empty_text_still_produces_a_row(self):
        # Model uncertainty must never drop an opinion.
        with _pipeline() as p:
            rows = (
                p
                | beam.Create([[{**VALID, "text": ""}]])
                | beam.ParDo(ClassifyBatch("stub"))
            )
            assert_that(
                rows | beam.Map(lambda r: (r["sentiment_label"], r["language"])),
                equal_to([("neu", None)]),
            )

    def test_unknown_model_fails_at_setup(self):
        with pytest.raises(Exception, match="Unknown NLP model"):
            with _pipeline() as p:
                _ = p | beam.Create([[VALID]]) | beam.ParDo(ClassifyBatch("nope"))
