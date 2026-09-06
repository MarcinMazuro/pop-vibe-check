"""The classifier contract shared by the pipeline and every model.

This module is the seam described in the project's binding decision that
NLP starts as a stub and is later replaced through the model registry
"without touching surrounding code". The Dataflow pipeline imports
:class:`SentimentClassifier` and :class:`Sentiment` and nothing else, so
swapping the stub for a real model is a registry change, not a pipeline
change.

Two rules any implementation must honour:

1. **Determinism.** The same text must yield the same label and score on
   every call and in every process. The project guarantees that replaying
   the same data twice produces an identical set of rows in ``events``; a
   classifier that varies between runs breaks that guarantee. Models with
   sampling or dropout at inference must disable it.
2. **Total function.** :meth:`SentimentClassifier.classify` must return a
   result for any input, including empty or whitespace-only text. Records
   that cannot be classified are still valid records; only records that
   cannot be *parsed* go to the dead-letter path, and that decision is
   made upstream of the classifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# The three sentiment classes written to the events table. Any
# implementation maps its own label space onto exactly these.
LABELS: tuple[str, str, str] = ("pos", "neu", "neg")

# DistilBERT head ids used at train and serve time. Order matches
# tweet_eval sentiment (0=neg, 1=neu, 2=pos) so a checkpoint served
# without our id2label still maps LABEL_0/1/2 in a documented way.
LABEL2ID: dict[str, int] = {"neg": 0, "neu": 1, "pos": 2}
ID2LABEL: dict[int, str] = {index: label for label, index in LABEL2ID.items()}

# Serving-time aliases from Hugging Face / Vertex prediction payloads.
_HF_LABEL_TO_SENTIMENT: dict[str, str] = {
    "label_0": "neg",
    "label_1": "neu",
    "label_2": "pos",
    "negative": "neg",
    "neutral": "neu",
    "positive": "pos",
    "neg": "neg",
    "neu": "neu",
    "pos": "pos",
}


def normalize_predicted_label(raw: str) -> str:
    """Map a serving-time label string onto ``pos`` / ``neu`` / ``neg``.

    Args:
        raw: Label from a Vertex prediction (``pos``, ``LABEL_2``,
            ``positive``, …).

    Returns:
        A pipeline label.

    Raises:
        ValueError: If ``raw`` cannot be mapped.
    """
    key = raw.strip().lower()
    if key in _HF_LABEL_TO_SENTIMENT:
        return _HF_LABEL_TO_SENTIMENT[key]
    raise ValueError(f"Cannot map predicted label '{raw}' onto {LABELS}.")


@dataclass(frozen=True)
class Sentiment:
    """One classification result.

    Attributes:
        label: One of :data:`LABELS`.
        score: Model confidence in ``label``, in the closed range 0..1.
        model_version: Identifier of the model that produced this result,
            written to the ``model_version`` column. The stub uses a
            versioned identifier (``stub/1``); the Vertex client writes
            ``vertex/<deployed-model-id>`` so rows stay traceable to a
            Model Registry version.
    """

    label: str
    score: float
    model_version: str

    def __post_init__(self) -> None:
        """Validate the label and score ranges.

        Raises:
            ValueError: If ``label`` is not one of :data:`LABELS` or
                ``score`` falls outside 0..1.
        """
        if self.label not in LABELS:
            raise ValueError(f"label must be one of {LABELS}, got '{self.label}'.")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be within 0..1, got {self.score}.")


@runtime_checkable
class SentimentClassifier(Protocol):
    """Interface every sentiment model implements.

    Implementations are constructed once per worker process (in a Beam
    ``DoFn.setup``) and then called many times. Loading **weights** belongs
    in ``__init__`` and must not require the public internet — Dataflow
    workers have no public IPs and cannot reach PyPI or Hugging Face Hub.
    Calling a Google API (Vertex ``Endpoint.predict`` over Private Google
    Access) is allowed; baking a DistilBERT checkpoint into the Flex
    Template image is not how this project serves the model.
    """

    @property
    def model_version(self) -> str:
        """Identifier written to the ``model_version`` column."""
        ...

    def classify(self, text: str) -> Sentiment:
        """Classify one text.

        Args:
            text: The comment or review body. May be empty.

        Returns:
            The classification result.
        """
        ...

    def classify_batch(self, texts: list[str]) -> list[Sentiment]:
        """Classify a batch of texts.

        The pipeline always calls this, never :meth:`classify` directly,
        so a model with a batched forward pass gets one without any
        pipeline change. Implementations without batching may simply map
        :meth:`classify` over the input.

        Args:
            texts: Texts to classify, in order.

        Returns:
            One result per input, in the same order.
        """
        ...
