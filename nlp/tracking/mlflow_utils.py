"""MLflow tracking with a GCS artifact store.

Runs are tracked on the MLflow server (Cloud Run behind IAP, Postgres on
Cloud SQL — ``terraform/modules/mlflow``): set ``MLFLOW_TRACKING_URI`` to
its URL and ``MLFLOW_IAP_AUDIENCE`` to the IAP OAuth client ID. Artifacts
go straight to GCS under ``nlp/mlruns/`` either way; the server does not
proxy them. A ``gs://`` tracking URI still selects the older
Workbench-local file store.

This module must not be imported from :mod:`nlp.registry`. The registry
is the Dataflow classifier factory; tracking is a training concern.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_GCS_TRACKING_URI = "gs://co-tf-artifacts-dev/nlp/mlruns"
DEFAULT_EXPERIMENT = "xlmr-sentiment"

IAP_AUDIENCE_ENV = "MLFLOW_IAP_AUDIENCE"
# Google ID tokens live an hour. Refreshing at half that keeps a training
# run longer than an hour authenticated without tracking expiry.
IAP_TOKEN_REFRESH_SECONDS = 30 * 60


def use_iap_token(audience: str) -> None:
    """Keep ``MLFLOW_TRACKING_TOKEN`` set to a fresh Google ID token.

    IAP admits a program that presents a Google-signed ID token minted for
    its OAuth client, from an identity holding
    ``roles/iap.httpsResourceAccessor``. MLflow reads
    ``MLFLOW_TRACKING_TOKEN`` on every request and sends it as a bearer
    token, so replacing the variable on a timer is all a refresh needs.

    The token comes from Application Default Credentials: the metadata
    server on Workbench, or a service account key elsewhere. A user's
    ``gcloud`` login cannot mint a token for an arbitrary audience.

    Args:
        audience: The IAP OAuth client ID.
    """
    import google.auth.transport.requests
    import google.oauth2.id_token

    os.environ["MLFLOW_TRACKING_TOKEN"] = google.oauth2.id_token.fetch_id_token(
        google.auth.transport.requests.Request(), audience
    )
    timer = threading.Timer(IAP_TOKEN_REFRESH_SECONDS, use_iap_token, (audience,))
    timer.daemon = True
    timer.start()


def start_run(
    *,
    tracking_uri: str | None = None,
    experiment: str = DEFAULT_EXPERIMENT,
    run_name: str | None = None,
) -> Any:
    """Configure MLflow and open a run.

    Args:
        tracking_uri: MLflow tracking URI. ``None`` uses ``MLFLOW_TRACKING_URI``
            or :data:`DEFAULT_GCS_TRACKING_URI`. For an ``https://`` server,
            ``MLFLOW_IAP_AUDIENCE`` set in the environment switches on the
            IAP token (:func:`use_iap_token`).
        experiment: Experiment name.
        run_name: Optional run name.

    Returns:
        The active ``mlflow.ActiveRun``.
    """
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
        audience = os.environ.get(IAP_AUDIENCE_ENV)
        if audience:
            use_iap_token(audience)
        mlflow.set_tracking_uri(uri)
        logger.info(
            "MLflow tracking_uri=%s experiment=%s iap=%s",
            uri,
            experiment,
            bool(audience),
        )
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
