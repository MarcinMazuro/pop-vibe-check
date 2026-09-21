import pytest

from nlp.catalog import get_model, list_models, selected_model
from nlp.registry import available_models


class TestCatalog:
    def test_lists_xlmr_v2_and_v21(self) -> None:
        ids = [model.model_id for model in list_models()]
        assert ids == ["distilbert-sent", "xlmr-sent", "xlmr-sent-v2.1"]

    def test_v21_is_selected(self) -> None:
        champion = selected_model()
        assert champion.model_id == "xlmr-sent-v2.1"
        assert champion.selected is True
        assert get_model("xlmr-sent").selected is False

    def test_artifact_uris(self) -> None:
        v2 = get_model("xlmr-sent")
        v21 = get_model("xlmr-sent-v2.1")
        assert v2.artifact_uri == "gs://co-tf-artifacts-dev/nlp/models/xlmr-sent/"
        assert v21.artifact_uri == (
            "gs://co-tf-artifacts-dev/nlp/models/xlmr-sent-v2.1/"
        )
        assert v2.vertex_model_resource == (
            "projects/891032629527/locations/europe-central2/models/1068281099500650496"
        )
        assert v21.vertex_model_resource == (
            "projects/891032629527/locations/europe-central2/models/406814904230608896"
        )
        assert v21.vertex_endpoint_resource == (
            "projects/891032629527/locations/europe-central2/"
            "endpoints/co-nlp-endpoint-dev"
        )
        assert v2.vertex_endpoint_resource is None

    def test_gold_v3_holdout_comparison(self) -> None:
        v2 = get_model("xlmr-sent").holdout
        v21 = get_model("xlmr-sent-v2.1").holdout
        assert v2.n == v21.n == 200
        assert v21.macro_f1 > v2.macro_f1
        assert v21.f1_neg > v2.f1_neg
        assert v21.en_macro_f1 is not None and v2.en_macro_f1 is not None
        assert v21.en_macro_f1 > v2.en_macro_f1
        assert v21.report_path.endswith("report-xlmr-v2.1-goldv3.json")

    def test_v21_training_snapshot(self) -> None:
        v21 = get_model("xlmr-sent-v2.1")
        assert v21.trained_at == "2026-09-20"
        assert v21.train_epochs == 3
        assert v21.train_steps == 2379
        assert v21.train_loss is not None
        assert v21.best_dev_macro_f1 is not None

    def test_unknown_id_fails_loudly(self) -> None:
        with pytest.raises(KeyError, match="does-not-exist"):
            get_model("does-not-exist")

    def test_catalog_ids_are_not_dataflow_factories(self) -> None:
        names = available_models()
        assert names == ("stub", "vertex")
        assert "xlmr-sent" not in names
        assert "xlmr-sent-v2.1" not in names
