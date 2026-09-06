"""Hybrid training data and DistilBERT fine-tune entry points.

Import :mod:`nlp.training.labels` from tests and CI — it has no Hugging
Face or torch dependency. :mod:`nlp.training.loaders` and
:mod:`nlp.training.train` pull those in only when actually downloading
or training, which happens on Vertex AI Workbench, not in the Dataflow
image.
"""

from nlp.base import ID2LABEL, LABEL2ID
from nlp.training.labels import (
    MAX_LEN,
    MODEL_NAME,
    LabeledText,
    map_goemotions_labels,
    map_sentiment140_label,
    map_sst2_label,
    map_tweet_eval_label,
)

__all__ = [
    "ID2LABEL",
    "LABEL2ID",
    "LabeledText",
    "MAX_LEN",
    "MODEL_NAME",
    "map_goemotions_labels",
    "map_sentiment140_label",
    "map_sst2_label",
    "map_tweet_eval_label",
]
