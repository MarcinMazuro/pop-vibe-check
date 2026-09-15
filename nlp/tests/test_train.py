"""CPU-safe helpers for XLM-RoBERTa training (no torch import required)."""

from nlp.training.labels import MODEL_NAME
from nlp.training.train import fp16_enabled, parse_args, stratified_indices


class TestFp16Enabled:
    def test_off_without_cuda(self) -> None:
        assert fp16_enabled(False) is False

    def test_on_with_cuda(self) -> None:
        assert fp16_enabled(True) is True


class TestParseArgs:
    def test_model_cache_dir_optional(self) -> None:
        args = parse_args(["--cache-dir", "/tmp/hf-datasets"])
        assert args.cache_dir == "/tmp/hf-datasets"
        assert args.model_cache_dir is None
        assert args.skip_mlflow is False
        assert args.model_name == MODEL_NAME
        assert args.batch_size == 8
        assert args.output_dir == "./xlmr-sent"
        assert args.skip_clapai is False
        assert args.include_sst2 is False

    def test_model_name_override(self) -> None:
        args = parse_args(["--model-name", "distilbert-base-uncased"])
        assert args.model_name == "distilbert-base-uncased"


class TestStratifiedIndices:
    def test_each_class_in_both_splits(self) -> None:
        labels = [0] * 10 + [1] * 10 + [2] * 10
        train, eval_idx = stratified_indices(labels, 0.1, seed=33)
        assert len(train) + len(eval_idx) == 30
        assert set(train).isdisjoint(eval_idx)
        train_labels = {labels[i] for i in train}
        eval_labels = {labels[i] for i in eval_idx}
        assert train_labels == {0, 1, 2}
        assert eval_labels == {0, 1, 2}
