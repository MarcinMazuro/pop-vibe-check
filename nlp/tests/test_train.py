"""CPU-safe helpers for DistilBERT training (no torch import required)."""

from nlp.training.train import fp16_enabled, parse_args


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
