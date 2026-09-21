"""CPU-safe tests for nlp.eval.merge_gold."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nlp.eval.merge_gold import (
    allocate_new_splits,
    cohen_kappa,
    main,
    merge_gold_rows,
    parse_args,
    pick_stratified,
    prelabel_agreement,
    resolve_review_row,
)
from nlp.eval.sample_gold import load_jsonl, write_jsonl


def _gold(
    rid: str,
    label: str,
    *,
    split: str = "train",
    language: str = "en",
    text: str | None = None,
) -> dict[str, Any]:
    return {
        "id": rid,
        "text": text or f"text {rid}",
        "language": language,
        "event_tag": "launch",
        "source": "youtube",
        "label": label,
        "split": split,
    }


def _review(
    rid: str,
    label_llm: str,
    *,
    language: str = "en",
    review_required: bool = False,
    label: str = "",
    llm_confidence: str = "high",
) -> dict[str, Any]:
    return {
        "id": rid,
        "text": f"text {rid}",
        "language": language,
        "event_tag": "launch",
        "source": "youtube",
        "label_llm": label_llm,
        "llm_confidence": llm_confidence,
        "label": label,
        "review_required": review_required,
    }


class TestCohenKappa:
    def test_perfect_agreement(self) -> None:
        labels = ["pos", "neu", "neg", "pos"]
        assert cohen_kappa(labels, labels) == 1.0

    def test_hand_computed_partial(self) -> None:
        human = ["pos", "pos", "neg", "neu"]
        llm = ["pos", "neu", "neg", "neu"]
        # po=0.75; pe=5/16; kappa=0.4375/0.6875
        assert cohen_kappa(human, llm) == pytest.approx(0.4375 / 0.6875)

    def test_empty_and_length_mismatch(self) -> None:
        assert cohen_kappa([], []) == 0.0
        with pytest.raises(ValueError, match="length mismatch"):
            cohen_kappa(["pos"], ["pos", "neg"])


class TestResolveReviewRow:
    def test_required_without_human_is_dropped(self) -> None:
        assert resolve_review_row(_review("a", "neg", review_required=True)) is None

    def test_required_with_human_wins(self) -> None:
        row = resolve_review_row(
            _review("a", "pos", review_required=True, label="neg")
        )
        assert row is not None
        assert row["label"] == "neg"
        assert row["label_source"] == "human"

    def test_optional_takes_label_llm(self) -> None:
        row = resolve_review_row(_review("a", "neu"))
        assert row is not None
        assert row["label"] == "neu"
        assert row["label_source"] == "llm"

    def test_spot_check_human_on_optional(self) -> None:
        row = resolve_review_row(_review("a", "pos", label="neu"))
        assert row is not None
        assert row["label_source"] == "human"
        assert row["label"] == "neu"

    def test_optional_missing_llm_raises(self) -> None:
        with pytest.raises(ValueError, match="label_llm"):
            resolve_review_row(_review("a", ""))


class TestSplits:
    def test_old_holdout_kept_new_fills_targets(self) -> None:
        existing = [
            _gold(f"old-h-{i}", "pos", split="holdout", language="en")
            for i in range(4)
        ] + [
            _gold(f"old-t-{i}", "neu", split="train", language="fr")
            for i in range(3)
        ]
        review = []
        for i in range(12):
            lang = "en" if i % 2 == 0 else "fr"
            label = ("pos", "neu", "neg")[i % 3]
            review.append(
                _review(
                    f"new-{i}",
                    label,
                    language=lang,
                    review_required=True,
                    label=label,
                )
            )
        for i in range(12, 20):
            review.append(_review(f"new-{i}", "pos", language="en"))
        merged, agreement = merge_gold_rows(
            existing,
            review,
            holdout_target=8,
            dev_n=4,
            seed=33,
        )
        by_split: dict[str, list[str]] = {"holdout": [], "dev": [], "train": []}
        for row in merged:
            by_split[row["split"]].append(row["id"])
        for i in range(4):
            assert f"old-h-{i}" in by_split["holdout"]
        for i in range(3):
            assert f"old-t-{i}" in by_split["train"]
        assert len(by_split["holdout"]) == 8
        assert len(by_split["dev"]) == 4
        assert all(rid.startswith("new-") for rid in by_split["dev"])
        new_hold = [rid for rid in by_split["holdout"] if rid.startswith("new-")]
        assert len(new_hold) == 4
        assert agreement["n"] == 12
        assert agreement["dropped_unreviewed"] == 0

    def test_drops_unreviewed_required_and_dedupes(self) -> None:
        existing = [_gold("dup", "pos", split="train")]
        review = [
            _review("dup", "neg"),
            _review("need-me", "neg", review_required=True),
            _review("ok", "neu"),
            _review("ok", "pos"),
        ]
        merged, agreement = merge_gold_rows(
            existing, review, holdout_target=1, dev_n=0, seed=1
        )
        ids = [row["id"] for row in merged]
        assert ids.count("dup") == 1
        assert "need-me" not in ids
        assert "ok" in ids
        assert agreement["dropped_unreviewed"] == 1
        ok = next(row for row in merged if row["id"] == "ok")
        assert ok["label"] == "neu"
        assert ok["label_source"] == "llm"

    def test_human_only_drops_llm_train(self) -> None:
        existing = [_gold("old-h", "pos", split="holdout")]
        review = [
            _review("h1", "neg", review_required=True, label="neg", language="en"),
            _review("h2", "pos", review_required=True, label="pos", language="fr"),
            _review("llm1", "neu", language="en"),
            _review("llm2", "pos", language="fr"),
        ]
        merged, _agreement = merge_gold_rows(
            existing,
            review,
            holdout_target=2,
            dev_n=1,
            seed=33,
            human_only=True,
        )
        sources = {(row["id"], row["split"], row["label_source"]) for row in merged}
        assert ("old-h", "holdout", "human") in sources
        llm_train = [
            row
            for row in merged
            if row["label_source"] == "llm" and row["split"] == "train"
        ]
        assert llm_train == []
        assert all(
            row["label_source"] == "human" or row["split"] != "train" for row in merged
        )

    def test_agreement_report(self) -> None:
        rows = [
            {
                "label": "pos",
                "label_llm": "pos",
                "label_source": "human",
            },
            {
                "label": "pos",
                "label_llm": "neu",
                "label_source": "human",
            },
            {
                "label": "neg",
                "label_llm": "neg",
                "label_source": "human",
            },
            {
                "label": "neu",
                "label_llm": "neu",
                "label_source": "human",
            },
            {
                "label": "pos",
                "label_llm": "pos",
                "label_source": "llm",
            },
        ]
        report = prelabel_agreement(rows)
        assert report["n"] == 4
        assert report["accuracy"] == pytest.approx(0.75)
        assert report["cohen_kappa"] == pytest.approx(0.4375 / 0.6875)

    def test_pick_stratified_uses_both_en_buckets(self) -> None:
        rows = [_gold(f"en-{i}", "pos", language="en") for i in range(10)] + [
            _gold(f"fr-{i}", "pos", language="fr") for i in range(10)
        ]
        picked = pick_stratified(rows, 6, seed=33)
        langs = {row["language"] for row in picked}
        assert langs == {"en", "fr"}
        assert len(picked) == 6

    def test_allocate_preserves_order_and_counts(self) -> None:
        rows = [
            _gold(
                f"r-{i}",
                ("pos", "neu", "neg")[i % 3],
                language="en" if i < 6 else "es",
            )
            for i in range(12)
        ]
        allocated = allocate_new_splits(rows, holdout_n=4, dev_n=3, seed=7)
        assert [row["id"] for row in allocated] == [row["id"] for row in rows]
        assert sum(row["split"] == "holdout" for row in allocated) == 4
        assert sum(row["split"] == "dev" for row in allocated) == 3
        assert sum(row["split"] == "train" for row in allocated) == 5


class TestParseArgs:
    def test_defaults_and_human_only(self) -> None:
        args = parse_args(["--human-only"])
        assert args.human_only is True
        assert args.holdout_target == 200
        assert args.dev_n == 80
        assert args.output == Path("nlp/eval/artifacts/gold_v3.jsonl")
        assert args.agreement == Path("nlp/eval/artifacts/prelabel-agreement.json")


class TestCli:
    def test_main_writes_jsonl_and_agreement(self, tmp_path: Path) -> None:
        gold = tmp_path / "gold.jsonl"
        review = tmp_path / "review.jsonl"
        output = tmp_path / "gold_v3.jsonl"
        agreement = tmp_path / "prelabel-agreement.json"
        write_jsonl(gold, [_gold("old-h", "pos", split="holdout")])
        write_jsonl(
            review,
            [
                _review("h1", "neg", review_required=True, label="neu"),
                _review("llm1", "pos"),
            ],
        )
        assert (
            main(
                [
                    "--gold",
                    str(gold),
                    "--review",
                    str(review),
                    "--output",
                    str(output),
                    "--agreement",
                    str(agreement),
                    "--holdout-target",
                    "2",
                    "--dev-n",
                    "0",
                ]
            )
            == 0
        )
        rows = load_jsonl(output)
        assert {row["id"] for row in rows} == {"old-h", "h1", "llm1"}
        payload = json.loads(agreement.read_text(encoding="utf-8"))
        assert payload["n"] == 1
        assert payload["accuracy"] == 0.0
        h1 = next(row for row in rows if row["id"] == "h1")
        assert h1["label"] == "neu"
        assert h1["label_source"] == "human"
