"""ETL ERP -> notre base : nettoyage, validation, import incrémental et idempotent (ADR-0007)."""

from dataclasses import fields, replace
from datetime import UTC, datetime

import pytest
from mlflow import MlflowClient

from src.domain.entities import OrderEntity
from src.domain.order_quality import clean_order, order_errors
from src.etl.erp_import import SOURCE, import_erp_orders
from src.infrastructure.collect_ducklake import CollectDuckLake
from src.infrastructure.dev.in_memory_order_repository import InMemoryOrderRepository
from src.infrastructure.ducklake_store import DuckLakeSnapshotStore
from src.infrastructure.import_journal import SqlAlchemyImportJournal
from src.infrastructure.order_store import SqlAlchemyOrderStore
from src.training.pipeline import run_training
from tests.erp_simulator import erp_orders

ENTITY_FIELDS = {f.name for f in fields(OrderEntity)}


def to_labeled_entity(order):
    """Commande du simulateur ERP -> (OrderEntity, cible), comme les lit le repository."""
    values = {key: order[key] for key in ENTITY_FIELDS if key != "order_date"}
    order_date = datetime.combine(order["order_date"], datetime.min.time(), UTC)
    return OrderEntity(**values, order_date=order_date), order["express_eligible"]


@pytest.fixture
def store(database_url):
    return SqlAlchemyOrderStore(database_url)


@pytest.fixture
def journal(database_url):
    return SqlAlchemyImportJournal(database_url)


@pytest.fixture
def erp():
    return InMemoryOrderRepository([to_labeled_entity(order) for order in erp_orders(40)])


# --- Nettoyage et validation d'une commande ------------------------------------------------


def test_valid_erp_order_has_no_error():
    order, _ = to_labeled_entity(erp_orders(1)[0])

    assert order_errors(clean_order(order)) == []


def test_cleaning_derives_missing_weekend_and_normalises_categories():
    order, _ = to_labeled_entity(erp_orders(1)[0])
    dirty = replace(order, weekend=None, day_of_week=6, weather="  Rain ")

    cleaned = clean_order(dirty)

    assert cleaned.weekend == 1
    assert cleaned.weather == "rain"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"weather": "orage"}, "weather inconnu"),
        ({"distance_km": -3.0}, "distance_km négatif"),
        ({"hour": 27}, "hour hors bornes"),
        ({"stock_available": 2}, "stock_available doit valoir 0 ou 1"),
        ({"preparation_time_min": None}, "preparation_time_min manquant"),
        ({"weight_kg": "lourd"}, "weight_kg non numérique"),
    ],
)
def test_invalid_orders_are_rejected_with_their_reason(change, reason):
    order, _ = to_labeled_entity(erp_orders(1)[0])

    assert any(reason in error for error in order_errors(replace(order, **change)))


# --- Import -------------------------------------------------------------------------------


def test_import_copies_erp_orders_with_their_target(erp, store, journal):
    report = import_erp_orders(erp, store, journal, batch_size=15)
    exported = store.export_labeled_orders()

    assert (report.read, report.imported, report.rejected) == (40, 40, 0)
    assert report.last_order_id == "ERP-00000040"
    assert len(exported) == 40
    first = exported.set_index("order_id").loc["ERP-00000001"]
    source_order, label = erp.get_labeled_after(None, 1)[0]
    assert first["express_eligible"] == label
    assert first["order_date"] == source_order.order_date.replace(tzinfo=None)


def test_rerunning_the_import_adds_nothing(erp, store, journal):
    import_erp_orders(erp, store, journal)

    report = import_erp_orders(erp, store, journal)

    assert (report.read, report.imported) == (0, 0)
    assert len(store.export_labeled_orders()) == 40


def test_import_is_incremental(erp, store, journal):
    import_erp_orders(erp, store, journal)
    for order in erp_orders(5, first_sequence=41):
        entity, label = to_labeled_entity(order)
        erp._orders[entity.order_id], erp._labels[entity.order_id] = entity, label

    report = import_erp_orders(erp, store, journal)

    assert (report.read, report.imported) == (5, 5)
    assert report.last_order_id == "ERP-00000045"


def test_invalid_orders_are_counted_not_imported_and_not_reread(store, journal):
    labeled = [to_labeled_entity(order) for order in erp_orders(10)]
    labeled[3] = (replace(labeled[3][0], weather="orage"), labeled[3][1])
    labeled[9] = (replace(labeled[9][0], distance_km=-1.0), labeled[9][1])  # dernière du lot
    erp = InMemoryOrderRepository(labeled)

    report = import_erp_orders(erp, store, journal)

    assert (report.imported, report.rejected) == (8, 2)
    assert report.rejection_reasons == {"weather inconnu": 1, "distance_km négatif": 1}
    assert store.get(labeled[3][0].order_id) is None
    # La position a dépassé les rejets : le passage suivant ne les relit pas.
    assert import_erp_orders(erp, store, journal).read == 0


def test_orders_without_target_are_imported_but_not_used_for_training(store, journal):
    labeled = [to_labeled_entity(order) for order in erp_orders(10)]
    labeled[0] = (labeled[0][0], None)
    erp = InMemoryOrderRepository(labeled)

    report = import_erp_orders(erp, store, journal)

    assert (report.imported, report.unlabeled) == (10, 1)
    assert store.get(labeled[0][0].order_id) is not None
    assert len(store.export_labeled_orders()) == 9


def test_import_resumes_from_our_data_when_the_journal_is_empty(erp, store, journal):
    # 20 commandes ERP déjà dans notre base, mais aucune trace dans le journal (perdu).
    already = [to_labeled_entity(order) for order in erp_orders(20)]
    store.import_orders([
        {**{k: v for k, v in vars(o).items() if k != "order_date"},
         "created_at": o.order_date, "express_eligible": label}
        for o, label in already
    ])

    report = import_erp_orders(erp, store, journal)

    assert (report.read, report.imported) == (20, 20)


def test_each_import_is_journaled(erp, store, journal):
    import_erp_orders(erp, store, journal, batch_size=15)

    assert journal.last_order_id(SOURCE) == "ERP-00000040"


# --- De l'ERP au modèle -------------------------------------------------------------------


def test_model_is_trained_on_imported_erp_data(tmp_path, monkeypatch, store, journal, valid_order):
    """Point i du barème : entraînement sur les données de production (ERP via l'ETL)."""
    monkeypatch.chdir(tmp_path)
    erp = InMemoryOrderRepository([to_labeled_entity(order) for order in erp_orders(400)])
    import_erp_orders(erp, store, journal)
    # Une commande de test restée avec l'ancien vocabulaire : écartée au nettoyage.
    store.save({"order_id": "CMD-ancienne", **valid_order, "weather": "pluie"})
    store.record_outcome("CMD-ancienne", True)
    lake = DuckLakeSnapshotStore(f"sqlite:///{tmp_path / 'lake.sqlite'}", tmp_path / "lake")

    _, metrics, run_id = run_training(CollectDuckLake(store, lake))

    params = MlflowClient().get_run(run_id).data.params
    assert params["data_source"] == "ducklake"
    assert params["rows_dropped"] == "1"
    assert params["training_rows"] == "400"
    assert 0.5 < metrics["roc_auc"] <= 1
