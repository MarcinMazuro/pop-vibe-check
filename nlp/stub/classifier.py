"""A deterministic rule-based stub classifier.

Its only job is to make the pipeline end-to-end testable before a real
model exists, and to be replaceable by one without a pipeline change.

**Why rule-based and not random.** The obvious stub is a coin flip, but a
random classifier would quietly break the project's reproducibility
guarantee: replaying the same data twice must produce an identical set of
rows in ``events``. A per-call random label makes that assertion fail for
reasons that have nothing to do with the pipeline, which is exactly the
kind of false signal a stub must not introduce. So this classifier is
deterministic: a small keyword rule with a hash-derived fallback that
depends only on the text.

Nothing here claims accuracy. The keyword lists are deliberately tiny and
English-only, and the fallback is arbitrary by construction — it exists to
spread unmatched text across all three labels so downstream aggregations,
charts, and the promotion MERGE see a realistic label distribution rather
than a single constant.
"""

from __future__ import annotations

import hashlib

from nlp.base import LABELS, Sentiment

# Version identifier written to the model_version column. Bump the suffix
# if the rules below change, so rows stay traceable to what produced them.
MODEL_VERSION = "stub/1"

# Confidence reported for a keyword match versus the hash fallback. Both
# are arbitrary but fixed: a matched rule is reported as more confident
# than a coin the text merely happened to land on.
MATCH_SCORE = 0.75
FALLBACK_SCORE = 0.34

_POSITIVE = frozenset(
    {
        "amazing",
        "awesome",
        "beautiful",
        "best",
        "brilliant",
        "excellent",
        "fantastic",
        "goty",
        "great",
        "incredible",
        "love",
        "loved",
        "masterpiece",
        "perfect",
        "peak",
        "stunning",
        "wonderful",
    }
)

_NEGATIVE = frozenset(
    {
        "awful",
        "bad",
        "boring",
        "broken",
        "bug",
        "bugged",
        "buggy",
        "crap",
        "disappointing",
        "garbage",
        "hate",
        "horrible",
        "refund",
        "terrible",
        "trash",
        "unplayable",
        "worst",
    }
)

# Characters stripped from token edges before matching, so "amazing!!!" and
# "(great)" still hit the keyword sets.
_STRIP = ".,!?;:\"'()[]{}<>*_~`-—…"


def _tokenize(text: str) -> list[str]:
    """Split text into lowercased, punctuation-stripped tokens.

    Args:
        text: Raw comment or review body.

    Returns:
        The non-empty tokens, lowercased.
    """
    return [token for token in (w.strip(_STRIP).lower() for w in text.split()) if token]


def _fallback_label(text: str) -> str:
    """Pick a label deterministically from the text itself.

    Uses a stable hash rather than :func:`hash`, whose per-process salt
    would make results differ between workers and between runs.

    Args:
        text: Raw comment or review body.

    Returns:
        One of :data:`nlp.base.LABELS`.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return LABELS[digest[0] % len(LABELS)]


class StubClassifier:
    """Deterministic keyword classifier standing in for a real model."""

    def __init__(self, model_version: str = MODEL_VERSION) -> None:
        """Initialise the stub.

        Args:
            model_version: Identifier reported on every result. Overridable
                so tests can assert the value is carried through rather
                than hardcoded downstream.
        """
        self._model_version = model_version

    @property
    def model_version(self) -> str:
        """Identifier written to the ``model_version`` column."""
        return self._model_version

    def classify(self, text: str) -> Sentiment:
        """Classify one text by keyword counts, falling back to a hash.

        Args:
            text: The comment or review body. May be empty.

        Returns:
            The classification result. Empty text is ``neu``; text whose
            positive and negative hits tie falls through to the hash.
        """
        if not text or not text.strip():
            return Sentiment("neu", FALLBACK_SCORE, self._model_version)

        tokens = _tokenize(text)
        positives = sum(1 for token in tokens if token in _POSITIVE)
        negatives = sum(1 for token in tokens if token in _NEGATIVE)

        if positives > negatives:
            return Sentiment("pos", MATCH_SCORE, self._model_version)
        if negatives > positives:
            return Sentiment("neg", MATCH_SCORE, self._model_version)

        return Sentiment(_fallback_label(text), FALLBACK_SCORE, self._model_version)

    def classify_batch(self, texts: list[str]) -> list[Sentiment]:
        """Classify a batch by mapping :meth:`classify` over it.

        The stub has no batched fast path; it implements the method so the
        pipeline can always call the batch form.

        Args:
            texts: Texts to classify, in order.

        Returns:
            One result per input, in the same order.
        """
        return [self.classify(text) for text in texts]
