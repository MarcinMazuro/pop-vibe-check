"""In-repo catalog of trained sentiment checkpoints.

Dataflow still loads a classifier through :mod:`nlp.registry` (``stub`` /
``vertex``). This module records Hugging Face exports, gold-holdout
metrics, and which artifact is selected for a later Vertex upload. It
does not upload to Vertex Model Registry or change ``--nlp_model``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HoldoutMetrics:
    """Gold holdout numbers used to compare model versions.

    Attributes:
        n: Holdout row count.
        accuracy: Holdout accuracy.
        macro_f1: Holdout macro-F1.
        f1_neg: Holdout F1 for ``neg``.
        gold_path: Gold JSONL scored for these numbers.
        report_path: Evaluate report that contains the slice.
        en_n: EN holdout row count, if reported.
        en_macro_f1: EN holdout macro-F1, if reported.
    """

    n: int
    accuracy: float
    macro_f1: float
    f1_neg: float
    gold_path: str
    report_path: str
    en_n: int | None = None
    en_macro_f1: float | None = None


@dataclass(frozen=True)
class TrainedSentimentModel:
    """One trained export recorded in the in-repo catalog.

    Attributes:
        model_id: Stable catalog id (matches GCS prefix / display name).
        family: Encoder family (``distilbert`` or ``xlm-roberta``).
        version: Human version label (``v1``, ``v2``, ``v2.1``).
        display_name: Vertex / GCS display name.
        artifact_uri: GCS prefix of the Hugging Face export.
        base_checkpoint: Hub id or previous export this run started from.
        trained_at: ISO date (UTC) of the training or eval snapshot.
        docs: Paths to recipe / evaluation docs.
        holdout: Primary holdout metrics for version comparison.
        selected: Whether this artifact is the current serving candidate.
        vertex_model_resource: Vertex Model Registry resource name, if uploaded.
        vertex_endpoint_resource: Vertex Endpoint resource name, if deployed.
        train_epochs: Fine-tune epochs, if known.
        train_steps: Trainer ``global_step``, if known.
        train_loss: Reported training loss, if known.
        best_dev_macro_f1: Gold-dev macro-F1 of the selected checkpoint.
    """

    model_id: str
    family: str
    version: str
    display_name: str
    artifact_uri: str
    base_checkpoint: str
    trained_at: str
    docs: tuple[str, ...]
    holdout: HoldoutMetrics
    selected: bool = False
    vertex_model_resource: str | None = None
    vertex_endpoint_resource: str | None = None
    train_epochs: int | None = None
    train_steps: int | None = None
    train_loss: float | None = None
    best_dev_macro_f1: float | None = None


# DistilBERT v1 gold.jsonl holdout — nlp/eval/artifacts/report.json.
_DISTILBERT_V1 = TrainedSentimentModel(
    model_id="distilbert-sent",
    family="distilbert",
    version="v1",
    display_name="distilbert-sent",
    artifact_uri="gs://co-tf-artifacts-dev/nlp/models/distilbert-sent/",
    base_checkpoint="distilbert-base-uncased",
    trained_at="2026-09-12",
    docs=(
        "docs/phase-1-nlp-evaluation-distilbert-v1.md",
        "docs/phase-1-nlp-vertex-dev.md",
    ),
    holdout=HoldoutMetrics(
        n=80,
        accuracy=0.525,
        macro_f1=0.4980788359891557,
        f1_neg=0.45454545454545453,
        gold_path="nlp/eval/artifacts/gold.jsonl",
        report_path="nlp/eval/artifacts/report.json",
    ),
    vertex_model_resource=(
        "projects/891032629527/locations/europe-central2/models/6682862459948105728"
    ),
)

# XLM-R v2 rescore on the expanded gold_v3 holdout (same 200 rows as v2.1).
_XLMR_V2 = TrainedSentimentModel(
    model_id="xlmr-sent",
    family="xlm-roberta",
    version="v2",
    display_name="xlmr-sent",
    artifact_uri="gs://co-tf-artifacts-dev/nlp/models/xlmr-sent/",
    base_checkpoint="xlm-roberta-base",
    trained_at="2026-09-17",
    docs=(
        "docs/phase-1-nlp-evaluation-xlmr-v2.md",
        "docs/phase-1-nlp-multilingual-v2.md",
        "docs/phase-1-nlp-xlmr-v2.1-continued.md",
    ),
    holdout=HoldoutMetrics(
        n=200,
        accuracy=0.59,
        macro_f1=0.5681348236977818,
        f1_neg=0.48101265822784817,
        gold_path="nlp/eval/artifacts/gold_v3.jsonl",
        report_path="nlp/eval/artifacts/report-xlmr-v2-goldv3.json",
        en_n=55,
        en_macro_f1=0.6234567901234568,
    ),
    vertex_model_resource=(
        "projects/891032629527/locations/europe-central2/models/1068281099500650496"
    ),
)

# XLM-R v2.1 continued fine-tune. Workbench finished 2026-09-20T21:57:49Z.
_XLMR_V21 = TrainedSentimentModel(
    model_id="xlmr-sent-v2.1",
    family="xlm-roberta",
    version="v2.1",
    display_name="xlmr-sent-v2.1",
    artifact_uri="gs://co-tf-artifacts-dev/nlp/models/xlmr-sent-v2.1/",
    base_checkpoint="gs://co-tf-artifacts-dev/nlp/models/xlmr-sent/",
    trained_at="2026-09-20",
    docs=("docs/phase-1-nlp-xlmr-v2.1-continued.md",),
    holdout=HoldoutMetrics(
        n=200,
        accuracy=0.63,
        macro_f1=0.6001623117835456,
        f1_neg=0.48484848484848486,
        gold_path="nlp/eval/artifacts/gold_v3.jsonl",
        report_path="nlp/eval/artifacts/report-xlmr-v2.1-goldv3.json",
        en_n=55,
        en_macro_f1=0.677498252969951,
    ),
    selected=True,
    vertex_model_resource=(
        "projects/891032629527/locations/europe-central2/models/406814904230608896"
    ),
    vertex_endpoint_resource=(
        "projects/891032629527/locations/europe-central2/endpoints/co-nlp-endpoint-dev"
    ),
    train_epochs=3,
    train_steps=2379,
    train_loss=0.3938329375155987,
    best_dev_macro_f1=0.5381118881118881,
)

_MODELS: tuple[TrainedSentimentModel, ...] = (
    _DISTILBERT_V1,
    _XLMR_V2,
    _XLMR_V21,
)


def list_models() -> tuple[TrainedSentimentModel, ...]:
    """Return every catalogued checkpoint, in registration order.

    Returns:
        DistilBERT v1, XLM-R v2, then XLM-R v2.1.
    """
    return _MODELS


def get_model(model_id: str) -> TrainedSentimentModel:
    """Look up a catalogued checkpoint.

    Args:
        model_id: Catalog id such as ``xlmr-sent-v2.1``.

    Returns:
        The matching entry.

    Raises:
        KeyError: If ``model_id`` is not in the catalog.
    """
    for model in _MODELS:
        if model.model_id == model_id:
            return model
    known = ", ".join(item.model_id for item in _MODELS)
    raise KeyError(f"Unknown trained model '{model_id}'. Catalogued: {known}.")


def selected_model() -> TrainedSentimentModel:
    """Return the unique selected (champion) artifact.

    Returns:
        The entry with ``selected=True``.

    Raises:
        RuntimeError: If zero or several entries are marked selected.
    """
    chosen = [model for model in _MODELS if model.selected]
    if len(chosen) != 1:
        raise RuntimeError(
            f"Expected exactly one selected trained model, found {len(chosen)}."
        )
    return chosen[0]
