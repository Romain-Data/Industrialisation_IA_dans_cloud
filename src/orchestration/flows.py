"""Flows Prefect : import ERP horaire, puis réentraînement s'il y a assez de nouvelles données.

L'entraînement est un processus d'exécution, pas une étape de construction de
l'application : il est orchestré ici, jamais par la CI/CD (cours #4, ADR-0009).

Chaque étape est une tâche Prefect : reprises automatiques en cas d'échec, durée et
résultat visibles dans l'interface, et l'enchaînement s'arrête proprement si une étape
échoue (pas d'entraînement sur un import raté).
"""

from prefect import flow, get_run_logger, task

from src.config import (
    DATABASE_URL,
    DUCKLAKE_CATALOG_URL,
    DUCKLAKE_DATA_PATH,
    ERP_IMPORT_BATCH_SIZE,
    ERP_MONGO_COLLECTION,
    ERP_MONGO_DATABASE,
    ERP_MONGO_URI,
    RETRAIN_MIN_NEW_ORDERS,
)
from src.etl.erp_import import import_erp_orders
from src.infrastructure.collect_ducklake import CollectDuckLake
from src.infrastructure.ducklake_store import DuckLakeSnapshotStore
from src.infrastructure.import_journal import SqlAlchemyImportJournal
from src.infrastructure.mongo_order_repository import MongoOrderRepository
from src.infrastructure.order_store import SqlAlchemyOrderStore
from src.training.pipeline import run_training
from src.training.retraining import orders_seen_by_last_training, should_retrain


@task(name="import-erp", retries=3, retry_delay_seconds=60)
def import_erp_task(batch_size: int = ERP_IMPORT_BATCH_SIZE) -> dict:
    """Importe les nouvelles commandes de l'ERP (MongoDB) dans notre base."""
    source = MongoOrderRepository(
        ERP_MONGO_URI, database=ERP_MONGO_DATABASE, collection=ERP_MONGO_COLLECTION
    )
    try:
        report = import_erp_orders(
            source,
            SqlAlchemyOrderStore(DATABASE_URL),
            SqlAlchemyImportJournal(DATABASE_URL),
            batch_size=batch_size,
        )
    finally:
        source.close()
    return {
        "read": report.read,
        "imported": report.imported,
        "rejected": report.rejected,
        "unlabeled": report.unlabeled,
        "last_order_id": report.last_order_id,
        "rejection_reasons": dict(report.rejection_reasons),
    }


@task(name="decide-retraining")
def decide_retraining_task(min_new_orders: int, force: bool) -> bool:
    """Réentraîner ? Oui si forcé, ou s'il y a assez de nouvelles commandes étiquetées."""
    logger = get_run_logger()
    labeled = SqlAlchemyOrderStore(DATABASE_URL).count_labeled_orders()
    seen = orders_seen_by_last_training()
    decision = force or should_retrain(labeled, seen, min_new_orders)
    logger.info(
        "Commandes étiquetées : %d, vues au dernier entraînement : %s, seuil : %d -> %s.",
        labeled, seen, min_new_orders, "réentraînement" if decision else "pas de réentraînement",
    )
    return decision


@task(name="train", retries=1, retry_delay_seconds=120)
def train_task() -> dict:
    """Entraîne sur un snapshot DuckLake des commandes importées ; promotion selon ADR-0002."""
    collector = CollectDuckLake(
        SqlAlchemyOrderStore(DATABASE_URL),
        DuckLakeSnapshotStore(DUCKLAKE_CATALOG_URL, DUCKLAKE_DATA_PATH),
    )
    _, metrics, run_id = run_training(collector)
    return {"run_id": run_id, **collector.tracking_params, **metrics}


@flow(name="erp-pipeline", log_prints=True)
def erp_pipeline(min_new_orders: int = RETRAIN_MIN_NEW_ORDERS, force_retrain: bool = False) -> dict:
    """Import ERP, puis réentraînement si utile. L'API recharge seule un nouveau champion."""
    imported = import_erp_task()
    result = {"import": imported, "training": None}
    if decide_retraining_task(min_new_orders, force_retrain):
        result["training"] = train_task()
    return result
