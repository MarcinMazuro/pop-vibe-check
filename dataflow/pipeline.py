"""Streaming pipeline: replayed Pub/Sub records to enriched BigQuery rows.

Shape of the job:

    ReadFromPubSub(subscription, event time from created_utc)
        -> parse, validate                 -- failures to the dead-letter topic
        -> batch
        -> detect language, classify sentiment, stamp processed_at
        -> WriteToBigQuery(events_landing, append)

Two design points worth stating up front.

**The pipeline writes to the landing table only.** ``events`` is written
exclusively by the promotion MERGE that runs after a replay drains. That
split is what lets this job be at-least-once — duplicate deliveries and
repeated passes over the same id collapse to one row per id downstream,
so the reproducibility guarantee does not depend on exactly-once
semantics from Pub/Sub or Beam.

**Event time comes from the record, not the delivery.** The replay
compresses months into minutes, so publish time is meaningless as a
clock. Reading ``created_utc`` as the timestamp attribute makes the
watermark track the events' real chronology, which is what any
event-time windowing added later needs to be correct.
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime
from typing import Any

import apache_beam as beam
from apache_beam.io.gcp.pubsub import PubsubMessage
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions
from google.cloud import bigquery
from nlp.base import SentimentClassifier
from nlp.registry import load_classifier

from dataflow.options import SentimentOptions
from dataflow.transforms import (
    RecordError,
    build_dead_letter,
    build_event_row,
    detect_language,
    parse_message,
    validate_record,
    warm_up_language_detection,
)

logger = logging.getLogger("dataflow.pipeline")

# Tag for the side output carrying records the pipeline could not turn
# into an events row.
DEAD_LETTER = "dead_letter"


class ParseAndValidate(beam.DoFn):
    """Turn a Pub/Sub message into a validated record, or dead-letter it.

    Only structural failures are diverted here — malformed JSON, a missing
    id or created_utc. A record the models later find difficult still
    reaches BigQuery.
    """

    def process(self, message: PubsubMessage) -> Any:
        """Parse and validate one message.

        Args:
            message: The inbound Pub/Sub message, with attributes.

        Yields:
            The validated record on the main output, or a
            :class:`PubsubMessage` tagged :data:`DEAD_LETTER`.
        """
        try:
            record = validate_record(parse_message(message.data))
        except RecordError as exc:
            data, attributes = build_dead_letter(
                message.data, dict(message.attributes or {}), str(exc)
            )
            logger.warning("Dead-lettering record: %s", exc)
            yield beam.pvalue.TaggedOutput(
                DEAD_LETTER, PubsubMessage(data=data, attributes=attributes)
            )
            return
        yield record


class ClassifyBatch(beam.DoFn):
    """Detect language and classify sentiment for a batch of records.

    The classifier is constructed once per worker process in
    :meth:`setup`, never per element. The stub is local. The Vertex
    client calls ``Endpoint.predict`` over Private Google Access —
    Google APIs are reachable, PyPI and Hugging Face Hub are not.
    """

    def __init__(
        self,
        model_name: str,
        vertex_endpoint_id: str = "",
        vertex_project: str = "",
        vertex_location: str = "",
    ) -> None:
        """Record which classifier to load and the Vertex env to inject.

        Args:
            model_name: Name resolved through the nlp registry.
            vertex_endpoint_id: Copied into ``VERTEX_ENDPOINT_ID`` before
                constructing a ``vertex`` classifier. Empty for the stub.
            vertex_project: Copied into ``VERTEX_PROJECT``.
            vertex_location: Copied into ``VERTEX_LOCATION``.
        """
        self._model_name = model_name
        self._vertex_endpoint_id = vertex_endpoint_id
        self._vertex_project = vertex_project
        self._vertex_location = vertex_location
        self._classifier: SentimentClassifier | None = None

    def setup(self) -> None:
        """Load the classifier and the language profiles once per process.

        Flex Template ``--parameters`` become pipeline options, not worker
        environment variables, so Vertex config is copied into ``os.environ``
        here before the zero-argument registry factory runs.

        The language profiles are warmed up here rather than on first use
        so the load happens before several bundle threads start calling
        the detector at once — see warm_up_language_detection.
        """
        if self._vertex_endpoint_id:
            os.environ["VERTEX_ENDPOINT_ID"] = self._vertex_endpoint_id
        if self._vertex_project:
            os.environ["VERTEX_PROJECT"] = self._vertex_project
        if self._vertex_location:
            os.environ["VERTEX_LOCATION"] = self._vertex_location
        warm_up_language_detection()
        self._classifier = load_classifier(self._model_name)
        logger.info(
            "Loaded classifier '%s' (model_version=%s).",
            self._model_name,
            self._classifier.model_version,
        )

    def process(self, batch: list[dict[str, Any]]) -> Any:
        """Enrich one batch of validated records.

        Args:
            batch: Validated records.

        Yields:
            One events_landing row per input record.
        """
        assert self._classifier is not None, "setup() must run before process()."

        texts = [record.get("text") or "" for record in batch]
        sentiments = self._classifier.classify_batch(texts)
        processed_at = datetime.now(UTC)

        for record, text, sentiment in zip(batch, texts, sentiments, strict=True):
            yield build_event_row(
                record=record,
                sentiment=sentiment,
                processed_at=processed_at,
                language=detect_language(text),
            )


def fetch_output_schema(table: str) -> dict[str, Any]:
    """Read the write target's schema from BigQuery when the graph is built.

    The Storage Write API needs an explicit schema — unlike streaming
    inserts, it will not read one off the destination table. The obvious
    fix is to declare the events schema again in Python, but that would
    put a second copy of it next to the Terraform-managed one it has to
    match exactly, free to drift the moment either side changes. Reading
    it from the table keeps Terraform the single source of truth.

    This runs in the launcher, once per launch, not on the workers.

    Args:
        table: Write target as ``PROJECT:DATASET.TABLE``.

    Returns:
        The table schema in the dict form BigQueryIO accepts.

    Raises:
        ValueError: If ``table`` is not in ``PROJECT:DATASET.TABLE`` form.
    """
    project, _, dataset_table = table.partition(":")
    dataset, _, table_id = dataset_table.partition(".")
    if not (project and dataset and table_id):
        raise ValueError(f"output_table must be PROJECT:DATASET.TABLE, got '{table}'.")

    client = bigquery.Client(project=project)
    schema = client.get_table(f"{project}.{dataset}.{table_id}").schema
    logger.info("Read %d columns from %s.", len(schema), table)
    return {
        "fields": [
            {
                "name": field.name,
                "type": field.field_type,
                "mode": field.mode or "NULLABLE",
            }
            for field in schema
        ]
    }


def build_pipeline(pipeline: beam.Pipeline, options: SentimentOptions) -> None:
    """Wire the pipeline's transforms onto ``pipeline``.

    Split out from :func:`run` so the graph can be constructed against a
    test runner without going near Dataflow.

    Args:
        pipeline: The pipeline to attach transforms to.
        options: Resolved custom options.
    """
    timestamp_attribute = options.timestamp_attribute or None

    messages = pipeline | "ReadFromPubSub" >> beam.io.ReadFromPubSub(
        subscription=options.input_subscription,
        with_attributes=True,
        timestamp_attribute=timestamp_attribute,
    )

    parsed = messages | "ParseAndValidate" >> beam.ParDo(
        ParseAndValidate()
    ).with_outputs(DEAD_LETTER, main="records")

    (
        parsed[DEAD_LETTER]
        | "WriteDeadLetters"
        >> beam.io.WriteToPubSub(topic=options.dlq_topic, with_attributes=True)
    )

    rows = (
        parsed.records
        | "BatchRecords"
        >> beam.BatchElements(min_batch_size=1, max_batch_size=options.max_batch_size)
        | "Classify"
        >> beam.ParDo(
            ClassifyBatch(
                options.nlp_model,
                vertex_endpoint_id=options.vertex_endpoint_id or "",
                vertex_project=options.vertex_project or "",
                vertex_location=options.vertex_location or "europe-central2",
            )
        )
    )

    # At-least-once is deliberate: the landing table is append-only and
    # the promotion MERGE collapses duplicates by id, so paying for
    # exactly-once here would buy a guarantee the design already provides.
    #
    # STORAGE_WRITE_API additionally requires Java — it is a cross-language
    # transform in the Python SDK — which is why it is no longer the
    # default. See BQ_WRITE_METHODS in dataflow/options.py.
    method_kwargs: dict[str, Any] = (
        {"use_at_least_once": True}
        if options.bq_write_method == "STORAGE_WRITE_API"
        else {"insert_retry_strategy": "RETRY_ON_TRANSIENT_ERROR"}
    )

    write_result = rows | "WriteToBigQuery" >> beam.io.WriteToBigQuery(
        table=options.output_table,
        schema=fetch_output_schema(options.output_table),
        method=options.bq_write_method,
        # The table is owned by Terraform. CREATE_NEVER means a typo in
        # --output_table fails the job instead of quietly creating a
        # second, unmanaged table that nothing reads.
        create_disposition=beam.io.BigQueryDisposition.CREATE_NEVER,
        write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
        **method_kwargs,
    )

    _route_failed_rows(write_result, options.dlq_topic)


def _route_failed_rows(write_result: Any, dlq_topic: str) -> None:
    """Send rows BigQuery rejected to the dead-letter topic.

    A row can pass validation and still be refused by BigQuery — a value
    too large for its column, say. Those rows would otherwise vanish into
    the job's error counters, so they join the parse failures on the DLQ
    and an operator has one place to look.

    The attribute exposing failed rows differs between Beam's write
    methods and has moved across releases, so its absence is logged rather
    than raised: losing the diagnostic branch is not worth failing a
    launch over.

    Args:
        write_result: The result of :class:`~apache_beam.io.WriteToBigQuery`.
        dlq_topic: Dead-letter topic to publish to.
    """
    failed_rows = getattr(write_result, "failed_rows", None)
    if failed_rows is None:
        logger.warning(
            "This Beam release exposes no failed_rows output; BigQuery "
            "rejections will appear only in job error counters."
        )
        return

    (
        failed_rows
        | "FailedRowToMessage" >> beam.Map(_failed_row_to_message)
        | "WriteFailedRows"
        >> beam.io.WriteToPubSub(topic=dlq_topic, with_attributes=True)
    )


def _failed_row_to_message(failed: Any) -> PubsubMessage:
    """Render a BigQuery-rejected row as a dead-letter message.

    Args:
        failed: A ``(destination, row)`` pair, or a row on its own,
            depending on the write method.

    Returns:
        The message to publish to the dead-letter topic.
    """
    row = failed[1] if isinstance(failed, tuple) and len(failed) >= 2 else failed
    payload = str(row).encode("utf-8")
    data, attributes = build_dead_letter(payload, {}, "rejected by BigQuery")
    return PubsubMessage(data=data, attributes=attributes)


def run(argv: list[str] | None = None) -> None:
    """Build and launch the streaming pipeline.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv``.
    """
    logging.getLogger().setLevel(logging.INFO)

    known, _ = argparse.ArgumentParser().parse_known_args(argv)
    del known  # Beam parses the arguments; this only validates argv shape.

    pipeline_options = PipelineOptions(argv)
    pipeline_options.view_as(StandardOptions).streaming = True
    options = pipeline_options.view_as(SentimentOptions)

    logger.info(
        "Starting pipeline: subscription=%s table=%s dlq=%s model=%s "
        "vertex_endpoint=%s method=%s",
        options.input_subscription,
        options.output_table,
        options.dlq_topic,
        options.nlp_model,
        options.vertex_endpoint_id or "-",
        options.bq_write_method,
    )

    with beam.Pipeline(options=pipeline_options) as pipeline:
        build_pipeline(pipeline, options)


if __name__ == "__main__":
    run()
