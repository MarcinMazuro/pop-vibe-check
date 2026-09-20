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

Continued fine-tune (stage 2, from a v2 export)::

    python -m nlp.training.train \\
        --init-from /home/jupyter/models/xlmr-sent \\
        --own-domain /home/jupyter/gold/gold_v3.jsonl \\
        --own-domain-factor 2 \\
        --dev-from-gold /home/jupyter/gold/gold_v3.jsonl \\
        --replay-n 5000 \\
        --lr 1e-5 \\
        --epochs 3 \\
        --batch-size 8 \\
        --early-stopping-patience 2 \\
        --output-dir /home/jupyter/models/xlmr-sent-v2.1
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
    load_gold_split,
    load_own_domain,
    load_v2_corpus,
    oversample_rows,
    subsample_rows,
)

logger = logging.getLogger(__name__)

DEFAULT_LR = 2e-5
DEFAULT_EPOCHS = 3
DEFAULT_BATCH = 8
DEFAULT_SEED = 33
DEFAULT_OUTPUT_DIR = "./xlmr-sent"
DEFAULT_EXPERIMENT = "xlmr-sentiment"
DEFAULT_REPLAY_N = 5000
DEFAULT_WARMUP_RATIO = 0.1
DEFAULT_WEIGHT_DECAY = 0.01
DEFAULT_EARLY_STOPPING_PATIENCE = 0


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


def build_stage2_train_rows(
    gold_train: Sequence[LabeledText],
    replay_pool: Sequence[LabeledText],
    *,
    own_domain_factor: int,
    replay_n: int,
    seed: int,
) -> list[LabeledText]:
    """Combine oversampled gold train rows with a stratified replay subsample.

    Args:
        gold_train: Own-domain rows (already without dev/holdout).
        replay_pool: v2 mix used as the anti-forgetting source.
        own_domain_factor: Repeat count for gold.
        replay_n: Replay subsample size. ``0`` keeps gold only.
        seed: Subsample RNG seed.

    Returns:
        Concatenated training rows (gold copies first, then replay).
    """
    gold = oversample_rows(list(gold_train), own_domain_factor)
    if replay_n <= 0:
        return gold
    replay = subsample_rows(replay_pool, replay_n, seed=seed)
    return gold + replay


def assemble_train_rows(args: argparse.Namespace) -> list[LabeledText]:
    """Build the training pool for v2 or continued (stage-2) fine-tune.

    Without ``--init-from`` this is :func:`load_v2_corpus` (today's mix).
    With ``--init-from`` and ``--own-domain``, train is gold train rows
    oversampled by ``--own-domain-factor`` plus a stratified
    ``--replay-n`` subsample of the v2 mix. ``--replay-n 0`` is
    gold-only and does not download the mix.

    Args:
        args: Parsed CLI namespace.

    Returns:
        Mapped examples used as the training pool. Eval may still be
        carved out later unless ``--dev-from-gold`` is set.
    """
    if args.init_from:
        gold_train: list[LabeledText] = []
        if args.own_domain:
            gold_train = load_own_domain(args.own_domain)
        need_mix = args.replay_n > 0 or not gold_train
        replay_pool: list[LabeledText] = []
        if need_mix:
            replay_pool = load_v2_corpus(**_v2_corpus_kwargs(args, own_domain=None))
        if gold_train:
            return build_stage2_train_rows(
                gold_train,
                replay_pool,
                own_domain_factor=args.own_domain_factor,
                replay_n=args.replay_n,
                seed=args.seed,
            )
        if args.replay_n > 0:
            return subsample_rows(replay_pool, args.replay_n, seed=args.seed)
        return replay_pool
    return load_v2_corpus(**_v2_corpus_kwargs(args, own_domain=args.own_domain))


def split_train_eval(
    rows: Sequence[LabeledText],
    args: argparse.Namespace,
) -> tuple[list[LabeledText], list[LabeledText]]:
    """Choose train/eval lists, optionally from gold ``split==dev``.

    Args:
        rows: Training pool from :func:`assemble_train_rows`.
        args: Parsed CLI namespace.

    Returns:
        ``(train_rows, eval_rows)``.

    Raises:
        ValueError: If ``--dev-from-gold`` is set but that file has no
            ``split==dev`` rows, or if either split would be empty.
    """
    if args.dev_from_gold:
        eval_rows = load_gold_split(args.dev_from_gold, "dev")
        if not eval_rows:
            raise ValueError(f"{args.dev_from_gold} has no split==dev rows")
        train_rows = list(rows)
        if not train_rows:
            raise ValueError("training pool is empty")
        return train_rows, eval_rows
    pool = list(rows)
    labels = [LABEL2ID[row.label] for row in pool]
    train_idx, eval_idx = stratified_indices(labels, 0.1, args.seed)
    return [pool[i] for i in train_idx], [pool[i] for i in eval_idx]


def _v2_corpus_kwargs(
    args: argparse.Namespace,
    *,
    own_domain: str | None,
) -> dict[str, Any]:
    """Keyword arguments shared by :func:`load_v2_corpus` call sites.

    Args:
        args: Parsed CLI namespace.
        own_domain: Gold JSONL path, or ``None`` to omit own-domain rows
            (stage-2 replay mix).

    Returns:
        kwargs for :func:`load_v2_corpus`.
    """
    return {
        "cache_dir": args.cache_dir,
        "seed": args.seed,
        "own_domain": own_domain,
        "skip_goemotions": args.skip_goemotions,
        "skip_clapai": args.skip_clapai,
        "skip_tweet_ml": args.skip_tweet_ml,
        "skip_tweet_eval": args.skip_tweet_eval,
        "include_sst2": args.include_sst2,
        "include_sentiment140": args.include_sentiment140,
        "tweet_eval_target": args.tweet_eval_target,
        "goemotions_target": args.goemotions_target,
        "own_domain_factor": args.own_domain_factor,
    }


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
        help=(
            "Repeat count for gold train rows (holdout and dev are "
            f"skipped). Default {OWN_DOMAIN_OVERSAMPLE}. Stage-2 "
            "recommended: 2."
        ),
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
    parser.add_argument(
        "--init-from",
        default=None,
        help=(
            "Local Hugging Face export (tokenizer + weights) to continue "
            "from instead of --model-name. Logged to MLflow as init_from. "
            "Stage-2: path to the xlmr-sent v2 export."
        ),
    )
    parser.add_argument(
        "--dev-from-gold",
        default=None,
        help=(
            "Gold JSONL whose split==dev rows become the eval set. "
            "Without this flag, eval is a random 10% of the train mix."
        ),
    )
    parser.add_argument(
        "--replay-n",
        type=int,
        default=DEFAULT_REPLAY_N,
        help=(
            "With --init-from, stratified subsample of the v2 mix as "
            "anti-forgetting (0 = gold-only). Ignored without "
            f"--init-from. Default {DEFAULT_REPLAY_N}."
        ),
    )
    parser.add_argument(
        "--warmup-ratio",
        type=float,
        default=DEFAULT_WARMUP_RATIO,
        help=(
            "Linear warmup fraction of training steps. "
            f"Default {DEFAULT_WARMUP_RATIO}."
        ),
    )
    parser.add_argument(
        "--weight-decay",
        type=float,
        default=DEFAULT_WEIGHT_DECAY,
        help=f"AdamW weight decay. Default {DEFAULT_WEIGHT_DECAY}.",
    )
    parser.add_argument(
        "--early-stopping-patience",
        type=int,
        default=DEFAULT_EARLY_STOPPING_PATIENCE,
        help=(
            "Stop after this many evals without macro-F1 improvement. "
            "0 disables (default, full v2 train). Stage-2 recommended: "
            "1 or 2."
        ),
    )
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--epochs",
        type=int,
        default=DEFAULT_EPOCHS,
        help=f"Training epochs. Default {DEFAULT_EPOCHS}. Stage-2 recommended: 3.",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=DEFAULT_LR,
        help=f"Learning rate. Default {DEFAULT_LR}. Stage-2 recommended: 1e-5.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH,
        help=f"Per-device batch size. Default {DEFAULT_BATCH}. Stage-2 recommended: 8.",
    )
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
    if "greater_is_better" not in params:
        kwargs.pop("greater_is_better", None)
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

    rows = assemble_train_rows(args)
    train_rows, eval_rows = split_train_eval(rows, args)
    logger.info(
        "Hybrid corpus: %d train / %d eval examples (pool %d).",
        len(train_rows),
        len(eval_rows),
        len(rows),
    )

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
    checkpoint = args.init_from or args.model_name
    model_cache = args.model_cache_dir or os.environ.get("HF_HUB_CACHE")
    tokenizer = AutoTokenizer.from_pretrained(checkpoint, cache_dir=model_cache)
    model = AutoModelForSequenceClassification.from_pretrained(
        checkpoint,
        cache_dir=model_cache,
        num_labels=len(LABEL2ID),
        id2label={str(k): v for k, v in ID2LABEL.items()},
        label2id=LABEL2ID,
    )

    train_raw = examples_to_hf_dataset(train_rows)
    eval_raw = examples_to_hf_dataset(eval_rows)
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
        warmup_ratio=args.warmup_ratio,
        weight_decay=args.weight_decay,
        eval_save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
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

    callbacks: list[Any] = []
    if args.early_stopping_patience > 0:
        from transformers import EarlyStoppingCallback

        callbacks.append(
            EarlyStoppingCallback(early_stopping_patience=args.early_stopping_patience)
        )

    trainer = WeightedTrainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        compute_metrics=_compute_metrics,
        callbacks=callbacks or None,
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
                "model": checkpoint,
                "init_from": args.init_from or "",
                "max_len": MAX_LEN,
                "lr": args.lr,
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "seed": args.seed,
                "n_examples": len(train_rows),
                "n_eval": len(eval_rows),
                "fp16": use_fp16,
                "class_weights": weights,
                "num_workers": args.num_workers,
                "warmup_ratio": args.warmup_ratio,
                "weight_decay": args.weight_decay,
                "replay_n": args.replay_n,
                "early_stopping_patience": args.early_stopping_patience,
                "own_domain_factor": args.own_domain_factor,
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
