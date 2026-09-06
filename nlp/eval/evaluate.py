"""Pure-Python classification metrics for the gold set.

sklearn is available on Workbench but not in CI / the Dataflow image.
These helpers cover accuracy, per-class precision/recall/F1, macro-F1,
and a confusion matrix over ``pos`` / ``neu`` / ``neg``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from nlp.base import LABELS


def confusion_matrix(
    gold: Sequence[str],
    predicted: Sequence[str],
    *,
    labels: Sequence[str] = LABELS,
) -> dict[str, dict[str, int]]:
    """Build a label × label count matrix.

    Args:
        gold: Reference labels.
        predicted: Model labels, same length and order as ``gold``.
        labels: Axis order.

    Returns:
        Nested dict ``matrix[gold_label][predicted_label] = count``.

    Raises:
        ValueError: If the sequences differ in length.
    """
    if len(gold) != len(predicted):
        raise ValueError(
            f"gold ({len(gold)}) and predicted ({len(predicted)}) length mismatch"
        )
    matrix = {row: {col: 0 for col in labels} for row in labels}
    for y_true, y_pred in zip(gold, predicted, strict=True):
        if y_true not in matrix:
            matrix[y_true] = {col: 0 for col in labels}
        if y_pred not in matrix[y_true]:
            matrix[y_true][y_pred] = 0
        matrix[y_true][y_pred] += 1
    return matrix


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    """Precision, recall, F1 from one class's counts.

    Args:
        tp: True positives.
        fp: False positives.
        fn: False negatives.

    Returns:
        ``(precision, recall, f1)``, each in ``0..1``. Zero-support
        classes yield ``0.0`` rather than NaN so JSON serialisation
        stays clean.
    """
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    if precision + recall == 0.0:
        return precision, recall, 0.0
    f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def classification_metrics(
    gold: Sequence[str],
    predicted: Sequence[str],
    *,
    labels: Sequence[str] = LABELS,
) -> dict[str, float]:
    """Accuracy, macro-F1, and per-class precision / recall / F1.

    Args:
        gold: Reference labels.
        predicted: Model labels.
        labels: Classes to score. Extra labels in the data are ignored
            for the macro average but still affect accuracy.

    Returns:
        Flat dict suitable for MLflow ``log_metrics``. Keys::

            accuracy, macro_f1, macro_precision, macro_recall,
            precision_pos, recall_pos, f1_pos, … (each label)
    """
    if len(gold) != len(predicted):
        raise ValueError(
            f"gold ({len(gold)}) and predicted ({len(predicted)}) length mismatch"
        )
    n = len(gold)
    accuracy = (
        (sum(g == p for g, p in zip(gold, predicted, strict=True)) / n) if n else 0.0
    )

    gold_counts: Counter[str] = Counter(gold)
    pred_counts: Counter[str] = Counter(predicted)
    tp: Counter[str] = Counter(
        g for g, p in zip(gold, predicted, strict=True) if g == p
    )

    metrics: dict[str, float] = {"accuracy": accuracy}
    precs: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []
    for label in labels:
        precision, recall, f1 = _prf(
            tp[label],
            pred_counts[label] - tp[label],
            gold_counts[label] - tp[label],
        )
        metrics[f"precision_{label}"] = precision
        metrics[f"recall_{label}"] = recall
        metrics[f"f1_{label}"] = f1
        precs.append(precision)
        recalls.append(recall)
        f1s.append(f1)
    k = len(labels) or 1
    metrics["macro_precision"] = sum(precs) / k
    metrics["macro_recall"] = sum(recalls) / k
    metrics["macro_f1"] = sum(f1s) / k
    return metrics


def metrics_by_group(
    gold: Sequence[str],
    predicted: Sequence[str],
    groups: Sequence[str],
    *,
    labels: Sequence[str] = LABELS,
) -> dict[str, dict[str, float]]:
    """Slice :func:`classification_metrics` by a grouping column.

    Args:
        gold: Reference labels.
        predicted: Model labels.
        groups: Group key per row (language, source, …).
        labels: Classes to score.

    Returns:
        Group name → metrics dict.
    """
    if not (len(gold) == len(predicted) == len(groups)):
        raise ValueError("gold, predicted and groups must be the same length")
    buckets: dict[str, tuple[list[str], list[str]]] = defaultdict(lambda: ([], []))
    for y_true, y_pred, group in zip(gold, predicted, groups, strict=True):
        buckets[group][0].append(y_true)
        buckets[group][1].append(y_pred)
    return {
        name: classification_metrics(g, p, labels=labels)
        for name, (g, p) in sorted(buckets.items())
    }


def load_label_table(path: Path) -> list[dict[str, str]]:
    """Load a gold or prediction table from JSONL or CSV.

    Args:
        path: ``.jsonl`` / ``.json`` or ``.csv``. Required columns:
            ``label``. Optional: ``id``, ``text``, ``language``,
            ``source``, ``predicted``.

    Returns:
        One dict per row, keys lower-cased.

    Raises:
        ValueError: If the file is empty or missing ``label``.
    """
    suffix = path.suffix.lower()
    rows: list[dict[str, str]] = []
    if suffix in {".jsonl", ".json"}:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                payload = json.loads(raw)
                rows.append({str(k).lower(): str(v) for k, v in payload.items()})
    else:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for payload in reader:
                rows.append({str(k).lower(): str(v or "") for k, v in payload.items()})
    if not rows:
        raise ValueError(f"{path} contains no rows")
        if (
            "label" not in rows[0]
            and "gold" not in rows[0]
            and "predicted" not in rows[0]
            and "pred" not in rows[0]
        ):
            raise ValueError(f"{path} needs a 'label', 'gold', or 'predicted' column")
    return rows


def _row_gold(row: dict[str, str]) -> str:
    """Return the gold label from a table row.

    Args:
        row: Loaded row.

    Returns:
        Gold label.
    """
    return row.get("gold") or row["label"]


def evaluate_files(
    gold_path: Path,
    pred_path: Path | None = None,
) -> dict[str, Any]:
    """Score a gold file, optionally joined to a predictions file on ``id``.

    If ``pred_path`` is omitted, each gold row must already carry
    ``predicted``.

    Args:
        gold_path: Gold JSONL/CSV.
        pred_path: Optional predictions file with ``id`` + ``predicted``
            (or ``label``).

    Returns:
        Report dict with overall metrics, confusion matrix, and per
        ``language`` / ``source`` slices when those columns exist.
    """
    gold_rows = load_label_table(gold_path)
    if pred_path is None:
        predicted = [row.get("predicted") or row.get("pred") or "" for row in gold_rows]
        gold = [_row_gold(row) for row in gold_rows]
        aligned = gold_rows
    else:
        preds = {
            row.get("id", str(i)): row
            for i, row in enumerate(load_label_table(pred_path))
        }
        aligned = []
        gold = []
        predicted = []
        for row in gold_rows:
            key = row.get("id")
            if key is None or key not in preds:
                continue
            aligned.append(row)
            gold.append(_row_gold(row))
            pred_row = preds[key]
            predicted.append(pred_row.get("predicted") or pred_row.get("label") or "")

    report: dict[str, Any] = {
        "n": len(gold),
        "metrics": classification_metrics(gold, predicted),
        "confusion": confusion_matrix(gold, predicted),
    }
    if aligned and "language" in aligned[0]:
        report["by_language"] = metrics_by_group(
            gold, predicted, [row.get("language", "") for row in aligned]
        )
    if aligned and "source" in aligned[0]:
        report["by_source"] = metrics_by_group(
            gold, predicted, [row.get("source", "") for row in aligned]
        )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list.

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True, type=Path, help="Gold JSONL or CSV.")
    parser.add_argument(
        "--pred",
        type=Path,
        default=None,
        help=(
            "Optional predictions file joined on id. "
            "Otherwise gold must have 'predicted'."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the JSON report here instead of stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list.

    Returns:
        Process exit code.
    """
    args = parse_args(argv)
    report = evaluate_files(args.gold, args.pred)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
