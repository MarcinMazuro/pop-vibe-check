from types import SimpleNamespace

import pytest

from nlp.base import Sentiment, SentimentClassifier, normalize_predicted_label
from nlp.endpoint.classifier import VertexEndpointClassifier, parse_prediction
from nlp.registry import available_models, load_classifier


class FakeEndpoint:
    def __init__(self, predictions, deployed_model_id="distilbert@3"):
        self.predictions = predictions
        self.deployed_model_id = deployed_model_id
        self.calls = []

    def predict(self, instances, timeout=None):
        self.calls.append((instances, timeout))
        return SimpleNamespace(
            predictions=self.predictions,
            deployed_model_id=self.deployed_model_id,
        )


class TestParsePrediction:
    def test_dict_label_and_score(self):
        assert parse_prediction({"label": "pos", "score": 0.91}) == ("pos", 0.91)

    def test_hf_label_alias(self):
        assert parse_prediction({"label": "LABEL_0", "score": 0.4}) == ("neg", 0.4)

    def test_list_of_scored_labels_picks_argmax(self):
        raw = [
            {"label": "neg", "score": 0.1},
            {"label": "neu", "score": 0.2},
            {"label": "pos", "score": 0.7},
        ]
        assert parse_prediction(raw) == ("pos", 0.7)

    def test_three_logits(self):
        label, score = parse_prediction([0.0, 0.0, 5.0])
        assert label == "pos"
        assert score > 0.9

    def test_plain_string(self):
        assert parse_prediction("neutral") == ("neu", 1.0)

    def test_rejects_garbage(self):
        with pytest.raises(ValueError, match="Unsupported"):
            parse_prediction(None)

    def test_normalize_unknown(self):
        with pytest.raises(ValueError, match="Cannot map"):
            normalize_predicted_label("happy")


class TestVertexEndpointClassifier:
    def test_satisfies_the_protocol(self):
        clf = VertexEndpointClassifier(
            endpoint_id="ep",
            project="proj",
            endpoint=FakeEndpoint([{"label": "pos", "score": 0.8}]),
        )
        assert isinstance(clf, SentimentClassifier)

    def test_requires_env(self, monkeypatch):
        monkeypatch.delenv("VERTEX_ENDPOINT_ID", raising=False)
        monkeypatch.delenv("VERTEX_PROJECT", raising=False)
        with pytest.raises(RuntimeError, match="VERTEX_ENDPOINT_ID"):
            VertexEndpointClassifier()

    def test_reads_env(self, monkeypatch):
        monkeypatch.setenv("VERTEX_ENDPOINT_ID", "ep-from-env")
        monkeypatch.setenv("VERTEX_PROJECT", "proj-from-env")
        fake = FakeEndpoint([{"label": "neg", "score": 0.6}])
        clf = VertexEndpointClassifier(endpoint=fake)
        result = clf.classify("terrible")
        assert result == Sentiment("neg", 0.6, "vertex/distilbert@3")
        assert fake.calls[0][0] == [{"text": "terrible"}]

    def test_batch_order_and_count_mismatch(self):
        clf = VertexEndpointClassifier(
            endpoint_id="ep",
            project="p",
            endpoint=FakeEndpoint([{"label": "pos", "score": 1.0}]),
        )
        with pytest.raises(RuntimeError, match="returned 1 predictions for 2"):
            clf.classify_batch(["a", "b"])

    def test_empty_batch(self):
        clf = VertexEndpointClassifier(
            endpoint_id="ep",
            project="p",
            endpoint=FakeEndpoint([]),
        )
        assert clf.classify_batch([]) == []

    def test_does_not_invent_neu_on_bad_payload(self):
        clf = VertexEndpointClassifier(
            endpoint_id="ep",
            project="p",
            endpoint=FakeEndpoint(["not-a-label"]),
        )
        with pytest.raises(ValueError):
            clf.classify("anything")

    def test_retries_then_raises(self):
        class Flaky:
            def __init__(self):
                self.n = 0

            def predict(self, instances, timeout=None):
                self.n += 1
                raise DummyUnavailable()

        class DummyUnavailable(Exception):
            def __init__(self):
                super().__init__("unavailable")
                self.code = 503

        flaky = Flaky()
        clf = VertexEndpointClassifier(
            endpoint_id="ep",
            project="p",
            endpoint=flaky,
        )
        with pytest.raises(DummyUnavailable):
            clf.classify("x")
        assert flaky.n == 5


class TestRegistryVertex:
    def test_vertex_is_registered(self):
        assert "vertex" in available_models()

    def test_vertex_factory_fails_without_env(self, monkeypatch):
        monkeypatch.delenv("VERTEX_ENDPOINT_ID", raising=False)
        monkeypatch.delenv("VERTEX_PROJECT", raising=False)
        with pytest.raises(RuntimeError, match="VERTEX_ENDPOINT_ID"):
            load_classifier("vertex")
