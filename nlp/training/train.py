r"""Fine-tune XLM-RoBERTa-base for three-class multilingual sentiment.

Run this on Vertex AI Workbench (CPU-only), not on a
Dataflow worker and not from CI. Hugging Face / torch are imported inside
:func:`main` so ``nlp.training.labels`` stays importable without those
packages.

Example (Workbench, after rsyncing the dataset cache)::

    python -m nlp.training.train \\
        --cache-dir /home/jupyter/hf-datasets \\
        --output-dir /home/jupyter/models/xlmr-sent \\
        --batch-size 8 \\
        --own-domain /home/jupyter/gold/gold.jsonl
"""

from __future__ import annotations

import argparse
import inspect
import logging
import os
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from nlp.base import ID2LABEL, LABEL2ID
from nlp.training.labels import (
    MAX_LEN,
    MODEL_NAME,
    LabeledText,
    inverse_frequency_weights,
)
from nlp.training.loaders import (
    DEFAULT_GCS_DATASETS_URI,
    GOEMOTIONS_TARGET,
    OWN_DOMAIN_OVERSAMPLE,
    TWEET_EVAL_TARGET,
    load_v2_corpus,
)

logger = logging.getLogger(__name__)

DEFAULT_LR = 2e-5
DEFAULT_EPOCHS = 3
DEFAULT_BATCH = 8
DEFAULT_SEED = 33
DEFAULT_OUTPUT_DIR = "./xlmr-sent"
DEFAULT_EXPERIMENT = "xlmr-sentiment"


def fp16_enabled(cuda_available: bool | None = None) -> bool:
    """Return whether AMP fp16 should be enabled.

    Hugging Face ``TrainingArguments(fp16=True)`` raises on CPU because
    AMP is CUDA-only. Probe ``torch.cuda.is_available()`` unless the
    caller already knows.

    Args:
        cuda_available: Explicit CUDA probe result; ``None`` imports torch.

    Returns:
        ``True`` only when CUDA is available.
    """
    if cuda_available is None:
        import torch

        cuda_available = torch.cuda.is_available()
    return bool(cuda_available)


def stratified_indices(
    labels: Sequence[int],
    test_size: float,
    seed: int,
) -> tuple[list[int], list[int]]:
    """Split indices so each class appears in train and eval when possible.

    Args:
        labels: Integer class ids, one per example.
        test_size: Fraction assigned to eval (0..1).
        seed: RNG seed.

    Returns:
        ``(train_indices, eval_indices)``.
    """
    rng = random.Random(seed)
    by_class: dict[int, list[int]] = {}
    for index, label in enumerate(labels):
        by_class.setdefault(int(label), []).append(index)

    train: list[int] = []
    eval_idx: list[int] = []
    for idxs in by_class.values():
        shuffled = list(idxs)
        rng.shuffle(shuffled)
        n_test = int(round(len(shuffled) * test_size))
        if n_test <= 0 and len(shuffled) > 1:
            n_test = 1
        if n_test >= len(shuffled):
            n_test = max(0, len(shuffled) - 1)
        eval_idx.extend(shuffled[:n_test])
        train.extend(shuffled[n_test:])
    rng.shuffle(train)
    rng.shuffle(eval_idx)
    return train, eval_idx


def examples_to_hf_dataset(rows: list[LabeledText]) -> Any:
    """Build a Hugging Face ``Dataset`` from mapped examples.

    Args:
        rows: Labelled texts.

    Returns:
        A ``datasets.Dataset`` with ``text`` and ``label`` (int) columns.
    """
    from datasets import Dataset

    return Dataset.from_dict(
        {
            "text": [row.text for row in rows],
            "label": [LABEL2ID[row.label] for row in rows],
            "source": [row.source for row in rows],
        }
    )


def tokenize_dataset(dataset: Any, tokenizer: Any, max_len: int = MAX_LEN) -> Any:
    """Tokenize ``text`` with truncation at ``max_len``.

    Args:
        dataset: Hugging Face dataset with a ``text`` column.
        tokenizer: Hugging Face tokenizer.
        max_len: Maximum sequence length.

    Returns:
        The tokenized dataset (batched).
    """

    def _tokenize(batch: dict[str, list[str]]) -> Any:
        return tokenizer(
            batch["text"],
            truncation=True,
            padding="max_length",
            max_length=max_len,
        )

    return dataset.map(_tokenize, batched=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list; defaults to ``sys.argv[1:]``.

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        default=None,
        help=(
            "Local Hugging Face datasets cache. On Workbench, rsync "
            f"{DEFAULT_GCS_DATASETS_URI} here first."
        ),
    )
    parser.add_argument(
        "--model-cache-dir",
        default=None,
        help=(
            "Hugging Face Hub cache for base-model weights. Defaults to "
            "HF_HUB_CACHE when set."
        ),
    )
    parser.add_argument(
        "--model-name",
        default=MODEL_NAME,
        help=f"Hugging Face model id. Default {MODEL_NAME}.",
    )
    parser.add_argument(
        "--own-domain",
        default=None,
        help="Optional JSONL of hand-labelled YouTube / gold rows.",
    )
    parser.add_argument(
        "--own-domain-factor",
        type=int,
        default=OWN_DOMAIN_OVERSAMPLE,
        help="Repeat count for gold train rows (holdout is skipped).",
    )
    parser.add_argument(
        "--skip-goemotions",
        action="store_true",
        help="Do not load the Reddit-comment substitute.",
    )
    parser.add_argument(
        "--skip-clapai",
        action="store_true",
        help="Do not load the clapAI multilingual subsample.",
    )
    parser.add_argument(
        "--skip-tweet-ml",
        action="store_true",
        help="Do not load CardiffNLP multilingual tweets.",
    )
    parser.add_argument(
        "--skip-tweet-eval",
        action="store_true",
        help="Do not load English tweet_eval.",
    )
    parser.add_argument(
        "--include-sst2",
        action="store_true",
        help="Append GLUE SST-2 (v1 leftover; off by default).",
    )
    parser.add_argument(
        "--include-sentiment140",
        action="store_true",
        help="Append a Sentiment140 sample (v1 leftover; off by default).",
    )
    parser.add_argument(
        "--tweet-eval-target",
        type=int,
        default=TWEET_EVAL_TARGET,
        help=f"Cap for downsampled tweet_eval. Default {TWEET_EVAL_TARGET}.",
    )
    parser.add_argument(
        "--goemotions-target",
        type=int,
        default=GOEMOTIONS_TARGET,
        help=f"Cap for downsampled GoEmotions. Default {GOEMOTIONS_TARGET}.",
    )
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--lr", type=float, default=DEFAULT_LR)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--num-workers",
        type=int,
        default=2,
        help="DataLoader workers. Use 0 if Workbench forks misbehave.",
    )
    parser.add_argument(
        "--mlflow-uri",
        default=None,
        help="MLflow tracking URI. Defaults to gs://co-tf-artifacts-dev/nlp/mlruns.",
    )
    parser.add_argument(
        "--mlflow-experiment",
        default=DEFAULT_EXPERIMENT,
        help=f"MLflow experiment name. Default {DEFAULT_EXPERIMENT}.",
    )
    parser.add_argument(
        "--skip-mlflow",
        action="store_true",
        help="Train without logging (offline smoke test).",
    )
    parser.add_argument(
        "--no-class-weights",
        action="store_true",
        help="Uniform CrossEntropyLoss (v1 behaviour).",
    )
    return parser.parse_args(argv)


def _training_arguments(**kwargs: Any) -> Any:
    """Build ``TrainingArguments`` across transformers 4.40–4.x.

    Args:
        **kwargs: Fields shared by both API versions.

    Returns:
        A ``TrainingArguments`` instance.
    """
    from transformers import TrainingArguments

    params = inspect.signature(TrainingArguments.__init__).parameters
    strategy = kwargs.pop("eval_save_strategy", "epoch")
    if "eval_strategy" in params:
        kwargs["eval_strategy"] = strategy
    else:
        kwargs["evaluation_strategy"] = strategy
    kwargs.setdefault("save_strategy", strategy)
    return TrainingArguments(**kwargs)


def main(argv: list[str] | None = None) -> None:
    """Load the v2 corpus, fine-tune XLM-RoBERTa, log to MLflow.

    Args:
        argv: CLI arguments.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)

    # Workbench images ship TensorFlow + an old sklearn that imports
    # numpy.core.numeric.ComplexWarning, removed in NumPy 2. Disable TF
    # and restore the alias before Hugging Face imports Trainer.
    os.environ.setdefault("USE_TF", "0")
    import numpy.core.numeric as _numeric

    if not hasattr(_numeric, "ComplexWarning"):
        from numpy.exceptions import ComplexWarning as _ComplexWarning

        _numeric.ComplexWarning = _ComplexWarning

    rows = load_v2_corpus(
        cache_dir=args.cache_dir,
        seed=args.seed,
        own_domain=args.own_domain,
        skip_goemotions=args.skip_goemotions,
        skip_clapai=args.skip_clapai,
        skip_tweet_ml=args.skip_tweet_ml,
        skip_tweet_eval=args.skip_tweet_eval,
        include_sst2=args.include_sst2,
        include_sentiment140=args.include_sentiment140,
        tweet_eval_target=args.tweet_eval_target,
        goemotions_target=args.goemotions_target,
        own_domain_factor=args.own_domain_factor,
    )
    logger.info("Hybrid corpus: %d examples.", len(rows))

    import torch
    from torch.nn import CrossEntropyLoss
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        Trainer,
        set_seed,
    )

    cpu_count = os.cpu_count() or 1
    torch.set_num_threads(cpu_count)
    logger.info("torch.set_num_threads(%d)", cpu_count)

    set_seed(args.seed)
    model_name = args.model_name
    model_cache = args.model_cache_dir or os.environ.get("HF_HUB_CACHE")
    tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=model_cache)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        cache_dir=model_cache,
        num_labels=len(LABEL2ID),
        id2label={str(k): v for k, v in ID2LABEL.items()},
        label2id=LABEL2ID,
    )

    dataset = examples_to_hf_dataset(rows)
    train_idx, eval_idx = stratified_indices(dataset["label"], 0.1, args.seed)
    train_raw = dataset.select(train_idx)
    eval_raw = dataset.select(eval_idx)
    train_ds = tokenize_dataset(train_raw, tokenizer)
    eval_ds = tokenize_dataset(eval_raw, tokenizer)
    train_ds.set_format("torch", columns=["input_ids", "attention_mask", "label"])
    eval_ds.set_format("torch", columns=["input_ids", "attention_mask", "label"])

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    use_fp16 = fp16_enabled(torch.cuda.is_available())
    logger.info("Training device: cuda=%s fp16=%s", torch.cuda.is_available(), use_fp16)

    weights: list[float] | None = None
    if not args.no_class_weights:
        train_label_names = [ID2LABEL[int(i)] for i in train_raw["label"]]
        weights = inverse_frequency_weights(train_label_names)
        logger.info("Class weights (neg, neu, pos): %s", weights)

    training_args = _training_arguments(
        output_dir=str(output_dir / "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.lr,
        eval_save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        seed=args.seed,
        fp16=use_fp16,
        report_to=[],
        dataloader_num_workers=max(0, args.num_workers),
        dataloader_pin_memory=False,
    )

    class_weights_tensor = (
        torch.tensor(weights, dtype=torch.float32) if weights is not None else None
    )

    class WeightedTrainer(Trainer):
        """Cross-entropy with optional inverse-frequency class weights."""

        def compute_loss(
            self,
            model: Any,
            inputs: dict[str, Any],
            return_outputs: bool = False,
            **kwargs: Any,
        ) -> Any:
            labels = inputs["labels"]
            model_inputs = {
                key: value for key, value in inputs.items() if key != "labels"
            }
            outputs = model(**model_inputs)
            logits = outputs.logits
            weight = class_weights_tensor
            if weight is not None:
                weight = weight.to(device=logits.device, dtype=logits.dtype)
            loss = CrossEntropyLoss(weight=weight)(
                logits.view(-1, logits.size(-1)),
                labels.view(-1),
            )
            return (loss, outputs) if return_outputs else loss

    def _compute_metrics(eval_pred: Any) -> dict[str, float]:
        import numpy as np

        from nlp.eval.evaluate import classification_metrics

        logits, labels = eval_pred
        pred_ids = np.argmax(logits, axis=-1)
        pred_labels = [ID2LABEL[int(i)] for i in pred_ids]
        gold_labels = [ID2LABEL[int(i)] for i in labels]
        return classification_metrics(gold_labels, pred_labels)

    trainer = WeightedTrainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        compute_metrics=_compute_metrics,
    )

    run = None
    if not args.skip_mlflow:
        from nlp.tracking.mlflow_utils import log_params, start_run

        run = start_run(
            tracking_uri=args.mlflow_uri,
            experiment=args.mlflow_experiment,
        )
        log_params(
            {
                "model": model_name,
                "max_len": MAX_LEN,
                "lr": args.lr,
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "seed": args.seed,
                "n_examples": len(rows),
                "fp16": use_fp16,
                "class_weights": weights,
                "num_workers": args.num_workers,
            }
        )

    metrics = trainer.train()
    eval_metrics = trainer.evaluate()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    logger.info(
        "Saved model to %s. train=%s eval=%s", output_dir, metrics, eval_metrics
    )

    if run is not None:
        from nlp.tracking.mlflow_utils import end_run, log_metrics, log_weights

        flat = {
            k: float(v) for k, v in eval_metrics.items() if isinstance(v, int | float)
        }
        log_metrics(flat)
        log_weights(str(output_dir))
        end_run()


if __name__ == "__main__":
    main()
