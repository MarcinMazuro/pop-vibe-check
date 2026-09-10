"""MLflow tracking with a GCS artifact store.

Hosting is Workbench-local plus a GCS backend — no Cloud SQL, no Cloud
Run UI. That is enough for the thesis requirement to record learning
rate, epochs, batch size, accuracy, and macro-F1.

This module must not be imported from :mod:`nlp.registry`. The registry
is the Dataflow classifier factory; tracking is a training concern.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_GCS_TRACKING_URI = "gs://co-tf-artifacts-dev/nlp/mlruns"
DEFAULT_EXPERIMENT = "distilbert-sentiment"


def start_run(
    *,
    tracking_uri: str | None = None,
    experiment: str = DEFAULT_EXPERIMENT,
    run_name: str | None = None,
) -> Any:
    """Configure MLflow and open a run.

    Args:
        tracking_uri: MLflow tracking URI. ``None`` uses ``MLFLOW_TRACKING_URI``
            or :data:`DEFAULT_GCS_TRACKING_URI`.
        experiment: Experiment name.
        run_name: Optional run name.

    Returns:
        The active ``mlflow.ActiveRun``.
    """
    import os
    from pathlib import Path

    import mlflow
    from mlflow.tracking import MlflowClient

    uri = (
        tracking_uri
        or os.environ.get("MLFLOW_TRACKING_URI")
        or DEFAULT_GCS_TRACKING_URI
    )
    # MLflow's tracking *store* is file/SQL/HTTP. ``gs://`` is valid as an
    # artifact location (google-cloud-storage) but not as the registry URI
    # on Workbench-local MLflow 2.x.
    if uri.startswith("gs://"):
        local = Path(
            os.environ.get("MLFLOW_LOCAL_STORE", "/home/jupyter/mlruns")
        ).resolve()
        local.mkdir(parents=True, exist_ok=True)
        tracking = local.as_uri()
        mlflow.set_tracking_uri(tracking)
        client = MlflowClient(tracking_uri=tracking)
        existing = client.get_experiment_by_name(experiment)
        if existing is None:
            client.create_experiment(experiment, artifact_location=uri)
        logger.info(
            "MLflow tracking_uri=%s artifact_location=%s experiment=%s",
            tracking,
            uri,
            experiment,
        )
    else:
        mlflow.set_tracking_uri(uri)
        logger.info("MLflow tracking_uri=%s experiment=%s", uri, experiment)
    mlflow.set_experiment(experiment)
    return mlflow.start_run(run_name=run_name)


def log_params(params: Mapping[str, Any]) -> None:
    """Log training hyperparameters.

    Args:
        params: Name → value (lr, epochs, batch, …).
    """
    import mlflow

    mlflow.log_params({key: _stringify(value) for key, value in params.items()})


def log_metrics(metrics: Mapping[str, float], *, step: int | None = None) -> None:
    """Log scalar metrics (accuracy, macro-F1, per-class precision/recall).

    Args:
        metrics: Name → float.
        step: Optional step index (epoch).
    """
    import mlflow

    mlflow.log_metrics(dict(metrics), step=step)


def log_weights(model_dir: str, *, artifact_path: str = "model") -> None:
    """Upload the saved Hugging Face model directory as an MLflow artifact.

    Prefers ``mlflow.transformers.log_model`` when the package can load
    the directory as a transformers checkpoint; falls back to
    ``log_artifacts`` so a half-written export still lands in GCS.

    Args:
        model_dir: Local directory from ``Trainer.save_model``.
        artifact_path: Artifact subdirectory inside the run.
    """
    import mlflow

    try:
        mlflow.transformers.log_model(
            transformers_model=model_dir,
            artifact_path=artifact_path,
        )
    except Exception:  # noqa: BLE001 — transformers extra is optional
        logger.warning(
            "mlflow.transformers.log_model failed; falling back to log_artifacts",
            exc_info=True,
        )
        mlflow.log_artifacts(model_dir, artifact_path=artifact_path)


def end_run() -> None:
    """Close the active MLflow run if one is open."""
    import mlflow

    mlflow.end_run()


def _stringify(value: Any) -> str:
    """Render a param value as MLflow expects a string.

    Args:
        value: Any param.

    Returns:
        ``str(value)``.
    """
    return str(value)
