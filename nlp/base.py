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

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# Social-media noise shared by train / eval / serve. Handles are Twitter-
# style ``@name`` tokens, not the local-part of an email (lookbehind).
_HANDLE_RE = re.compile(r"(?<![A-Za-z0-9_])@[A-Za-z0-9_]+")
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")

# The three sentiment classes written to the events table. Any
# implementation maps its own label space onto exactly these.
LABELS: tuple[str, str, str] = ("pos", "neu", "neg")

# Classification-head ids used at train and serve time. Order matches
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


def normalize_text(text: str) -> str:
    """Collapse noisy social-media tokens to a stable training form.

    Replaces ``@handle`` mentions with ``@user``, URLs with ``http``,
    non-breaking spaces (U+00A0) and repeated whitespace with a
    single space, then strips ends. Training loaders, gold eval, and the
    serving client all call this so the three paths see the same
    distribution.

    Args:
        text: Raw comment or review body. May be empty.

    Returns:
        The normalised string. Whitespace-only input becomes ``""``.
    """
    collapsed = text.replace("\xa0", " ")
    collapsed = _URL_RE.sub("http", collapsed)
    collapsed = _HANDLE_RE.sub("@user", collapsed)
    collapsed = _WHITESPACE_RE.sub(" ", collapsed)
    return collapsed.strip()


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
    Access) is allowed; baking a checkpoint into the Flex Template image
    is not how this project serves the model.
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
