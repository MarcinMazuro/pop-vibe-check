r"""CPU-safe Hugging Face inference for gold-set evaluation.

Loads a local sequence-classification directory and writes JSONL
predictions that :mod:`nlp.eval.evaluate` can join on ``id``. This
module is not imported by Dataflow.

Example::

    python -m nlp.eval.predict \\
        --model-dir nlp/eval/artifacts/xlmr-sent \\
        --gold nlp/eval/artifacts/gold.jsonl \\
        --output nlp/eval/artifacts/pred-xlmr-v2.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from nlp.base import ID2LABEL, normalize_text
from nlp.training.labels import MAX_LEN

DEFAULT_BATCH = 8


def texts_for_tokenize(rows: Sequence[dict[str, Any]]) -> list[str]:
    """Normalise gold ``text`` fields the same way training does.

    Args:
        rows: Gold records. ``text`` may be empty.

    Returns:
        One normalised string per row, same order.
    """
    return [normalize_text(str(row.get("text") or "")) for row in rows]


def label_and_score(logits: Sequence[float]) -> tuple[str, float]:
    """Map a 3-class logit vector to ``(label, softmax confidence)``.

    Args:
        logits: Class scores in ``neg`` / ``neu`` / ``pos`` id order.

    Returns:
        Pipeline label and the softmax mass of the argmax class.

    Raises:
        ValueError: If ``logits`` is empty.
    """
    if not logits:
        raise ValueError("logits must be non-empty")
    peak = max(logits)
    exps = [math.exp(value - peak) for value in logits]
    total = sum(exps)
    probs = [value / total for value in exps]
    index = max(range(len(probs)), key=probs.__getitem__)
    label = ID2LABEL.get(index)
    if label is None:
        raise ValueError(f"logit index {index} is outside {sorted(ID2LABEL)}")
    return label, probs[index]


def load_gold_rows(path: Path) -> list[dict[str, Any]]:
    """Load gold JSONL rows.

    Args:
        path: Gold file with ``id`` and ``text``.

    Returns:
        Parsed objects, skipping blank lines.

    Raises:
        ValueError: If the file is empty.
    """
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            rows.append(json.loads(raw))
    if not rows:
        raise ValueError(f"{path} contains no rows")
    return rows


def write_pred_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    """Write prediction objects as JSONL.

    Args:
        path: Destination.
        rows: Objects with ``id``, ``label``, ``score``, ``text``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def predict_rows(
    rows: Sequence[dict[str, Any]],
    *,
    model_dir: Path,
    max_len: int = MAX_LEN,
    batch_size: int = DEFAULT_BATCH,
) -> list[dict[str, Any]]:
    """Run CPU sequence-classification on gold rows.

    Args:
        rows: Gold records. ``text`` may be empty.
        model_dir: Hugging Face export directory.
        max_len: Tokenizer truncation length.
        batch_size: Forward-pass batch size.

    Returns:
        One prediction dict per input, same order.
    """
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir)
    model.eval()
    device = torch.device("cpu")
    model.to(device)

    predictions: list[dict[str, Any]] = []
    step = max(1, batch_size)
    with torch.inference_mode():
        for start in range(0, len(rows), step):
            batch = rows[start : start + step]
            texts = texts_for_tokenize(batch)
            encoded = tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=max_len,
                return_tensors="pt",
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            logits = model(**encoded).logits.cpu().tolist()
            for row, logit in zip(batch, logits, strict=True):
                label, score = label_and_score(logit)
                predictions.append(
                    {
                        "id": row.get("id", ""),
                        "label": label,
                        "score": score,
                        "text": row.get("text", ""),
                    }
                )
    return predictions


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list.

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-dir",
        required=True,
        type=Path,
        help="Local Hugging Face sequence-classification directory.",
    )
    parser.add_argument("--gold", required=True, type=Path, help="Gold JSONL.")
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Prediction JSONL (id/label/score/text).",
    )
    parser.add_argument("--max-len", type=int, default=MAX_LEN)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list.

    Returns:
        Process exit code.
    """
    args = parse_args(argv)
    rows = load_gold_rows(args.gold)
    predictions = predict_rows(
        rows,
        model_dir=args.model_dir,
        max_len=args.max_len,
        batch_size=args.batch_size,
    )
    write_pred_jsonl(args.output, predictions)
    print(f"Wrote {len(predictions)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
