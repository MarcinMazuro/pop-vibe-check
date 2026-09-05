"""Sentiment classification for the pop-vibe-check pipeline.

Exposes the classifier contract (:mod:`nlp.base`) and a registry
(:func:`load_classifier`) that resolves a classifier by name. The Dataflow
pipeline depends on the contract and the registry only — never on a
concrete implementation — so a real model replaces the stub without any
pipeline change.
"""

from nlp.base import LABELS, Sentiment, SentimentClassifier
from nlp.registry import load_classifier

__all__ = ["LABELS", "Sentiment", "SentimentClassifier", "load_classifier"]
