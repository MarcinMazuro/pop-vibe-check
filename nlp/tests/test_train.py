"""CPU-safe helpers for XLM-RoBERTa training (no torch import required)."""

import json

from nlp.training.labels import MODEL_NAME, LabeledText
from nlp.training.train import (
    build_stage2_train_rows,
    fp16_enabled,
    parse_args,
    split_train_eval,
    stratified_indices,
)


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
        assert args.init_from is None
        assert args.dev_from_gold is None
        assert args.replay_n == 5000
        assert args.warmup_ratio == 0.1
        assert args.weight_decay == 0.01
        assert args.early_stopping_patience == 0

    def test_model_name_override(self) -> None:
        args = parse_args(["--model-name", "distilbert-base-uncased"])
        assert args.model_name == "distilbert-base-uncased"

    def test_stage2_flags(self) -> None:
        args = parse_args(
            [
                "--init-from",
                "/models/xlmr-sent",
                "--dev-from-gold",
                "/gold/gold_v3.jsonl",
                "--replay-n",
                "0",
                "--warmup-ratio",
                "0.0",
                "--weight-decay",
                "0.0",
                "--early-stopping-patience",
                "2",
                "--lr",
                "1e-5",
                "--own-domain-factor",
                "2",
            ]
        )
        assert args.init_from == "/models/xlmr-sent"
        assert args.dev_from_gold == "/gold/gold_v3.jsonl"
        assert args.replay_n == 0
        assert args.warmup_ratio == 0.0
        assert args.weight_decay == 0.0
        assert args.early_stopping_patience == 2
        assert args.lr == 1e-5
        assert args.own_domain_factor == 2


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


class TestBuildStage2TrainRows:
    def test_gold_plus_replay(self) -> None:
        gold = [LabeledText("g", "pos", "own_domain")]
        mix = [LabeledText(f"m{i}", "neu", "clapai") for i in range(10)]
        rows = build_stage2_train_rows(
            gold, mix, own_domain_factor=2, replay_n=4, seed=33
        )
        gold_texts = [row.text for row in rows if row.source == "own_domain"]
        replay_texts = [row.text for row in rows if row.source == "clapai"]
        assert gold_texts == ["g", "g"]
        assert len(replay_texts) == 4

    def test_replay_zero_is_gold_only(self) -> None:
        gold = [LabeledText("g", "neg", "own_domain")]
        mix = [LabeledText("m", "pos", "clapai")]
        rows = build_stage2_train_rows(
            gold, mix, own_domain_factor=3, replay_n=0, seed=1
        )
        assert [row.text for row in rows] == ["g", "g", "g"]


class TestSplitTrainEval:
    def test_dev_from_gold_uses_dev_rows(self, tmp_path) -> None:
        path = tmp_path / "gold.jsonl"
        path.write_text(
            json.dumps({"text": "train", "label": "pos", "split": "train"})
            + "\n"
            + json.dumps({"text": "dev", "label": "neu", "split": "dev"})
            + "\n",
            encoding="utf-8",
        )
        pool = [LabeledText("mix", "neg", "clapai")]
        args = parse_args(["--dev-from-gold", str(path)])
        train_rows, eval_rows = split_train_eval(pool, args)
        assert [row.text for row in train_rows] == ["mix"]
        assert [row.text for row in eval_rows] == ["dev"]

    def test_default_is_stratified_holdout(self) -> None:
        pool = [LabeledText(f"p{i}", "pos", "x") for i in range(10)] + [
            LabeledText(f"n{i}", "neg", "x") for i in range(10)
        ]
        args = parse_args([])
        train_rows, eval_rows = split_train_eval(pool, args)
        assert len(train_rows) + len(eval_rows) == 20
        assert {row.text for row in train_rows}.isdisjoint(
            {row.text for row in eval_rows}
        )
        assert {row.label for row in eval_rows} <= {"pos", "neg"}
