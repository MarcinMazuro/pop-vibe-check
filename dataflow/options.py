"""Launch-time options for the sentiment pipeline.

Every value here is supplied by ``gcloud dataflow flex-template run
--parameters=...`` and comes from ``terraform output`` rather than being
hardcoded, so the pipeline never carries a copy of a subscription path or
a table reference that could drift from the deployed infrastructure.
"""

from __future__ import annotations

import argparse

from apache_beam.options.pipeline_options import PipelineOptions

# BigQuery write methods this pipeline accepts.
#
# STREAMING_INSERTS is the default, which reverses an earlier decision.
# STORAGE_WRITE_API is cheaper per byte, but in the Python SDK it is a
# cross-language transform: it needs a Java expansion service when the
# graph is built and a Java SDK harness on the workers at runtime. The
# first launch attempt died on exactly that ("Java must be installed on
# this system"). Carrying a JRE in an image that must stay self-contained,
# plus a second language runtime on every worker, is a real cost — and the
# saving it buys is meaningless at this volume, where a whole replay is a
# few megabytes. STREAMING_INSERTS is pure Python and needs neither.
#
# Either way the landing table is append-only and the promotion MERGE
# collapses duplicates by id, so at-least-once delivery is correct.
# STORAGE_WRITE_API stays selectable for anyone who adds the JRE and wants
# the cheaper path at a larger volume.
BQ_WRITE_METHODS = ("STREAMING_INSERTS", "STORAGE_WRITE_API")


class SentimentOptions(PipelineOptions):
    """Custom options for the streaming sentiment pipeline."""

    @classmethod
    def _add_argparse_args(cls, parser: argparse.ArgumentParser) -> None:
        """Declare the pipeline's own parameters.

        Args:
            parser: Parser Beam supplies for custom options.
        """
        parser.add_argument(
            "--input_subscription",
            required=True,
            help=(
                "Pub/Sub subscription to consume, as "
                "projects/<project>/subscriptions/<name>. From the "
                "dataflow_input_subscription Terraform output."
            ),
        )
        parser.add_argument(
            "--output_table",
            required=True,
            help=(
                "BigQuery write target as PROJECT:DATASET.TABLE. From the "
                "dataflow_events_landing_table Terraform output. This is "
                "always the landing table — the events table is written "
                "only by the promotion MERGE, never by the pipeline."
            ),
        )
        parser.add_argument(
            "--dlq_topic",
            required=True,
            help=(
                "Dead-letter topic as projects/<project>/topics/<name>. "
                "From the dataflow_dlq_topic Terraform output."
            ),
        )
        parser.add_argument(
            "--nlp_model",
            default="stub",
            help=(
                "Name of the classifier to load from the nlp registry. "
                "Defaults to the deterministic stub."
            ),
        )
        parser.add_argument(
            "--bq_write_method",
            default="STREAMING_INSERTS",
            choices=BQ_WRITE_METHODS,
            help="BigQuery write method. See BQ_WRITE_METHODS for the trade-off.",
        )
        parser.add_argument(
            "--timestamp_attribute",
            default="created_utc",
            help=(
                "Pub/Sub attribute carrying the event time, so the "
                "watermark follows the replayed record's own timestamp "
                "rather than the moment the publisher emitted it. Pass an "
                "empty string to fall back to publish time — the escape "
                "hatch if a producer ever emits an unparseable value, "
                "which would otherwise fail the read before the "
                "dead-letter path can catch it."
            ),
        )
        parser.add_argument(
            "--max_batch_size",
            type=int,
            default=200,
            help=(
                "Upper bound on how many records are handed to the "
                "classifier at once. Exists so a batched model gets a "
                "batched forward pass; the stub ignores the benefit."
            ),
        )
