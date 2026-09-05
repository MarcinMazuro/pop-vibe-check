"""Resolve a sentiment classifier by name.

The pipeline names the model it wants (``--nlp_model``) and this module
hands back an instance. Adding a real model means registering it here; the
pipeline is untouched.

Model weights must be present locally by the time this runs. Dataflow
workers launch without public IPs, so a classifier that downloads weights
on construction will hang until the worker times out — bake the weights
into the image instead.
"""

from __future__ import annotations

from collections.abc import Callable

from nlp.base import SentimentClassifier
from nlp.stub.classifier import StubClassifier

# Name -> factory. MLflow-backed models register alongside "stub" once the
# registry integration exists.
_FACTORIES: dict[str, Callable[[], SentimentClassifier]] = {
    "stub": StubClassifier,
}


def available_models() -> tuple[str, ...]:
    """Return the registered model names, sorted.

    Returns:
        The names accepted by :func:`load_classifier`.
    """
    return tuple(sorted(_FACTORIES))


def load_classifier(name: str = "stub") -> SentimentClassifier:
    """Construct the classifier registered under ``name``.

    Args:
        name: Registered model name.

    Returns:
        A ready-to-use classifier.

    Raises:
        KeyError: If no model is registered under ``name``. Failing here is
            deliberate — a typo in the launch parameter should stop the
            job at worker start-up, not silently label a whole replay with
            the wrong model.
    """
    try:
        factory = _FACTORIES[name]
    except KeyError:
        raise KeyError(
            f"Unknown NLP model '{name}'. Registered models: {available_models()}."
        ) from None
    return factory()
