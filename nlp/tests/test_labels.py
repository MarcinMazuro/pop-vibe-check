import json

import pytest

from nlp.training.labels import (
    LabeledText,
    map_goemotions_labels,
    map_sentiment140_label,
    map_sst2_label,
    map_tweet_eval_label,
)
from nlp.training.loaders import load_own_domain, mix_corpus


class TestLabelMaps:
    @pytest.mark.parametrize("idx,expected", [(0, "neg"), (1, "pos")])
    def test_sst2(self, idx, expected):
        assert map_sst2_label(idx) == expected

    def test_sst2_rejects_neutral_invention(self):
        with pytest.raises(ValueError, match="0 or 1"):
            map_sst2_label(2)

    @pytest.mark.parametrize("idx,expected", [(0, "neg"), (1, "neu"), (2, "pos")])
    def test_tweet_eval(self, idx, expected):
        assert map_tweet_eval_label(idx) == expected

    @pytest.mark.parametrize("idx,expected", [(0, "neg"), (2, "neu"), (4, "pos")])
    def test_sentiment140(self, idx, expected):
        assert map_sentiment140_label(idx) == expected

    def test_goemotions_negative_wins_tie(self):
        assert map_goemotions_labels(["joy", "anger"]) == "neg"

    def test_goemotions_positive(self):
        assert map_goemotions_labels(["love", "admiration"]) == "pos"

    def test_goemotions_neutral_and_empty(self):
        assert map_goemotions_labels(["neutral"]) == "neu"
        assert map_goemotions_labels([]) == "neu"

    def test_labeled_text_rejects_unknown_class(self):
        with pytest.raises(ValueError, match="label must be one of"):
            LabeledText("hi", "happy", "sst2")


class TestOwnDomainLoader:
    def test_jsonl(self, tmp_path):
        path = tmp_path / "gold.jsonl"
        path.write_text(
            json.dumps({"text": "loved it", "label": "pos", "source": "youtube"})
            + "\n"
            + json.dumps({"text": "meh", "label": "neu"})
            + "\n",
            encoding="utf-8",
        )
        rows = load_own_domain(path)
        assert [r.label for r in rows] == ["pos", "neu"]
        assert rows[0].source == "youtube"
        assert rows[1].source == "own_domain"

    def test_rejects_bad_json(self, tmp_path):
        path = tmp_path / "bad.jsonl"
        path.write_text("{nope}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="invalid JSON"):
            load_own_domain(path)

    def test_mix_drops_empty_text(self):
        mixed = mix_corpus(
            [
                [LabeledText("a", "pos", "sst2"), LabeledText("  ", "neg", "sst2")],
                [LabeledText("b", "neu", "tweet_eval")],
            ]
        )
        assert [r.text for r in mixed] == ["a", "b"]
