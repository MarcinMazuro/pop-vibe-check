"""What one experiment run is, and how it maps onto the replay build.

A run is the existing replay build (``dataflow/replay.cloudbuild.yaml``)
with experiment parameters. Reusing it keeps the one guarantee that
matters most for cost: the Dataflow job is always drained, even when the
run fails.

Every run is redirected away from the real tables — the pipeline writes
``events_landing_perf``, nothing is promoted, and the publisher never
reloads staging. See ``terraform/modules/bigquery/perf.tf`` for why.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PERF_LANDING_TABLE = "events_landing_perf"
PERF_STAGING_TABLE = "raw_staging_perf"
REAL_STAGING_TABLE = "raw_staging"
ALLOWED_STAGING_TABLES = (REAL_STAGING_TABLE, PERF_STAGING_TABLE)
MODELS = ("stub", "vertex")

# Dataflow label keys start with a lowercase letter; keys and values use
# lowercase letters, digits, '_' and '-', at most 63 characters.
_LABEL_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
_LABEL_VALUE = re.compile(r"^[a-z0-9_-]{0,63}$")

# gcloud's alternate list delimiter, so values may contain commas
# (LABELS does). See `gcloud topic escaping`.
SUBSTITUTION_DELIMITER = "~"


class SpecError(ValueError):
    """An experiment run specification is invalid."""


@dataclass(frozen=True)
class RunSpec:
    """Parameters of one experiment run.

    Attributes:
        experiment: Experiment id from the plan, e.g. ``e1``.
        run_id: Unique run id, e.g. ``e1-w2-s2000``; also a job label.
        model: ``stub`` or ``vertex``.
        speedup: Publisher time-compression factor; ``None`` keeps the
            publisher's deployed default.
        max_workers: Dataflow max workers.
        machine_type: Dataflow worker machine type.
        max_batch_size: Records per classifier call; ``None`` keeps the
            template default.
        staging_table: Table the publisher replays: ``raw_staging`` (real
            data) or ``raw_staging_perf`` (amplified copies).
        copies: Amplification factor of the staging table, recorded for
            the results (1 for real data).
        max_sleep_seconds: Publisher's cap on one inter-record sleep;
            ``None`` keeps its default.
        wait_timeout_minutes: How long the build waits for every record.
        endpoint_replicas: Vertex replicas deployed for the run, recorded
            for the results; the runner does not change the endpoint.
        notes: Free text stored with the results.
    """

    experiment: str
    run_id: str
    model: str = "stub"
    speedup: float | None = None
    max_workers: int = 2
    machine_type: str = "e2-standard-2"
    max_batch_size: int | None = None
    staging_table: str = REAL_STAGING_TABLE
    copies: int = 1
    max_sleep_seconds: float | None = None
    wait_timeout_minutes: int = 180
    endpoint_replicas: int | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        """Validate the specification.

        Raises:
            SpecError: If any field is out of range.
        """
        for key, value in (("experiment", self.experiment), ("run", self.run_id)):
            if not value or not _LABEL_VALUE.fullmatch(value):
                raise SpecError(
                    f"{key} id {value!r} must be lowercase letters, digits, "
                    "'-' or '_' (it becomes a Dataflow job label)."
                )
        if self.model not in MODELS:
            raise SpecError(f"model must be one of {MODELS}, got {self.model!r}.")
        if self.speedup is not None and self.speedup <= 0:
            raise SpecError("speedup must be positive.")
        if self.max_workers < 1:
            raise SpecError("max_workers must be at least 1.")
        if self.max_batch_size is not None and self.max_batch_size < 1:
            raise SpecError("max_batch_size must be at least 1.")
        if self.staging_table not in ALLOWED_STAGING_TABLES:
            raise SpecError(f"staging_table must be one of {ALLOWED_STAGING_TABLES}.")
        if self.copies < 1:
            raise SpecError("copies must be at least 1.")
        if self.copies > 1 and self.staging_table != PERF_STAGING_TABLE:
            raise SpecError(f"copies > 1 only makes sense with {PERF_STAGING_TABLE}.")
        if self.wait_timeout_minutes < 1:
            raise SpecError("wait_timeout_minutes must be at least 1.")

    def labels(self) -> dict[str, str]:
        """Return the Dataflow job labels for this run."""
        labels = {"experiment": self.experiment, "run": self.run_id, "purpose": "perf"}
        for key, value in labels.items():
            if not _LABEL_KEY.fullmatch(key) or not _LABEL_VALUE.fullmatch(value):
                raise SpecError(f"invalid label {key}={value}")
        return labels

    def substitutions(self, base: dict[str, str], project_id: str) -> dict[str, str]:
        """Return the replay build's substitutions for this run.

        Starts from the replay trigger's own substitutions (the
        infrastructure values Terraform put there) and overrides the
        experiment parameters and every table the run touches.

        Args:
            base: Substitutions of the ``co-replay-dev`` trigger.
            project_id: GCP project id.

        Returns:
            The full substitution map for ``gcloud builds submit``.

        Raises:
            SpecError: If the trigger lacks the dataset, or the result
                would write anywhere but the perf landing table.
        """
        dataset = base.get("_DATASET", "")
        if not dataset:
            raise SpecError("The replay trigger has no _DATASET substitution.")

        labels = ",".join(f"{k}={v}" for k, v in self.labels().items())
        overrides = {
            "_MODEL": self.model,
            "_SPEEDUP": _fmt(self.speedup),
            "_MAX_SLEEP_SECONDS": _fmt(self.max_sleep_seconds),
            "_MAX_WORKERS": str(self.max_workers),
            "_MACHINE_TYPE": self.machine_type,
            "_MAX_BATCH_SIZE": _fmt(self.max_batch_size),
            "_LABELS": labels,
            # Never touch the real tables.
            "_RUN_LOAD": "false",
            "_PROMOTE": "false",
            "_OUTPUT_TABLE": f"{project_id}:{dataset}.{PERF_LANDING_TABLE}",
            "_EVENTS_LANDING_TABLE_ID": PERF_LANDING_TABLE,
            "_RAW_STAGING_TABLE_ID": self.staging_table,
            "_PUBLISHER_STAGING_TABLE": self.staging_table,
            "_WAIT_TIMEOUT_MINUTES": str(self.wait_timeout_minutes),
            # Whole-table replays only: the wait step's expected count
            # must be the staging table's full distinct-id count.
            "_EVENT_ID": "",
            "_WINDOW_FROM": "",
            "_WINDOW_TO": "",
        }
        result = {**base, **overrides}

        if not result["_OUTPUT_TABLE"].endswith(f".{PERF_LANDING_TABLE}"):
            raise SpecError("Refusing to run: output is not the perf landing table.")
        for key, value in result.items():
            if SUBSTITUTION_DELIMITER in value:
                raise SpecError(f"{key} contains '{SUBSTITUTION_DELIMITER}'.")
        return result

    def to_json(self) -> str:
        """Serialise the specification as JSON."""
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> RunSpec:
        """Load a specification from JSON written by :meth:`to_json`."""
        data: dict[str, Any] = json.loads(text)
        return cls(**data)

    @classmethod
    def from_file(cls, path: Path) -> RunSpec:
        """Load a specification from a JSON file."""
        return cls.from_json(path.read_text(encoding="utf-8"))


def substitutions_arg(substitutions: dict[str, str]) -> str:
    """Render substitutions as one ``--substitutions`` value.

    Uses gcloud's alternate-delimiter syntax (``^~^KEY=v~KEY=v``) because
    label lists contain commas.

    Args:
        substitutions: Substitution map.

    Returns:
        The flag value.
    """
    d = SUBSTITUTION_DELIMITER
    body = d.join(f"{k}={v}" for k, v in sorted(substitutions.items()))
    return f"^{d}^{body}"


def _fmt(value: float | int | None) -> str:
    """Format an optional number for a substitution (empty when None)."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
