r"""Merge reviewed v3 prelabels with existing gold and assign splits.

Combines ``gold.jsonl`` with a verified ``gold_v3_review.jsonl``. Rows
marked ``review_required`` are kept only when a human filled ``label``;
other rows take ``label_llm`` as ``label`` and record
``label_source`` ``human`` or ``llm``.

The old holdout stays holdout. New rows fill holdout to the target
(default 200, including the existing 80), then ~80 to ``dev``, the rest
``train``. Stratification is ``label`` × EN/non-EN with language
round-robin inside each stratum (same idea as
:func:`nlp.eval.sample_gold.sample_records`).

Example::

    python -m nlp.eval.merge_gold \\
        --gold nlp/eval/artifacts/gold.jsonl \\
        --review nlp/eval/artifacts/gold_v3_review.jsonl \\
        --output nlp/eval/artifacts/gold_v3.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from nlp.base import LABELS
from nlp.eval.sample_gold import load_jsonl, write_jsonl

DEFAULT_GOLD = Path("nlp/eval/artifacts/gold.jsonl")
DEFAULT_REVIEW = Path("nlp/eval/artifacts/gold_v3_review.jsonl")
DEFAULT_OUTPUT = Path("nlp/eval/artifacts/gold_v3.jsonl")
DEFAULT_AGREEMENT = Path("nlp/eval/artifacts/prelabel-agreement.json")
DEFAULT_HOLDOUT_TARGET = 200
DEFAULT_DEV_N = 80
DEFAULT_SEED = 33
DEFAULT_EXISTING_HOLDOUT = 80
VALID_SPLITS = frozenset({"train", "dev", "holdout"})
LABEL_SET = frozenset(LABELS)


def en_bucket(language: str) -> str:
    """Map a language code to the EN / non-EN stratum.

    Args:
        language: ``langdetect``-style code (``en``, ``fr``, …).

    Returns:
        ``"en"`` if the code is English, otherwise ``"non-en"``.
    """
    return "en" if language.strip().lower() == "en" else "non-en"


def stratum_key(row: dict[str, Any], label_field: str = "label") -> str:
    """Return the ``label|en`` / ``label|non-en`` stratum key.

    Args:
        row: Gold or review record.
        label_field: Field to read the class from (``label`` or
            ``label_llm``).

    Returns:
        Stratum key used for holdout / dev allocation.
    """
    label = str(row.get(label_field) or "").strip().lower()
    language = str(row.get("language") or "")
    return f"{label}|{en_bucket(language)}"


def count_holdout(rows: Sequence[dict[str, Any]]) -> int:
    """Count rows already assigned to holdout.

    Args:
        rows: Gold records.

    Returns:
        Number of rows with ``split == "holdout"``.
    """
    return sum(
        1 for row in rows if str(row.get("split") or "").strip().lower() == "holdout"
    )


def _interleave_languages(
    rows: Sequence[dict[str, Any]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Shuffle within each language, then round-robin across languages.

    Args:
        rows: Records that already share a label × EN stratum.
        rng: Seeded RNG.

    Returns:
        A new list covering every input row.
    """
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get("language") or "und")].append(row)
    queues: list[list[dict[str, Any]]] = []
    for bucket in buckets.values():
        copy = list(bucket)
        rng.shuffle(copy)
        queues.append(copy)
    ordered: list[dict[str, Any]] = []
    while queues:
        next_round: list[list[dict[str, Any]]] = []
        for queue in queues:
            if not queue:
                continue
            ordered.append(queue.pop(0))
            if queue:
                next_round.append(queue)
        queues = next_round
    return ordered


def _take_round_robin_prefix(
    ordered_strata: dict[str, list[dict[str, Any]]],
    n: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Take up to ``n`` rows, round-robin across already-ordered strata.

    Leftover filling matches :func:`nlp.eval.sample_gold.sample_records`:
    sample from the unused tails when prefixes undershoot, then downsample
    if prefixes overshoot.

    Args:
        ordered_strata: Stratum key → language-interleaved rows.
        n: Target count.
        rng: Seeded RNG.

    Returns:
        At most ``n`` rows.
    """
    if not ordered_strata or n <= 0:
        return []
    total = sum(len(bucket) for bucket in ordered_strata.values())
    if total <= n:
        chosen: list[dict[str, Any]] = []
        for bucket in ordered_strata.values():
            chosen.extend(bucket)
        return chosen
    per_bucket = max(1, n // len(ordered_strata))
    chosen = []
    leftover: list[dict[str, Any]] = []
    for bucket in ordered_strata.values():
        take = min(per_bucket, len(bucket))
        chosen.extend(bucket[:take])
        leftover.extend(bucket[take:])
    if len(chosen) < n and leftover:
        chosen.extend(rng.sample(leftover, min(n - len(chosen), len(leftover))))
    if len(chosen) > n:
        chosen = rng.sample(chosen, n)
    return chosen


def pick_stratified(
    rows: Sequence[dict[str, Any]],
    n: int,
    *,
    seed: int = DEFAULT_SEED,
    label_field: str = "label",
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    """Pick ``n`` rows stratified by label × EN/non-EN.

    Within each stratum, languages are interleaved so a dominant language
    cannot wipe smaller ones (same motivation as
    :func:`nlp.eval.sample_gold.sample_records`).

    Args:
        rows: Candidate records.
        n: Target size.
        seed: Used when ``rng`` is omitted.
        label_field: Class field for the outer stratum.
        rng: Optional shared RNG (holdout then dev should share state).

    Returns:
        Up to ``n`` of the input row objects (not copied).
    """
    usable = list(rows)
    if n <= 0 or not usable:
        return []
    if n >= len(usable):
        return usable
    local_rng = rng if rng is not None else random.Random(seed)
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in usable:
        strata[stratum_key(row, label_field)].append(row)
    ordered = {
        key: _interleave_languages(bucket, local_rng) for key, bucket in strata.items()
    }
    return _take_round_robin_prefix(ordered, n, local_rng)


def allocate_new_splits(
    rows: Sequence[dict[str, Any]],
    *,
    holdout_n: int,
    dev_n: int,
    seed: int = DEFAULT_SEED,
    label_field: str = "label",
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    """Assign ``holdout`` / ``dev`` / ``train`` on new gold rows.

    Picks holdout first, then dev from the remainder, both stratified.
    Input order is preserved in the returned copies.

    Args:
        rows: Newly labelled records (already resolved ``label``).
        holdout_n: New holdout seats to fill.
        dev_n: Dev seats to fill after holdout.
        seed: RNG seed when ``rng`` is omitted.
        label_field: Class field for stratification.
        rng: Optional shared RNG.

    Returns:
        Shallow copies with ``split`` set.
    """
    local_rng = rng if rng is not None else random.Random(seed)
    pool = list(rows)
    holdout_rows = pick_stratified(
        pool, holdout_n, seed=seed, label_field=label_field, rng=local_rng
    )
    holdout_ids = {str(row.get("id")) for row in holdout_rows}
    rest = [row for row in pool if str(row.get("id")) not in holdout_ids]
    dev_rows = pick_stratified(
        rest, dev_n, seed=seed, label_field=label_field, rng=local_rng
    )
    dev_ids = {str(row.get("id")) for row in dev_rows}
    allocated: list[dict[str, Any]] = []
    for row in pool:
        item = dict(row)
        rid = str(item.get("id"))
        if rid in holdout_ids:
            item["split"] = "holdout"
        elif rid in dev_ids:
            item["split"] = "dev"
        else:
            item["split"] = "train"
        allocated.append(item)
    return allocated


def cohen_kappa(y1: Sequence[str], y2: Sequence[str]) -> float:
    """Cohen's κ for two label sequences of equal length.

    Args:
        y1: Reference labels (human).
        y2: Comparison labels (``label_llm``).

    Returns:
        κ in ``[-1, 1]``. Empty input yields ``0.0``. Perfect chance-level
        agreement with perfect observed agreement yields ``1.0``.

    Raises:
        ValueError: If the sequences differ in length.
    """
    if len(y1) != len(y2):
        raise ValueError(
            f"y1 ({len(y1)}) and y2 ({len(y2)}) length mismatch"
        )
    n = len(y1)
    if n == 0:
        return 0.0
    observed = sum(a == b for a, b in zip(y1, y2, strict=True)) / n
    labels = set(y1) | set(y2)
    counts1 = Counter(y1)
    counts2 = Counter(y2)
    expected = sum((counts1[lab] / n) * (counts2[lab] / n) for lab in labels)
    if expected >= 1.0:
        return 1.0 if observed >= 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def _truthy(value: Any) -> bool:
    """Interpret JSONL bools and common string spellings.

    Args:
        value: Raw ``review_required`` field.

    Returns:
        Whether the row was flagged for human review.
    """
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _normalise_label(value: Any) -> str:
    """Lower-case strip a label-like field.

    Args:
        value: Raw field.

    Returns:
        Normalised string, possibly empty.
    """
    return str(value or "").strip().lower()


def resolve_review_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Turn one review JSONL object into a gold row.

    A ``review_required`` row is dropped unless ``label`` is a valid class.
    Optional human labels on non-required rows still win over ``label_llm``.

    Args:
        row: Review record.

    Returns:
        Shallow copy with ``label`` and ``label_source`` set, or ``None``
        when a required review was not filled.

    Raises:
        ValueError: If a non-required row has no valid ``label_llm``.
    """
    item = dict(row)
    review_required = _truthy(item.get("review_required"))
    human = _normalise_label(item.get("label"))
    llm = _normalise_label(item.get("label_llm"))
    if human in LABEL_SET:
        item["label"] = human
        item["label_source"] = "human"
        return item
    if review_required:
        return None
    if llm not in LABEL_SET:
        raise ValueError(
            f"id={item.get('id')!r}: label_llm must be one of {LABELS}, "
            f"got {item.get('label_llm')!r}"
        )
    item["label"] = llm
    item["label_source"] = "llm"
    return item


def _as_existing_gold_row(row: dict[str, Any]) -> dict[str, Any]:
    """Validate an already-labelled gold.jsonl row and tag it human.

    Args:
        row: Existing gold record.

    Returns:
        Shallow copy with normalised ``label`` / ``split`` and
        ``label_source`` ``human``.

    Raises:
        ValueError: If ``label`` is missing or not a pipeline class.
    """
    item = dict(row)
    label = _normalise_label(item.get("label"))
    if label not in LABEL_SET:
        raise ValueError(
            f"id={item.get('id')!r}: gold label must be one of {LABELS}, "
            f"got {item.get('label')!r}"
        )
    item["label"] = label
    split = str(item.get("split") or "train").strip().lower()
    item["split"] = split if split in VALID_SPLITS else "train"
    item.setdefault("label_source", "human")
    return item


def prelabel_agreement(rows: Sequence[dict[str, Any]]) -> dict[str, float | int]:
    """Accuracy and Cohen's κ of human labels vs ``label_llm``.

    Only rows with ``label_source == "human"`` and a valid ``label_llm``
    are scored.

    Args:
        rows: Resolved review rows (not the pre-existing gold set).

    Returns:
        JSON-serialisable report with ``n``, ``accuracy``, ``cohen_kappa``.
    """
    human: list[str] = []
    llm: list[str] = []
    for row in rows:
        if str(row.get("label_source") or "") != "human":
            continue
        llm_label = _normalise_label(row.get("label_llm"))
        if llm_label not in LABEL_SET:
            continue
        human.append(str(row["label"]))
        llm.append(llm_label)
    n = len(human)
    accuracy = (
        sum(a == b for a, b in zip(human, llm, strict=True)) / n if n else 0.0
    )
    return {
        "n": n,
        "accuracy": accuracy,
        "cohen_kappa": cohen_kappa(human, llm),
    }


def merge_gold_rows(
    existing: Sequence[dict[str, Any]],
    review: Sequence[dict[str, Any]],
    *,
    holdout_target: int = DEFAULT_HOLDOUT_TARGET,
    dev_n: int = DEFAULT_DEV_N,
    seed: int = DEFAULT_SEED,
    human_only: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, float | int]]:
    """Merge gold + review, assign splits, and score LLM/human agreement.

    Existing gold ids win on duplicates. Holdout/dev seats for *new* rows
    are filled from human-labelled rows first, then LLM rows if short.

    Args:
        existing: Rows from ``gold.jsonl``.
        review: Rows from ``gold_v3_review.jsonl``.
        holdout_target: Total holdout size including the old 80.
        dev_n: New-row dev size.
        seed: Stratified-split seed.
        human_only: Drop ``train`` rows whose ``label_source`` is ``llm``.

    Returns:
        ``(merged_rows, agreement_report)``. The report also includes
        ``dropped_unreviewed``.
    """
    existing_out = [_as_existing_gold_row(row) for row in existing]
    existing_ids = {
        str(row.get("id") or "").strip()
        for row in existing_out
        if str(row.get("id") or "").strip()
    }
    resolved: list[dict[str, Any]] = []
    seen_new: set[str] = set()
    dropped = 0
    for row in review:
        rid = str(row.get("id") or "").strip()
        if not rid or rid in existing_ids or rid in seen_new:
            continue
        item = resolve_review_row(row)
        if item is None:
            dropped += 1
            continue
        seen_new.add(rid)
        resolved.append(item)

    existing_holdout = count_holdout(existing_out)
    holdout_needed = max(0, holdout_target - existing_holdout)
    human = [row for row in resolved if row.get("label_source") == "human"]
    llm = [row for row in resolved if row.get("label_source") != "human"]
    human_split = allocate_new_splits(
        human, holdout_n=holdout_needed, dev_n=dev_n, seed=seed
    )
    got_holdout = sum(1 for row in human_split if row["split"] == "holdout")
    got_dev = sum(1 for row in human_split if row["split"] == "dev")
    llm_split = allocate_new_splits(
        llm,
        holdout_n=max(0, holdout_needed - got_holdout),
        dev_n=max(0, dev_n - got_dev),
        seed=seed,
    )
    by_id = {str(row["id"]): row for row in human_split + llm_split}
    new_ordered = [by_id[rid] for rid in seen_new if rid in by_id]
    merged = existing_out + new_ordered
    if human_only:
        merged = [
            row
            for row in merged
            if not (
                str(row.get("split")) == "train"
                and str(row.get("label_source")) == "llm"
            )
        ]
    agreement = prelabel_agreement(resolved)
    agreement["dropped_unreviewed"] = dropped
    return merged, agreement


def _print_counts(title: str, values: Sequence[str]) -> None:
    """Print a Counter summary to stdout.

    Args:
        title: Line prefix.
        values: Observed keys.
    """
    counts = Counter(values)
    parts = [f"{key}={counts[key]}" for key in sorted(counts)]
    print(f"{title}: " + (", ".join(parts) if parts else "(none)"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list.

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gold",
        type=Path,
        default=DEFAULT_GOLD,
        help="Existing labelled gold JSONL.",
    )
    parser.add_argument(
        "--review",
        type=Path,
        default=DEFAULT_REVIEW,
        help="Reviewed gold_v3_review JSONL.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination gold_v3 JSONL.",
    )
    parser.add_argument(
        "--agreement",
        type=Path,
        default=DEFAULT_AGREEMENT,
        help="LLM vs human agreement JSON.",
    )
    parser.add_argument(
        "--holdout-target",
        type=int,
        default=DEFAULT_HOLDOUT_TARGET,
        help="Total holdout size including existing holdout rows.",
    )
    parser.add_argument(
        "--dev-n",
        type=int,
        default=DEFAULT_DEV_N,
        help="New-row dev size.",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--human-only",
        action="store_true",
        help="Drop train rows whose label_source is llm.",
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
    existing = load_jsonl(args.gold)
    review = load_jsonl(args.review)
    merged, agreement = merge_gold_rows(
        existing,
        review,
        holdout_target=args.holdout_target,
        dev_n=args.dev_n,
        seed=args.seed,
        human_only=args.human_only,
    )
    write_jsonl(args.output, merged)
    args.agreement.parent.mkdir(parents=True, exist_ok=True)
    args.agreement.write_text(
        json.dumps(agreement, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(merged)} rows to {args.output}")
    print(f"Wrote agreement n={agreement['n']} to {args.agreement}")
    _print_counts("split", [str(row.get("split") or "") for row in merged])
    _print_counts(
        "label_source", [str(row.get("label_source") or "") for row in merged]
    )
    _print_counts("label", [str(row.get("label") or "") for row in merged])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
