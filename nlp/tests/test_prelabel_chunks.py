"""CPU-safe tests for nlp.eval.prelabel_chunks (no LLM API)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nlp.eval.merge_gold import allocate_new_splits
from nlp.eval.prelabel_chunks import (
    filter_candidates,
    format_counts,
    gold_ids,
    main,
    mark_review_required,
    merge_chunk_rows,
    parse_args,
    split_into_chunks,
    to_prelabel_row,
)
from nlp.eval.sample_gold import load_jsonl, write_jsonl


def _row(
    rid: str,
    text: str,
    *,
    language: str = "en",
    event_tag: str = "launch",
    source: str = "youtube",
    created_utc: str | None = "2024-01-01T00:00:00Z",
    **extra: object,
) -> dict:
    item = {
        "id": rid,
        "text": text,
        "language": language,
        "event_tag": event_tag,
        "source": source,
        **extra,
    }
    if created_utc is not None:
        item["created_utc"] = created_utc
    return item


class TestFilterAndSplit:
    def test_excludes_gold_ids_and_dedupes_text(self) -> None:
        gold = [_row("keep-out", "already labelled")]
        candidates = [
            _row("keep-out", "already labelled"),
            _row("a", "hello world"),
            _row("b", "hello world"),
            _row("c", "  "),
            _row("d", "unique"),
            {"id": "", "text": "no id"},
        ]
        filtered = filter_candidates(candidates, gold_ids(gold))
        assert [row["id"] for row in filtered] == ["a", "d"]

    def test_prelabel_schema_keeps_optional_fields(self) -> None:
        row = to_prelabel_row(
            _row("a", "hello", source="reddit", created_utc="2025-01-01")
        )
        assert row["label_llm"] == ""
        assert row["llm_confidence"] == ""
        assert row["source"] == "reddit"
        assert row["created_utc"] == "2025-01-01"
        assert "label" not in row

    def test_split_into_chunks_remainder(self) -> None:
        rows = [_row(str(i), f"t{i}") for i in range(5)]
        chunks = split_into_chunks(rows, 2)
        assert [len(chunk) for chunk in chunks] == [2, 2, 1]

    def test_split_rejects_zero_size(self) -> None:
        with pytest.raises(ValueError, match="chunk_size"):
            split_into_chunks([], 0)


class TestMergeChunks:
    def test_validates_label_llm_and_clears_label(self) -> None:
        rows = [
            {**_row("a", "yes"), "label_llm": "POS", "label": "should-clear"},
            {**_row("b", "meh"), "label_llm": "neu"},
        ]
        merged = merge_chunk_rows(rows)
        assert [row["label_llm"] for row in merged] == ["pos", "neu"]
        assert all(row["label"] == "" for row in merged)

    def test_rejects_missing_label_llm(self) -> None:
        with pytest.raises(ValueError, match="label_llm"):
            merge_chunk_rows([_row("a", "nope")])

    def test_format_counts(self) -> None:
        assert format_counts(["en", "fr", "en"]) == "en=2, fr=1"
        assert format_counts([]) == "(none)"


class TestSelect:
    def test_marks_neg_low_and_holdout_dev(self) -> None:
        rows = [
            {
                **_row("neg-en", "bad", language="en"),
                "label_llm": "neg",
                "llm_confidence": "high",
            },
            {
                **_row("neg-fr", "nul", language="fr"),
                "label_llm": "neg",
                "llm_confidence": "med",
            },
            {
                **_row("low-en", "hmm", language="en"),
                "label_llm": "neu",
                "llm_confidence": "low",
            },
            {
                **_row("low-fr", "bof", language="fr"),
                "label_llm": "pos",
                "llm_confidence": "low",
            },
        ]
        for i in range(8):
            lang = "en" if i % 2 == 0 else "fr"
            rows.append(
                {
                    **_row(f"pos-{i}", f"great {i}", language=lang),
                    "label_llm": "pos",
                    "llm_confidence": "high",
                }
            )
        marked = mark_review_required(rows, holdout_n=2, dev_n=2, seed=33)
        by_id = {row["id"]: row for row in marked}
        assert by_id["neg-en"]["review_required"] is True
        assert by_id["neg-fr"]["review_required"] is True
        assert by_id["low-en"]["review_required"] is True
        assert by_id["low-fr"]["review_required"] is True

        allocated = allocate_new_splits(
            rows, holdout_n=2, dev_n=2, seed=33, label_field="label_llm"
        )
        hold_dev = {
            row["id"] for row in allocated if row["split"] in {"holdout", "dev"}
        }
        for rid in hold_dev:
            assert by_id[rid]["review_required"] is True
        for row in marked:
            if (
                row["id"] not in hold_dev
                and row["label_llm"] != "neg"
                and row["llm_confidence"] != "low"
            ):
                assert row["review_required"] is False


class TestParseArgs:
    def test_split_defaults(self, tmp_path: Path) -> None:
        args = parse_args(["split", "--input", str(tmp_path / "c.jsonl")])
        assert args.command == "split"
        assert args.chunk_size == 100
        assert args.output_dir == Path("nlp/eval/artifacts/prelabel")

    def test_select_defaults(self) -> None:
        args = parse_args(["select"])
        assert args.holdout_target == 200
        assert args.dev_n == 80
        assert args.output is None

    def test_requires_subcommand(self) -> None:
        with pytest.raises(SystemExit):
            parse_args([])


class TestCliRoundtrip:
    def test_split_merge_select_main(self, tmp_path: Path) -> None:
        gold = tmp_path / "gold.jsonl"
        write_jsonl(
            gold,
            [
                {
                    **_row("old-1", "old hold"),
                    "label": "pos",
                    "split": "holdout",
                }
            ],
        )
        candidates = tmp_path / "cand.jsonl"
        cand_rows = [_row("old-1", "old hold")]
        for i in range(5):
            cand_rows.append(
                _row(
                    f"new-{i}",
                    f"comment {i}",
                    language="en" if i < 3 else "fr",
                )
            )
        write_jsonl(candidates, cand_rows)
        chunks_dir = tmp_path / "prelabel"
        assert (
            main(
                [
                    "split",
                    "--input",
                    str(candidates),
                    "--gold",
                    str(gold),
                    "--output-dir",
                    str(chunks_dir),
                    "--chunk-size",
                    "2",
                ]
            )
            == 0
        )
        chunk_files = sorted(chunks_dir.glob("chunk-*.jsonl"))
        assert [p.name for p in chunk_files] == [
            "chunk-01.jsonl",
            "chunk-02.jsonl",
            "chunk-03.jsonl",
        ]
        assert len(load_jsonl(chunk_files[0])) == 2
        assert len(load_jsonl(chunk_files[2])) == 1

        labels = ["pos", "neu", "neg", "pos", "neu"]
        confs = ["high", "low", "high", "high", "med"]
        all_chunk_rows = []
        for path in chunk_files:
            all_chunk_rows.extend(load_jsonl(path))
        assert len(all_chunk_rows) == 5
        for row, label, conf in zip(all_chunk_rows, labels, confs, strict=True):
            row["label_llm"] = label
            row["llm_confidence"] = conf
        write_jsonl(chunk_files[0], all_chunk_rows[:2])
        write_jsonl(chunk_files[1], all_chunk_rows[2:4])
        write_jsonl(chunk_files[2], all_chunk_rows[4:])

        review = tmp_path / "review.jsonl"
        assert (
            main(
                [
                    "merge",
                    "--chunks-dir",
                    str(chunks_dir),
                    "--output",
                    str(review),
                ]
            )
            == 0
        )
        merged = load_jsonl(review)
        assert len(merged) == 5
        assert all(row["label"] == "" for row in merged)
        assert {row["label_llm"] for row in merged} <= {"pos", "neu", "neg"}

        out = tmp_path / "review_selected.jsonl"
        assert (
            main(
                [
                    "select",
                    "--input",
                    str(review),
                    "--output",
                    str(out),
                    "--gold",
                    str(gold),
                    "--holdout-target",
                    "3",
                    "--dev-n",
                    "1",
                    "--seed",
                    "33",
                ]
            )
            == 0
        )
        selected = load_jsonl(out)
        assert any(row["review_required"] for row in selected)
        assert all(
            row["label_llm"] != "neg" or row["review_required"] for row in selected
        )
        assert all(
            row["llm_confidence"] != "low" or row["review_required"] for row in selected
        )


def test_stale_chunks_are_cleared(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text("", encoding="utf-8")
    chunks_dir = tmp_path / "prelabel"
    chunks_dir.mkdir()
    stale = chunks_dir / "chunk-99.jsonl"
    stale.write_text(json.dumps(_row("stale", "gone")) + "\n", encoding="utf-8")
    candidates = tmp_path / "cand.jsonl"
    write_jsonl(candidates, [_row("a", "one"), _row("b", "two")])
    main(
        [
            "split",
            "--input",
            str(candidates),
            "--gold",
            str(gold),
            "--output-dir",
            str(chunks_dir),
            "--chunk-size",
            "10",
        ]
    )
    assert not stale.exists()
    assert (chunks_dir / "chunk-01.jsonl").is_file()
