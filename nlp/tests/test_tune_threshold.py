import json

import pytest

from nlp.eval.predict import label_and_score, label_probs
from nlp.eval.tune_threshold import (
    apply_threshold,
    choose_threshold,
    join_split,
    main,
    tune,
)


def _probs(neg, neu, pos):
    return {"neg": neg, "neu": neu, "pos": pos}


class TestLabelProbs:
    def test_sums_to_one_and_matches_argmax(self):
        logits = [2.0, 1.0, -1.0]
        probs = label_probs(logits)
        assert set(probs) == {"neg", "neu", "pos"}
        assert sum(probs.values()) == pytest.approx(1.0)
        label, score = label_and_score(logits)
        assert label == "neg"
        assert probs["neg"] == pytest.approx(score)


class TestApplyThreshold:
    def test_none_is_argmax(self):
        assert apply_threshold(_probs(0.35, 0.45, 0.20), None) == "neu"

    def test_threshold_promotes_neg(self):
        assert apply_threshold(_probs(0.35, 0.45, 0.20), 0.30) == "neg"

    def test_below_threshold_picks_neu_or_pos(self):
        assert apply_threshold(_probs(0.25, 0.30, 0.45), 0.30) == "pos"
        assert apply_threshold(_probs(0.25, 0.45, 0.30), 0.30) == "neu"

    def test_high_threshold_can_drop_argmax_neg(self):
        assert apply_threshold(_probs(0.50, 0.30, 0.20), 0.60) == "neu"


def _rows():
    gold = [
        {"id": "a", "label": "neg", "split": "dev"},
        {"id": "b", "label": "neu", "split": "dev"},
        {"id": "c", "label": "pos", "split": "dev"},
        {"id": "d", "label": "neg", "split": "holdout"},
        {"id": "e", "label": "neu", "split": "holdout"},
        {"id": "f", "label": "pos", "split": "train"},
    ]
    pred = [
        {"id": "a", "probs": _probs(0.35, 0.45, 0.20)},
        {"id": "b", "probs": _probs(0.10, 0.80, 0.10)},
        {"id": "c", "probs": _probs(0.05, 0.15, 0.80)},
        {"id": "d", "probs": _probs(0.40, 0.50, 0.10)},
        {"id": "e", "probs": _probs(0.20, 0.70, 0.10)},
        {"id": "f", "probs": _probs(0.90, 0.05, 0.05)},
    ]
    return gold, pred


class TestTune:
    def test_join_split_filters(self):
        gold, pred = _rows()
        labels, probs = join_split(gold, pred, "dev")
        assert labels == ["neg", "neu", "pos"]
        assert len(probs) == 3

    def test_join_split_requires_probs(self):
        gold, pred = _rows()
        del pred[0]["probs"]
        with pytest.raises(ValueError, match="probs"):
            join_split(gold, pred, "dev")

    def test_choose_ties_go_to_larger_threshold(self):
        curve = [
            {"threshold": 0.2, "metrics": {"macro_f1": 0.9}},
            {"threshold": 0.3, "metrics": {"macro_f1": 0.9}},
            {"threshold": 0.4, "metrics": {"macro_f1": 0.5}},
        ]
        assert choose_threshold(curve, "macro_f1") == 0.3

    def test_tune_picks_on_dev_and_reports_holdout(self):
        gold, pred = _rows()
        report = tune(gold, pred, grid=[0.30, 0.50])
        assert report["chosen_threshold"] == 0.30
        assert report["dev"]["argmax"]["metrics"]["recall_neg"] == 0.0
        assert report["dev"]["threshold"]["metrics"]["accuracy"] == 1.0
        assert report["holdout"]["threshold"]["n"] == 2
        assert report["holdout"]["threshold"]["metrics"]["recall_neg"] == 1.0

    def test_main_writes_report(self, tmp_path):
        gold, pred = _rows()
        gold_path = tmp_path / "gold.jsonl"
        pred_path = tmp_path / "pred.jsonl"
        out = tmp_path / "report.json"
        gold_path.write_text("\n".join(json.dumps(r) for r in gold), encoding="utf-8")
        pred_path.write_text("\n".join(json.dumps(r) for r in pred), encoding="utf-8")
        assert (
            main(
                [
                    "--gold",
                    str(gold_path),
                    "--pred",
                    str(pred_path),
                    "--output",
                    str(out),
                ]
            )
            == 0
        )
        assert "chosen_threshold" in json.loads(out.read_text(encoding="utf-8"))
