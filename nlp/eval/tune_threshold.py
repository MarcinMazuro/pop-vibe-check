r"""Tune a ``neg`` decision threshold on the gold dev split.

The fine-tuned models under-predict ``neg``: most missed negatives land in
``neu`` with a visible but non-winning ``neg`` probability. Instead of
argmax, this module scores the rule::

    neg            if p(neg) >= threshold
    argmax(neu,pos) otherwise

over a grid of thresholds. The threshold is chosen on ``--tune-split``
(``dev``) and reported once on ``--eval-split`` (``holdout``) next to the
plain argmax baseline. The holdout is never used to choose the value.

Predictions must carry ``probs`` (written by :mod:`nlp.eval.predict`).

Example::

    python -m nlp.eval.tune_threshold \\
        --gold nlp/eval/artifacts/gold_v3.jsonl \\
        --pred nlp/eval/artifacts/pred-xlmr-v2.1-goldv3.jsonl \\
        --output nlp/eval/artifacts/threshold-xlmr-v2.1-goldv3.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from nlp.eval.evaluate import classification_metrics, confusion_matrix
from nlp.eval.predict import load_gold_rows

DEFAULT_GRID: tuple[float, ...] = tuple(round(0.10 + 0.025 * i, 3) for i in range(17))
OBJECTIVES = ("macro_f1", "f1_neg")


def apply_threshold(probs: Mapping[str, float], threshold: float | None) -> str:
    """Pick a label from class probabilities.

    Args:
        probs: ``{"neg": p, "neu": p, "pos": p}``.
        threshold: ``neg`` cut-off, or ``None`` for plain argmax.

    Returns:
        ``neg`` when ``p(neg) >= threshold``, otherwise the larger of
        ``neu`` / ``pos``. With ``None``, the argmax over all three.
    """
    if threshold is None:
        return max(("neg", "neu", "pos"), key=lambda label: probs[label])
    if probs["neg"] >= threshold:
        return "neg"
    return "pos" if probs["pos"] > probs["neu"] else "neu"


def join_split(
    gold_rows: Sequence[dict[str, Any]],
    pred_rows: Sequence[dict[str, Any]],
    split: str,
) -> tuple[list[str], list[dict[str, float]]]:
    """Gold labels and prediction probabilities for one split.

    Args:
        gold_rows: Gold records with ``id``, ``label``, ``split``.
        pred_rows: Prediction records with ``id`` and ``probs``.
        split: Split name to keep.

    Returns:
        ``(gold_labels, probs)`` aligned by gold order.

    Raises:
        ValueError: If a prediction has no ``probs`` or the split is empty.
    """
    by_id = {row["id"]: row for row in pred_rows}
    gold: list[str] = []
    probs: list[dict[str, float]] = []
    for row in gold_rows:
        if row.get("split") != split or row.get("id") not in by_id:
            continue
        pred = by_id[row["id"]]
        if "probs" not in pred:
            raise ValueError(
                f"prediction {row['id']} has no 'probs'; rerun nlp.eval.predict"
            )
        gold.append(row["label"])
        probs.append({k: float(v) for k, v in pred["probs"].items()})
    if not gold:
        raise ValueError(f"no gold rows with split == {split!r} joined to predictions")
    return gold, probs


def score(
    gold: Sequence[str],
    probs: Sequence[Mapping[str, float]],
    threshold: float | None,
) -> dict[str, Any]:
    """Metrics and confusion for one threshold.

    Args:
        gold: Reference labels.
        probs: Class probabilities per row.
        threshold: ``neg`` cut-off or ``None`` for argmax.

    Returns:
        ``{"threshold", "n", "metrics", "confusion"}``.
    """
    predicted = [apply_threshold(p, threshold) for p in probs]
    return {
        "threshold": threshold,
        "n": len(gold),
        "metrics": classification_metrics(gold, predicted),
        "confusion": confusion_matrix(gold, predicted),
    }


def choose_threshold(
    curve: Sequence[dict[str, Any]],
    objective: str,
) -> float:
    """Pick the grid point with the best objective.

    Ties go to the larger threshold, the smaller change from argmax.

    Args:
        curve: Output of :func:`score` per grid threshold.
        objective: Metric key, e.g. ``macro_f1``.

    Returns:
        The chosen threshold.
    """
    best = max(
        curve, key=lambda point: (point["metrics"][objective], point["threshold"])
    )
    return float(best["threshold"])


def tune(
    gold_rows: Sequence[dict[str, Any]],
    pred_rows: Sequence[dict[str, Any]],
    *,
    tune_split: str = "dev",
    eval_split: str = "holdout",
    grid: Sequence[float] = DEFAULT_GRID,
    objective: str = "macro_f1",
) -> dict[str, Any]:
    """Choose a threshold on ``tune_split`` and report it on ``eval_split``.

    Args:
        gold_rows: Gold records.
        pred_rows: Predictions with ``probs``.
        tune_split: Split used to choose the threshold.
        eval_split: Split reported once with the chosen threshold.
        grid: Thresholds to try.
        objective: Metric maximised on ``tune_split``.

    Returns:
        Report with the tuning curve, the chosen threshold, and argmax vs
        threshold metrics on both splits.
    """
    tune_gold, tune_probs = join_split(gold_rows, pred_rows, tune_split)
    eval_gold, eval_probs = join_split(gold_rows, pred_rows, eval_split)
    curve = [score(tune_gold, tune_probs, t) for t in grid]
    chosen = choose_threshold(curve, objective)
    return {
        "objective": objective,
        "tune_split": tune_split,
        "eval_split": eval_split,
        "chosen_threshold": chosen,
        "curve": [{"threshold": p["threshold"], **p["metrics"]} for p in curve],
        tune_split: {
            "argmax": score(tune_gold, tune_probs, None),
            "threshold": score(tune_gold, tune_probs, chosen),
        },
        eval_split: {
            "argmax": score(eval_gold, eval_probs, None),
            "threshold": score(eval_gold, eval_probs, chosen),
        },
    }


def format_summary(report: Mapping[str, Any]) -> str:
    """Human-readable summary of a :func:`tune` report.

    Args:
        report: Output of :func:`tune`.

    Returns:
        Multi-line text table.
    """
    lines = [f"{'T':>6}  macro-F1  F1-neg  P-neg  R-neg"]
    for point in report["curve"]:
        lines.append(
            f"{point['threshold']:>6.3f}  {point['macro_f1']:.3f}     "
            f"{point['f1_neg']:.3f}   {point['precision_neg']:.3f}  "
            f"{point['recall_neg']:.3f}"
        )
    lines.append(
        f"chosen T = {report['chosen_threshold']:.3f} "
        f"(max {report['objective']} on {report['tune_split']})"
    )
    for split in (report["tune_split"], report["eval_split"]):
        for rule in ("argmax", "threshold"):
            m = report[split][rule]["metrics"]
            lines.append(
                f"{split:>8} {rule:<9} n={report[split][rule]['n']:<4} "
                f"acc={m['accuracy']:.3f} macro-F1={m['macro_f1']:.3f} "
                f"F1-neg={m['f1_neg']:.3f} P-neg={m['precision_neg']:.3f} "
                f"R-neg={m['recall_neg']:.3f}"
            )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list.

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True, type=Path, help="Gold JSONL.")
    parser.add_argument(
        "--pred", required=True, type=Path, help="Prediction JSONL with probs."
    )
    parser.add_argument("--output", type=Path, default=None, help="JSON report.")
    parser.add_argument("--tune-split", default="dev")
    parser.add_argument("--eval-split", default="holdout")
    parser.add_argument("--objective", choices=OBJECTIVES, default="macro_f1")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list.

    Returns:
        Process exit code.
    """
    args = parse_args(argv)
    report = tune(
        load_gold_rows(args.gold),
        load_gold_rows(args.pred),
        tune_split=args.tune_split,
        eval_split=args.eval_split,
        objective=args.objective,
    )
    if args.output:
        args.output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    sys.stdout.write(format_summary(report) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
