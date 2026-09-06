import json

from nlp.eval.evaluate import classification_metrics, confusion_matrix, evaluate_files
from nlp.eval.sample_gold import sample_records, write_jsonl


class TestMetrics:
    def test_perfect_accuracy(self):
        gold = ["pos", "neu", "neg"]
        pred = ["pos", "neu", "neg"]
        metrics = classification_metrics(gold, pred)
        assert metrics["accuracy"] == 1.0
        assert metrics["macro_f1"] == 1.0
        assert metrics["f1_pos"] == 1.0

    def test_confusion_shape(self):
        matrix = confusion_matrix(["pos", "pos", "neg"], ["pos", "neg", "neg"])
        assert matrix["pos"]["pos"] == 1
        assert matrix["pos"]["neg"] == 1
        assert matrix["neg"]["neg"] == 1

    def test_evaluate_files_join(self, tmp_path):
        gold = tmp_path / "gold.jsonl"
        pred = tmp_path / "pred.jsonl"
        gold.write_text(
            json.dumps(
                {
                    "id": "1",
                    "label": "pos",
                    "language": "en",
                    "source": "youtube",
                }
            )
            + "\n"
            + json.dumps(
                {
                    "id": "2",
                    "label": "neg",
                    "language": "fr",
                    "source": "youtube",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        pred.write_text(
            json.dumps({"id": "1", "predicted": "pos"})
            + "\n"
            + json.dumps({"id": "2", "predicted": "pos"})
            + "\n",
            encoding="utf-8",
        )
        report = evaluate_files(gold, pred)
        assert report["n"] == 2
        assert report["metrics"]["accuracy"] == 0.5
        assert "en" in report["by_language"]
        assert "youtube" in report["by_source"]


class TestSampleGold:
    def test_stratified_cap(self, tmp_path):
        rows = [
            {
                "id": f"yt-{i}",
                "source": "youtube",
                "language": "en",
                "text": f"hello {i}",
            }
            for i in range(40)
        ] + [
            {
                "id": f"yt-fr-{i}",
                "source": "youtube",
                "language": "fr",
                "text": f"bonjour {i}",
            }
            for i in range(10)
        ]
        sampled = sample_records(rows, 20, seed=1)
        assert len(sampled) == 20
        assert all(row["label"] == "" for row in sampled)
        languages = {row["language"] for row in sampled}
        assert languages == {"en", "fr"}

        out = tmp_path / "gold.jsonl"
        write_jsonl(out, sampled)
        assert out.read_text(encoding="utf-8").count("\n") == 20
