r"""Sample a ~300-row gold set for manual labelling.

Reads JSONL (publisher-shaped records or ``raw_staging`` exports) and
writes a stratified sample. Stratification is by ``source`` then
``language`` when those fields exist, otherwise a seeded uniform sample.

The SQL companion ``nlp/eval/sql/sample_gold.sql`` pulls candidates from
BigQuery; this script is the offline / already-exported path.

Example::

    python -m nlp.eval.sample_gold \\
        --input raw_staging.jsonl --output gold_to_label.jsonl --n 300
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load JSON objects from a JSONL file.

    Args:
        path: Source file.

    Returns:
        Parsed objects, skipping blank lines.
    """
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            rows.append(json.loads(raw))
    return rows


def write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    """Write JSON objects as JSONL.

    Args:
        path: Destination.
        rows: Objects to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def sample_records(
    rows: Sequence[dict[str, Any]],
    n: int,
    *,
    seed: int = 33,
    strata_keys: Sequence[str] = ("source", "language"),
) -> list[dict[str, Any]]:
    """Draw up to ``n`` rows, stratified when possible.

    Args:
        rows: Candidate records. Rows without ``text`` are dropped.
        n: Target size (~300).
        seed: RNG seed.
        strata_keys: Fields concatenated into a stratum key when present.

    Returns:
        A new list of at most ``n`` rows. Each output row is a shallow
        copy with ``label`` set to ``""`` so annotators fill it in.
    """
    usable = [row for row in rows if str(row.get("text") or "").strip()]
    if n <= 0 or not usable:
        return []
    rng = random.Random(seed)

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in usable:
        key = "|".join(str(row.get(k) or "") for k in strata_keys)
        buckets[key].append(row)

    if len(usable) <= n:
        chosen = list(usable)
    elif len(buckets) == 1:
        chosen = rng.sample(usable, n)
    else:
        # Round-robin so small languages / sources are not wiped by YouTube-EN.
        per_bucket = max(1, n // len(buckets))
        chosen = []
        leftover: list[dict[str, Any]] = []
        for bucket in buckets.values():
            rng.shuffle(bucket)
            take = min(per_bucket, len(bucket))
            chosen.extend(bucket[:take])
            leftover.extend(bucket[take:])
        if len(chosen) < n and leftover:
            chosen.extend(rng.sample(leftover, min(n - len(chosen), len(leftover))))
        if len(chosen) > n:
            chosen = rng.sample(chosen, n)

    annotated: list[dict[str, Any]] = []
    for row in chosen:
        item = dict(row)
        item.setdefault("label", "")
        annotated.append(item)
    return annotated


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list.

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--n", type=int, default=300)
    parser.add_argument("--seed", type=int, default=33)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list.

    Returns:
        Process exit code.
    """
    args = parse_args(argv)
    rows = load_jsonl(args.input)
    sampled = sample_records(rows, args.n, seed=args.seed)
    write_jsonl(args.output, sampled)
    print(f"Wrote {len(sampled)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
