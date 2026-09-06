r"""Fine-tune DistilBERT-base-uncased for three-class sentiment.

Run this on Vertex AI Workbench with a T4, not on a Dataflow worker and
not from CI. Hugging Face / torch are imported inside :func:`main` so
``nlp.training.labels`` stays importable without those packages.

Example (Workbench, after rsyncing the dataset cache)::

    python -m nlp.training.train \\
        --cache-dir /home/jupyter/hf-datasets \\
        --output-dir /home/jupyter/models/distilbert-sent \\
        --own-domain /home/jupyter/gold/own_domain.jsonl
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

from nlp.base import ID2LABEL, LABEL2ID
from nlp.training.labels import MAX_LEN, MODEL_NAME, LabeledText
from nlp.training.loaders import (
    DEFAULT_GCS_DATASETS_URI,
    load_goemotions,
    load_own_domain,
    load_sst2,
    load_twitter,
    mix_corpus,
)

logger = logging.getLogger(__name__)

DEFAULT_LR = 2e-5
DEFAULT_EPOCHS = 3
DEFAULT_BATCH = 16
DEFAULT_SEED = 33


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


def tokenize_dataset(dataset: Any, tokenizer: Any) -> Any:
    """Tokenize ``text`` with truncation at :data:`MAX_LEN`.

    Args:
        dataset: Hugging Face dataset with a ``text`` column.
        tokenizer: DistilBERT tokenizer.

    Returns:
        The tokenized dataset (batched).
    """

    def _tokenize(batch: dict[str, list[str]]) -> Any:
        return tokenizer(
            batch["text"],
            truncation=True,
            padding="max_length",
            max_length=MAX_LEN,
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
        "--own-domain",
        default=None,
        help="Optional JSONL of hand-labelled YouTube / gold rows.",
    )
    parser.add_argument(
        "--skip-goemotions",
        action="store_true",
        help="Do not load the Reddit-comment substitute.",
    )
    parser.add_argument("--output-dir", default="./distilbert-sent")
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--lr", type=float, default=DEFAULT_LR)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--mlflow-uri",
        default=None,
        help="MLflow tracking URI. Defaults to gs://co-tf-artifacts-dev/nlp/mlruns.",
    )
    parser.add_argument(
        "--skip-mlflow",
        action="store_true",
        help="Train without logging (offline smoke test).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Load the hybrid corpus, fine-tune DistilBERT, log to MLflow.

    Args:
        argv: CLI arguments.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)

    parts = [
        load_sst2(cache_dir=args.cache_dir),
        load_twitter(cache_dir=args.cache_dir, seed=args.seed),
    ]
    if not args.skip_goemotions:
        parts.append(load_goemotions(cache_dir=args.cache_dir))
    if args.own_domain:
        parts.append(load_own_domain(args.own_domain))
    rows = mix_corpus(parts)
    logger.info("Hybrid corpus: %d examples.", len(rows))

    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    set_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME,
        num_labels=len(LABEL2ID),
        id2label={str(k): v for k, v in ID2LABEL.items()},
        label2id=LABEL2ID,
    )

    dataset = examples_to_hf_dataset(rows)
    split = dataset.train_test_split(test_size=0.1, seed=args.seed)
    train_ds = tokenize_dataset(split["train"], tokenizer)
    eval_ds = tokenize_dataset(split["test"], tokenizer)
    train_ds.set_format("torch", columns=["input_ids", "attention_mask", "label"])
    eval_ds.set_format("torch", columns=["input_ids", "attention_mask", "label"])

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(output_dir / "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.lr,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        seed=args.seed,
        fp16=True,
        report_to=[],
    )

    def _compute_metrics(eval_pred: Any) -> dict[str, float]:
        import numpy as np

        from nlp.eval.evaluate import classification_metrics

        logits, labels = eval_pred
        pred_ids = np.argmax(logits, axis=-1)
        pred_labels = [ID2LABEL[int(i)] for i in pred_ids]
        gold_labels = [ID2LABEL[int(i)] for i in labels]
        return classification_metrics(gold_labels, pred_labels)

    trainer = Trainer(
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
            experiment="distilbert-sentiment",
        )
        log_params(
            {
                "model": MODEL_NAME,
                "max_len": MAX_LEN,
                "lr": args.lr,
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "seed": args.seed,
                "n_examples": len(rows),
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
