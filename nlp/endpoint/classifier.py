"""SentimentClassifier that calls a Vertex AI Endpoint over REST.

Dataflow workers have no public IP. Private Google Access is enough to
reach ``aiplatform.googleapis.com``; it is not enough to reach PyPI or
Hugging Face Hub. This client therefore ships with no weights — the
Flex Template image only needs ``google-cloud-aiplatform``.

Configuration is environment-only so the registry factory stays
zero-argument::

    VERTEX_ENDPOINT_ID   projects/.../endpoints/... or the short id
    VERTEX_PROJECT       GCP project
    VERTEX_LOCATION      region, default europe-central2

On failure after retries this classifier **raises**. Returning a fake
``neu`` would quietly poison ``events``. Beam retries the bundle.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Protocol

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from nlp.base import ID2LABEL, LABELS, Sentiment, normalize_predicted_label

logger = logging.getLogger(__name__)

_DEFAULT_LOCATION = "europe-central2"
_PREDICT_TIMEOUT_SECONDS = 60.0
_MAX_ATTEMPTS = 5
_ENV_ENDPOINT = "VERTEX_ENDPOINT_ID"
_ENV_PROJECT = "VERTEX_PROJECT"
_ENV_LOCATION = "VERTEX_LOCATION"


class PredictEndpoint(Protocol):
    """Subset of ``google.cloud.aiplatform.Endpoint`` used here."""

    def predict(
        self,
        instances: list[dict[str, str]],
        timeout: float | None = None,
    ) -> Any:
        """Run prediction.

        Args:
            instances: Vertex instances, one ``{"text": ...}`` per row.
            timeout: Per-call timeout in seconds.

        Returns:
            An object with ``predictions`` and optionally
            ``deployed_model_id``.
        """
        ...


def _is_retryable(exc: BaseException) -> bool:
    """Return whether a predict failure should be retried.

    Args:
        exc: Raised exception.

    Returns:
        ``True`` for 429/5xx and the matching google-api-core classes.
    """
    try:
        from google.api_core import exceptions as gcp_exceptions
    except ImportError:
        gcp_exceptions = None  # type: ignore[assignment]

    if gcp_exceptions is not None and isinstance(  # noqa: UP038
        exc,
        (
            gcp_exceptions.TooManyRequests,
            gcp_exceptions.ServiceUnavailable,
            gcp_exceptions.DeadlineExceeded,
            gcp_exceptions.InternalServerError,
            gcp_exceptions.GatewayTimeout,
            gcp_exceptions.Aborted,
            gcp_exceptions.ResourceExhausted,
        ),
    ):
        return True

    status = getattr(exc, "code", None)
    if callable(status):
        try:
            status = status()
        except Exception:  # noqa: BLE001
            status = None
    if isinstance(status, int) and status in {429, 500, 502, 503, 504}:
        return True
    grpc_status = getattr(exc, "status_code", None)
    if isinstance(grpc_status, int) and grpc_status in {429, 500, 502, 503, 504}:
        return True
    return False


def parse_prediction(raw: Any) -> tuple[str, float]:
    """Turn one Vertex prediction payload into ``(label, score)``.

    Accepted shapes (greedy / argmax, never sampled):

    * ``{"label": "pos", "score": 0.91}``
    * ``{"label": "LABEL_2", "score": 0.91}``
    * a list of ``{"label", "score"}`` dicts — highest score wins
    * a list/tuple of three numbers ``[neg, neu, pos]`` — argmax after
      a numerically stable softmax
    * a plain label string

    Args:
        raw: One element of ``Endpoint.predict(...).predictions``.

    Returns:
        Pipeline label and confidence in ``0..1``.

    Raises:
        ValueError: If the payload cannot be mapped. Callers must not
            swallow this into ``neu``.
    """
    if isinstance(raw, str):
        return normalize_predicted_label(raw), 1.0

    if isinstance(raw, dict):
        label_raw = raw.get("label", raw.get("sentiment"))
        score_raw = raw.get("score", raw.get("confidence", raw.get("probability")))
        if label_raw is not None:
            score = _coerce_score(score_raw, default=1.0)
            return normalize_predicted_label(str(label_raw)), score
        scores = raw.get("scores")
        if isinstance(scores, list | tuple) and scores:
            return _from_score_vector(scores)

    if isinstance(raw, list | tuple) and raw:
        if all(isinstance(item, dict) for item in raw):
            best: tuple[str, float] | None = None
            for item in raw:
                label, score = parse_prediction(item)
                if best is None or score > best[1]:
                    best = (label, score)
            if best is not None:
                return best
        if all(isinstance(item, int | float) for item in raw):
            return _from_score_vector(raw)

    raise ValueError(f"Unsupported Vertex prediction payload: {raw!r}")


def _from_score_vector(scores: list[Any] | tuple[Any, ...]) -> tuple[str, float]:
    """Argmax a 3-logit or 3-prob vector in ``neg, neu, pos`` order.

    Args:
        scores: Three numbers.

    Returns:
        Label and softmax probability of the winning class.

    Raises:
        ValueError: If the vector is not length 3.
    """
    values = [float(x) for x in scores]
    if len(values) != 3:
        raise ValueError(f"Expected 3 class scores, got {len(values)}: {values}")
    # Stable softmax so a raw-logit head and a already-normalised head
    # both yield a score in 0..1.
    peak = max(values)
    exps = [math.exp(v - peak) for v in values]
    total = sum(exps) or 1.0
    probs = [e / total for e in exps]
    winner = max(range(3), key=lambda i: probs[i])
    return ID2LABEL[winner], probs[winner]


def _coerce_score(raw: Any, *, default: float) -> float:
    """Clamp a model score into ``0..1``.

    Args:
        raw: Value from the payload, or ``None``.
        default: Used when ``raw`` is missing.

    Returns:
        A float in ``0..1``.

    Raises:
        ValueError: If ``raw`` is present but not a number in range.
    """
    if raw is None:
        return default
    score = float(raw)
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"score must be within 0..1, got {score}")
    return score


class VertexEndpointClassifier:
    """SentimentClassifier backed by ``Endpoint.predict``."""

    def __init__(
        self,
        *,
        endpoint_id: str | None = None,
        project: str | None = None,
        location: str | None = None,
        endpoint: PredictEndpoint | None = None,
        model_version: str | None = None,
    ) -> None:
        """Read config from arguments or the process environment.

        Args:
            endpoint_id: Vertex endpoint id or resource name. Defaults to
                ``VERTEX_ENDPOINT_ID``.
            project: GCP project. Defaults to ``VERTEX_PROJECT``.
            location: Region. Defaults to ``VERTEX_LOCATION`` or
                ``europe-central2``.
            endpoint: Injected client (tests). When omitted, a real
                ``aiplatform.Endpoint`` is constructed.
            model_version: Override written to ``Sentiment.model_version``.

        Raises:
            RuntimeError: If endpoint id or project is missing.
        """
        resolved_id = (endpoint_id or os.environ.get(_ENV_ENDPOINT) or "").strip()
        resolved_project = (project or os.environ.get(_ENV_PROJECT) or "").strip()
        resolved_location = (
            location or os.environ.get(_ENV_LOCATION) or _DEFAULT_LOCATION
        ).strip()
        if not resolved_id or not resolved_project:
            raise RuntimeError(
                f"{_ENV_ENDPOINT} and {_ENV_PROJECT} must be set (got "
                f"endpoint_id={resolved_id!r}, project={resolved_project!r})."
            )
        self._endpoint_id = resolved_id
        self._project = resolved_project
        self._location = resolved_location
        self._model_version_override = model_version
        self._deployed_model_id = ""
        if endpoint is not None:
            self._endpoint = endpoint
        else:
            import google.cloud.aiplatform as aiplatform  # type: ignore[import-untyped, attr-defined, unused-ignore]

            aiplatform.init(project=resolved_project, location=resolved_location)
            self._endpoint = aiplatform.Endpoint(endpoint_name=resolved_id)

    @property
    def model_version(self) -> str:
        """Identifier written to the ``model_version`` column."""
        if self._model_version_override:
            return self._model_version_override
        if self._deployed_model_id:
            return f"vertex/{self._deployed_model_id}"
        return f"vertex/{self._endpoint_id}"

    def classify(self, text: str) -> Sentiment:
        """Classify one text.

        Args:
            text: Comment or review body. May be empty.

        Returns:
            The classification result.
        """
        return self.classify_batch([text])[0]

    def classify_batch(self, texts: list[str]) -> list[Sentiment]:
        """Classify a batch with one ``Endpoint.predict`` call.

        Args:
            texts: Texts to classify, in order.

        Returns:
            One result per input, in the same order.

        Raises:
            RuntimeError: If the endpoint returns the wrong count, or
                retries are exhausted. Beam then retries the bundle —
                we do not invent ``neu``.
        """
        if not texts:
            return []
        instances = [{"text": text} for text in texts]
        response = self._predict(instances)
        predictions = list(getattr(response, "predictions", None) or [])
        if len(predictions) != len(texts):
            raise RuntimeError(
                f"Vertex Endpoint returned {len(predictions)} predictions "
                f"for {len(texts)} texts (endpoint={self._endpoint_id})."
            )
        deployed = str(getattr(response, "deployed_model_id", "") or "")
        if deployed:
            self._deployed_model_id = deployed
        results: list[Sentiment] = []
        for raw in predictions:
            label, score = parse_prediction(raw)
            if label not in LABELS:
                raise RuntimeError(f"Endpoint returned non-pipeline label {label!r}.")
            results.append(Sentiment(label, score, self.model_version))
        return results

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1.0, max=30.0),
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        reraise=True,
    )
    def _predict(self, instances: list[dict[str, str]]) -> Any:
        """Call ``Endpoint.predict`` with timeout and tenacity retry.

        Args:
            instances: Vertex instances.

        Returns:
            The predict response.

        Raises:
            Exception: After ``_MAX_ATTEMPTS`` retries the last error is
                re-raised so the worker fails the bundle.
        """
        try:
            return self._endpoint.predict(
                instances=instances, timeout=_PREDICT_TIMEOUT_SECONDS
            )
        except TypeError:
            # Injected test doubles (and some mock signatures) do not
            # accept timeout=.
            return self._endpoint.predict(instances)
