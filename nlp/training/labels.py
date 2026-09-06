"""Label maps for the hybrid DistilBERT fine-tune.

Every source dataset is reduced to the three classes written to
``events``: ``pos``, ``neu``, ``neg``. SST-2 is binary — it contributes
no ``neu`` rows. Twitter sources and the own-domain notes supply the
neutral class.

The integer ids stored with the Hugging Face model are::

    0 = neg, 1 = neu, 2 = pos

That order matches ``tweet_eval`` sentiment and is written into the
model config as ``id2label`` / ``label2id`` so the Vertex serving
container returns the same strings the pipeline expects.
"""

from __future__ import annotations

from dataclasses import dataclass

from nlp.base import LABELS

MODEL_NAME = "distilbert-base-uncased"
MAX_LEN = 128

# GoEmotions (Reddit comments, open access) → three-class sentiment.
# Used as the own-domain substitute while the project Reddit collector
# has no credentials. Multi-label rows: any negative emotion wins over
# positive; neither → neu.
_GOEMOTIONS_POS: frozenset[str] = frozenset(
    {
        "admiration",
        "amusement",
        "approval",
        "caring",
        "desire",
        "excitement",
        "gratitude",
        "joy",
        "love",
        "optimism",
        "pride",
        "relief",
    }
)
_GOEMOTIONS_NEG: frozenset[str] = frozenset(
    {
        "anger",
        "annoyance",
        "disappointment",
        "disapproval",
        "disgust",
        "embarrassment",
        "fear",
        "grief",
        "nervousness",
        "remorse",
        "sadness",
    }
)


@dataclass(frozen=True)
class LabeledText:
    """One training example after source labels have been mapped.

    Attributes:
        text: Raw comment or sentence.
        label: One of ``pos``, ``neu``, ``neg``.
        source: Short dataset id (``sst2``, ``tweet_eval``,
            ``sentiment140``, ``goemotions``, ``own_domain``).
    """

    text: str
    label: str
    source: str

    def __post_init__(self) -> None:
        """Reject labels outside the pipeline's three-class space.

        Raises:
            ValueError: If ``label`` is not in :data:`nlp.base.LABELS`.
        """
        if self.label not in LABELS:
            raise ValueError(f"label must be one of {LABELS}, got '{self.label}'.")


def map_sst2_label(idx: int) -> str:
    """Map a GLUE SST-2 integer label to ``pos`` or ``neg``.

    SST-2 has no neutral class. Callers must not invent ``neu`` for
    these rows — they train only the positive/negative head.

    Args:
        idx: ``0`` (negative) or ``1`` (positive).

    Returns:
        ``neg`` or ``pos``.

    Raises:
        ValueError: If ``idx`` is not 0 or 1.
    """
    mapping = {0: "neg", 1: "pos"}
    try:
        return mapping[idx]
    except KeyError:
        raise ValueError(f"SST-2 label must be 0 or 1, got {idx}.") from None


def map_tweet_eval_label(idx: int) -> str:
    """Map a ``tweet_eval`` sentiment integer to ``pos`` / ``neu`` / ``neg``.

    Args:
        idx: ``0`` negative, ``1`` neutral, ``2`` positive.

    Returns:
        The corresponding pipeline label.

    Raises:
        ValueError: If ``idx`` is outside 0..2.
    """
    mapping = {0: "neg", 1: "neu", 2: "pos"}
    try:
        return mapping[idx]
    except KeyError:
        raise ValueError(f"tweet_eval label must be 0, 1 or 2, got {idx}.") from None


def map_sentiment140_label(idx: int) -> str:
    """Map a Sentiment140 polarity value to a pipeline label.

    The original release uses ``0`` (neg) and ``4`` (pos). Some redistributions
    insert ``2`` for neutral; it is mapped when present.

    Args:
        idx: ``0``, ``2``, or ``4``.

    Returns:
        The corresponding pipeline label.

    Raises:
        ValueError: If ``idx`` is not a Sentiment140 polarity.
    """
    mapping = {0: "neg", 2: "neu", 4: "pos"}
    try:
        return mapping[idx]
    except KeyError:
        raise ValueError(f"Sentiment140 label must be 0, 2 or 4, got {idx}.") from None


def map_goemotions_labels(emotions: list[str]) -> str:
    """Collapse GoEmotions multi-label emotions to one sentiment class.

    Negative emotions win ties against positive ones so sarcasm-adjacent
    Reddit rows do not get counted as praise. Rows with neither set
    become ``neu`` (including the dataset's own ``neutral`` tag).

    Args:
        emotions: Emotion names on one example (already decoded from ids).

    Returns:
        ``neg``, ``pos``, or ``neu``.
    """
    names = {name.lower() for name in emotions}
    has_neg = bool(names & _GOEMOTIONS_NEG)
    has_pos = bool(names & _GOEMOTIONS_POS)
    if has_neg and not has_pos:
        return "neg"
    if has_pos and not has_neg:
        return "pos"
    if has_neg and has_pos:
        return "neg"
    return "neu"
