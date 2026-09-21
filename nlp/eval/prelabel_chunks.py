r"""Split / merge / select local prelabel chunks (no LLM API).

Prepares JSONL candidate comments for a Cursor agent that labels files
on disk, then stitches the labelled chunks and flags rows that a human
must review.

Subcommands:

* ``split`` — drop ids already in ``gold.jsonl``, dedupe texts, write
  ``chunk-NN.jsonl`` packs of 100 with empty ``label_llm`` /
  ``llm_confidence``.
* ``merge`` — concatenate chunks to ``gold_v3_review.jsonl``, require
  ``label_llm`` in ``pos|neu|neg``, leave ``label`` empty, print
  distributions.
* ``select`` — set ``review_required`` for every ``neg``, every
  ``llm_confidence == low``, and rows allocated to future holdout/dev.

Example::

    python -m nlp.eval.prelabel_chunks split \\
        --input nlp/eval/artifacts/candidates_v3.jsonl
    python -m nlp.eval.prelabel_chunks merge
    python -m nlp.eval.prelabel_chunks select
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from nlp.base import LABELS
from nlp.eval.merge_gold import (
    DEFAULT_DEV_N,
    DEFAULT_EXISTING_HOLDOUT,
    DEFAULT_HOLDOUT_TARGET,
    DEFAULT_SEED,
    allocate_new_splits,
    count_holdout,
)
from nlp.eval.sample_gold import load_jsonl, write_jsonl

DEFAULT_GOLD = Path("nlp/eval/artifacts/gold.jsonl")
DEFAULT_CHUNK_DIR = Path("nlp/eval/artifacts/prelabel")
DEFAULT_REVIEW = Path("nlp/eval/artifacts/gold_v3_review.jsonl")
DEFAULT_CHUNK_SIZE = 100
LABEL_SET = frozenset(LABELS)
OPTIONAL_KEEP = ("source", "created_utc")


def gold_ids(rows: Sequence[dict[str, Any]]) -> set[str]:
    """Collect non-empty gold ids to exclude from new candidates.

    Args:
        rows: Existing gold records.

    Returns:
        Id strings.
    """
    return {str(row.get("id") or "").strip() for row in rows if row.get("id")}


def to_prelabel_row(row: dict[str, Any]) -> dict[str, Any]:
    """Project a candidate onto the prelabel schema.

    Args:
        row: Source record (``raw_staging`` export or similar).

    Returns:
        Row with empty ``label_llm`` / ``llm_confidence`` and optional
        ``source`` / ``created_utc`` when present.
    """
    item: dict[str, Any] = {
        "id": str(row.get("id") or ""),
        "text": str(row.get("text") or ""),
        "language": str(row.get("language") or ""),
        "event_tag": str(row.get("event_tag") or ""),
        "label_llm": "",
        "llm_confidence": "",
    }
    for key in OPTIONAL_KEEP:
        if key in row and row[key] is not None:
            item[key] = row[key]
    return item


def filter_candidates(
    rows: Sequence[dict[str, Any]],
    exclude_ids: set[str],
) -> list[dict[str, Any]]:
    """Drop gold ids, empty text, duplicate ids, and duplicate texts.

    Text dedupe uses stripped equality and keeps the first occurrence.

    Args:
        rows: Candidate records.
        exclude_ids: Ids already present in gold.

    Returns:
        Prelabel-shaped rows ready to chunk.
    """
    seen_ids: set[str] = set()
    seen_texts: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        rid = str(row.get("id") or "").strip()
        text_key = str(row.get("text") or "").strip()
        if not rid or not text_key:
            continue
        if rid in exclude_ids or rid in seen_ids or text_key in seen_texts:
            continue
        seen_ids.add(rid)
        seen_texts.add(text_key)
        out.append(to_prelabel_row(row))
    return out


def split_into_chunks(
    rows: Sequence[dict[str, Any]],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> list[list[dict[str, Any]]]:
    """Partition rows into packs of ``chunk_size``.

    Args:
        rows: Prelabel rows.
        chunk_size: Pack length. The last pack may be shorter.

    Returns:
        Consecutive slices. Empty when ``rows`` is empty.

    Raises:
        ValueError: If ``chunk_size`` is less than 1.
    """
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    return [list(rows[i : i + chunk_size]) for i in range(0, len(rows), chunk_size)]


def chunk_path(output_dir: Path, index: int) -> Path:
    """Return ``chunk-NN.jsonl`` for a 1-based pack index.

    Args:
        output_dir: Prelabel directory.
        index: 1-based chunk number.

    Returns:
        Destination path with a two-digit (or wider) suffix.
    """
    return output_dir / f"chunk-{index:02d}.jsonl"


def clear_chunks(output_dir: Path) -> None:
    """Remove previous ``chunk-*.jsonl`` files so merge cannot see stale packs.

    Args:
        output_dir: Prelabel directory. Created if missing.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.glob("chunk-*.jsonl"):
        path.unlink()


def write_chunks(
    chunks: Sequence[Sequence[dict[str, Any]]],
    output_dir: Path,
) -> list[Path]:
    """Write packs as ``chunk-01.jsonl``, ``chunk-02.jsonl``, and so on.

    Args:
        chunks: Row packs.
        output_dir: Destination directory (cleared of old chunks first).

    Returns:
        Paths written, in order.
    """
    clear_chunks(output_dir)
    paths: list[Path] = []
    for index, chunk in enumerate(chunks, start=1):
        path = chunk_path(output_dir, index)
        write_jsonl(path, chunk)
        paths.append(path)
    return paths


def iter_chunk_paths(chunks_dir: Path) -> list[Path]:
    """List chunk files in sorted name order.

    Args:
        chunks_dir: Directory containing ``chunk-*.jsonl``.

    Returns:
        Sorted paths.
    """
    return sorted(chunks_dir.glob("chunk-*.jsonl"))


def merge_chunk_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate ``label_llm`` and leave ``label`` empty for the reviewer.

    Args:
        rows: Concatenated chunk records.

    Returns:
        Copies with ``label`` set to ``""``.

    Raises:
        ValueError: If any row has a missing or invalid ``label_llm``.
    """
    merged: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        label_llm = str(row.get("label_llm") or "").strip().lower()
        if label_llm not in LABEL_SET:
            raise ValueError(
                f"row {index} id={row.get('id')!r}: label_llm must be one of "
                f"{LABELS}, got {row.get('label_llm')!r}"
            )
        item = dict(row)
        item["label_llm"] = label_llm
        item["label"] = ""
        merged.append(item)
    return merged


def format_counts(values: Sequence[str]) -> str:
    """Format a Counter as ``key=n`` pairs sorted by key.

    Args:
        values: Observed labels or language codes.

    Returns:
        Human-readable summary, or ``(none)``.
    """
    counts = Counter(values)
    if not counts:
        return "(none)"
    return ", ".join(f"{key}={counts[key]}" for key in sorted(counts))


def existing_holdout_count(gold_path: Path | None) -> int:
    """Count holdout rows in gold, or fall back to the known 80.

    Args:
        gold_path: Existing gold JSONL, if present.

    Returns:
        Holdout size used to size the *new* holdout slice.
    """
    if gold_path is None or not gold_path.is_file():
        return DEFAULT_EXISTING_HOLDOUT
    return count_holdout(load_jsonl(gold_path))


def mark_review_required(
    rows: Sequence[dict[str, Any]],
    *,
    holdout_n: int,
    dev_n: int,
    seed: int = DEFAULT_SEED,
) -> list[dict[str, Any]]:
    """Flag rows a human must check before ``merge_gold``.

    Required: every ``label_llm == neg``, every ``llm_confidence == low``,
    and every row allocated to future holdout/dev (stratified by
    ``label_llm`` × EN/non-EN). Remaining high-confidence train rows stay
    ``review_required: false``.

    Args:
        rows: Merged review records with ``label_llm`` filled.
        holdout_n: New holdout seats (target total minus existing 80).
        dev_n: Dev seats (~80).
        seed: Allocation seed (must match :mod:`nlp.eval.merge_gold`).

    Returns:
        Copies with boolean ``review_required``.
    """
    allocated = allocate_new_splits(
        rows,
        holdout_n=holdout_n,
        dev_n=dev_n,
        seed=seed,
        label_field="label_llm",
    )
    hold_dev_ids = {
        str(row.get("id"))
        for row in allocated
        if row.get("split") in {"holdout", "dev"}
    }
    marked: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        label_llm = str(item.get("label_llm") or "").strip().lower()
        confidence = str(item.get("llm_confidence") or "").strip().lower()
        item["review_required"] = bool(
            label_llm == "neg"
            or confidence == "low"
            or str(item.get("id")) in hold_dev_ids
        )
        marked.append(item)
    return marked


def cmd_split(args: argparse.Namespace) -> int:
    """Run the ``split`` subcommand.

    Args:
        args: Parsed CLI namespace.

    Returns:
        Process exit code.
    """
    exclude = gold_ids(load_jsonl(args.gold)) if args.gold.is_file() else set()
    candidates = filter_candidates(load_jsonl(args.input), exclude)
    chunks = split_into_chunks(candidates, args.chunk_size)
    paths = write_chunks(chunks, args.output_dir)
    print(
        f"Wrote {len(candidates)} rows in {len(paths)} chunks "
        f"to {args.output_dir} (excluded {len(exclude)} gold ids)"
    )
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    """Run the ``merge`` subcommand.

    Args:
        args: Parsed CLI namespace.

    Returns:
        Process exit code.
    """
    paths = iter_chunk_paths(args.chunks_dir)
    if not paths:
        raise ValueError(f"no chunk-*.jsonl files in {args.chunks_dir}")
    raw: list[dict[str, Any]] = []
    for path in paths:
        raw.extend(load_jsonl(path))
    merged = merge_chunk_rows(raw)
    write_jsonl(args.output, merged)
    print(f"Wrote {len(merged)} rows to {args.output}")
    print("label_llm: " + format_counts([row["label_llm"] for row in merged]))
    print(
        "language: "
        + format_counts([str(row.get("language") or "") for row in merged])
    )
    return 0


def cmd_select(args: argparse.Namespace) -> int:
    """Run the ``select`` subcommand.

    Args:
        args: Parsed CLI namespace.

    Returns:
        Process exit code.
    """
    rows = load_jsonl(args.input)
    existing = existing_holdout_count(args.gold)
    holdout_n = max(0, args.holdout_target - existing)
    marked = mark_review_required(
        rows, holdout_n=holdout_n, dev_n=args.dev_n, seed=args.seed
    )
    output = args.output if args.output is not None else args.input
    write_jsonl(output, marked)
    n_required = sum(1 for row in marked if row["review_required"])
    print(
        f"Wrote {len(marked)} rows to {output} "
        f"(review_required={n_required}, new_holdout={holdout_n}, "
        f"dev={args.dev_n}, existing_holdout={existing})"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list.

    Returns:
        Parsed namespace with ``command`` set.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    split = sub.add_parser(
        "split",
        help="Write chunk-NN.jsonl packs, excluding existing gold ids.",
    )
    split.add_argument("--input", required=True, type=Path)
    split.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    split.add_argument("--output-dir", type=Path, default=DEFAULT_CHUNK_DIR)
    split.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)

    merge = sub.add_parser(
        "merge",
        help="Concatenate labelled chunks into gold_v3_review.jsonl.",
    )
    merge.add_argument("--chunks-dir", type=Path, default=DEFAULT_CHUNK_DIR)
    merge.add_argument("--output", type=Path, default=DEFAULT_REVIEW)

    select = sub.add_parser(
        "select",
        help="Set review_required on neg, low-confidence, holdout, and dev.",
    )
    select.add_argument("--input", type=Path, default=DEFAULT_REVIEW)
    select.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Destination JSONL. Default: overwrite --input.",
    )
    select.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    select.add_argument(
        "--holdout-target",
        type=int,
        default=DEFAULT_HOLDOUT_TARGET,
        help="Total holdout size including existing gold holdout.",
    )
    select.add_argument("--dev-n", type=int, default=DEFAULT_DEV_N)
    select.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list.

    Returns:
        Process exit code.
    """
    args = parse_args(argv)
    if args.command == "split":
        return cmd_split(args)
    if args.command == "merge":
        return cmd_merge(args)
    if args.command == "select":
        return cmd_select(args)
    raise ValueError(f"unknown command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
