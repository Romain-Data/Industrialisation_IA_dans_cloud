import joblib
import pytest

from src.domain.features import FEATURE_COLUMNS
from src.infrastructure.dev.collect import CollectDev
from src.serving.batch import batch_predict_orders, save_batch_predictions
from src.serving.model_loader import MODEL_FILENAME, load_model
from src.serving.predict import predict_order_eligibility
from tests.conftest import FakeModel


def test_predict_returns_eligible_decision(valid_order):
    result = predict_order_eligibility(valid_order, FakeModel(0.8))

    assert result["express_eligible"] is True
    assert result["decision"] == "oui"
    assert result["probability"] == 0.8
    assert {"model_version", "prediction_timestamp"} <= set(result)


def test_predict_returns_not_eligible_decision(valid_order):
    result = predict_order_eligibility(valid_order, FakeModel(0.2))

    assert result["express_eligible"] is False
    assert result["decision"] == "non"


def test_predict_threshold_is_configurable(valid_order):
    model = FakeModel(0.6)

    assert predict_order_eligibility(valid_order, model, threshold=0.5)["decision"] == "oui"
    assert predict_order_eligibility(valid_order, model, threshold=0.7)["decision"] == "non"


def test_predict_ignores_extra_keys(valid_order):
    valid_order["unused"] = 1

    assert predict_order_eligibility(valid_order, FakeModel())["decision"] == "oui"


def test_predict_rejects_missing_feature(valid_order):
    del valid_order["distance_km"]

    with pytest.raises(ValueError, match="Variables manquantes"):
        predict_order_eligibility(valid_order, FakeModel())


def test_predict_rejects_out_of_range_value(valid_order):
    valid_order["carrier_capacity"] = 1.5

    with pytest.raises(ValueError, match="capacité"):
        predict_order_eligibility(valid_order, FakeModel())


@pytest.fixture
def batch_input():
    return CollectDev().collect_data(n_rows=20)[FEATURE_COLUMNS]


def test_batch_adds_prediction_columns(batch_input):
    result = batch_predict_orders(batch_input, FakeModel(0.8))

    assert len(result) == 20
    assert set(result["decision"]) == {"oui"}
    assert set(result["express_eligible"]) == {1}
    assert (result["eligibility_probability"] == 0.8).all()


def test_batch_applies_threshold(batch_input):
    result = batch_predict_orders(batch_input, FakeModel(0.8), threshold=0.9)

    assert set(result["decision"]) == {"non"}


def test_batch_rejects_missing_column(batch_input):
    with pytest.raises(ValueError, match="Variables manquantes"):
        batch_predict_orders(batch_input.drop(columns="distance_km"), FakeModel())


def test_save_batch_predictions_writes_csv(batch_input, tmp_path):
    result = batch_predict_orders(batch_input, FakeModel())

    path = save_batch_predictions(result, tmp_path / "artifacts")

    assert path.name == "batch_predictions.csv"
    assert len(path.read_text().splitlines()) == 21


def test_load_model_raises_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="Modèle introuvable"):
        load_model(tmp_path)


def test_load_model_reads_saved_model(tmp_path):
    joblib.dump({"model": "ok"}, tmp_path / MODEL_FILENAME)

    assert load_model(tmp_path) == {"model": "ok"}
