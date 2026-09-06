import pytest

from nlp import LABELS, load_classifier
from nlp.base import Sentiment, SentimentClassifier
from nlp.registry import available_models
from nlp.stub.classifier import FALLBACK_SCORE, MATCH_SCORE, StubClassifier


class TestSentiment:
    def test_accepts_valid_label_and_score(self):
        s = Sentiment("pos", 0.5, "stub/1")
        assert (s.label, s.score, s.model_version) == ("pos", 0.5, "stub/1")

    def test_rejects_unknown_label(self):
        with pytest.raises(ValueError, match="label must be one of"):
            Sentiment("positive", 0.5, "stub/1")

    @pytest.mark.parametrize("score", [-0.1, 1.1])
    def test_rejects_out_of_range_score(self, score):
        with pytest.raises(ValueError, match="score must be within"):
            Sentiment("pos", score, "stub/1")


class TestStubClassifier:
    def test_satisfies_the_protocol(self):
        assert isinstance(StubClassifier(), SentimentClassifier)

    def test_positive_keywords_win(self):
        result = StubClassifier().classify("An absolute masterpiece, I loved it")
        assert result.label == "pos"
        assert result.score == MATCH_SCORE

    def test_negative_keywords_win(self):
        result = StubClassifier().classify("Buggy, boring and a total waste, refund")
        assert result.label == "neg"
        assert result.score == MATCH_SCORE

    def test_punctuation_does_not_hide_keywords(self):
        assert StubClassifier().classify("(amazing!!!)").label == "pos"

    def test_case_is_ignored(self):
        assert StubClassifier().classify("AMAZING").label == "pos"

    def test_balanced_keywords_fall_through_to_the_hash(self):
        result = StubClassifier().classify("amazing but also terrible")
        assert result.score == FALLBACK_SCORE

    @pytest.mark.parametrize("text", ["", "   ", "\n\t"])
    def test_empty_text_is_neutral(self, text):
        assert StubClassifier().classify(text).label == "neu"

    def test_always_returns_a_valid_label(self):
        texts = ["", "🎉", "ok", "a" * 5000, "Expedition 33", "не знаю"]
        assert all(StubClassifier().classify(t).label in LABELS for t in texts)

    def test_is_deterministic_across_instances(self):
        # The reproducibility guarantee depends on this: two workers
        # classifying the same text must agree.
        texts = ["Expedition 33", "no keywords here at all", "🎉", ""]
        first = [StubClassifier().classify(t) for t in texts]
        second = [StubClassifier().classify(t) for t in texts]
        assert first == second

    def test_fallback_spreads_across_labels(self):
        # A constant fallback would make every unmatched record share one
        # label and hide problems in downstream aggregation.
        texts = [f"neutral filler text number {i}" for i in range(200)]
        labels = {StubClassifier().classify(t).label for t in texts}
        assert labels == set(LABELS)

    def test_reports_its_model_version(self):
        assert StubClassifier("stub/test").classify("anything").model_version == (
            "stub/test"
        )

    def test_batch_matches_per_element(self):
        texts = ["amazing", "terrible", "", "something else entirely"]
        clf = StubClassifier()
        assert clf.classify_batch(texts) == [clf.classify(t) for t in texts]

    def test_empty_batch(self):
        assert StubClassifier().classify_batch([]) == []


class TestRegistry:
    def test_stub_is_registered(self):
        assert "stub" in available_models()

    def test_vertex_is_registered(self):
        assert "vertex" in available_models()

    def test_loads_the_stub_by_default(self):
        assert isinstance(load_classifier(), StubClassifier)

    def test_unknown_model_fails_loudly(self):
        with pytest.raises(KeyError, match="Unknown NLP model"):
            load_classifier("does-not-exist")
