"""ETL des commandes ERP : MongoDB (lecture seule) -> nettoyage -> validation -> notre base.

Exécution d'un import (ADR-0007) : lancé toutes les heures par l'orchestrateur, ou à la
main avec `python -m src.etl.erp_import` (mode `etl` de l'image Docker).

- **Incrémental** : on reprend après la dernière commande lue (journal `erp_imports`,
  ou à défaut la commande ERP la plus récente de notre base).
- **Idempotent** : rejouer un import n'insère aucun doublon.
- **Méfiant** : chaque commande est nettoyée puis validée ; une commande invalide est
  rejetée (comptée et journalisée avec ses motifs), jamais importée.
"""

import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from src.abstraction.import_journal import ImportJournal
from src.abstraction.order_repository import OrderRepository
from src.abstraction.order_store import OrderStore
from src.domain.order_quality import clean_order, order_errors

logger = logging.getLogger(__name__)

SOURCE = "erp-mongodb"
ERP_ID_PREFIX = "ERP-"
MAX_LOGGED_REJECTIONS = 20


@dataclass
class ImportReport:
    """Compte rendu d'un import."""

    started_at: datetime
    finished_at: datetime | None = None
    last_order_id: str | None = None
    read: int = 0
    imported: int = 0
    already_present: int = 0
    rejected: int = 0
    unlabeled: int = 0
    rejection_reasons: Counter = field(default_factory=Counter)


def import_erp_orders(
    source: OrderRepository,
    store: OrderStore,
    journal: ImportJournal,
    batch_size: int = 1000,
) -> ImportReport:
    """Importe toutes les nouvelles commandes de la source, par lots, et journalise l'import."""
    report = ImportReport(started_at=datetime.now(UTC))
    position = journal.last_order_id(SOURCE) or store.last_order_id(ERP_ID_PREFIX)
    report.last_order_id = position

    while batch := source.get_labeled_after(position, batch_size):
        valid = []
        for order, label in batch:
            report.read += 1
            order = clean_order(order)
            errors = order_errors(order)
            if label not in (0, 1, None):
                errors.append(f"express_eligible invalide ({label!r})")
            if errors:
                _reject(report, order.order_id, errors)
                continue
            if label is None:
                report.unlabeled += 1
            valid.append(_to_row(order, label))

        inserted = store.import_orders(valid)
        report.imported += inserted
        report.already_present += len(valid) - inserted
        # La position avance aussi après les commandes rejetées : elles ne sont pas relues.
        identifiers = [order.order_id for order, _ in batch if order.order_id]
        if not identifiers or (position is not None and identifiers[-1] <= position):
            break  # aucune progression possible : on s'arrête plutôt que de boucler
        position = identifiers[-1]
        report.last_order_id = position

    report.finished_at = datetime.now(UTC)
    journal.record(SOURCE, report)
    logger.info(
        "Import ERP : %d lues, %d importées, %d déjà présentes, %d rejetées, %d sans cible.",
        report.read, report.imported, report.already_present, report.rejected, report.unlabeled,
    )
    return report


def _reject(report, order_id, errors):
    """Compte et journalise une commande rejetée (les premières seulement, en détail)."""
    report.rejected += 1
    report.rejection_reasons.update(error.split(" (")[0] for error in errors)
    if report.rejected <= MAX_LOGGED_REJECTIONS:
        logger.warning("Commande %s rejetée : %s", order_id, "; ".join(errors))


def _to_row(order, label):
    """OrderEntity validée -> ligne de la table commandes (date ERP en created_at)."""
    row = asdict(order)
    order_date = row.pop("order_date")
    row["created_at"] = order_date or datetime.now(UTC)
    row["express_eligible"] = label
    return row


def main():
    """Point d'entrée : un import complet depuis la base analytique de l'ERP."""
    from src.config import (
        DATABASE_URL,
        ERP_IMPORT_BATCH_SIZE,
        ERP_MONGO_COLLECTION,
        ERP_MONGO_DATABASE,
        ERP_MONGO_URI,
    )
    from src.infrastructure.import_journal import SqlAlchemyImportJournal
    from src.infrastructure.mongo_order_repository import MongoOrderRepository
    from src.infrastructure.order_store import SqlAlchemyOrderStore

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    source = MongoOrderRepository(
        ERP_MONGO_URI, database=ERP_MONGO_DATABASE, collection=ERP_MONGO_COLLECTION
    )
    try:
        report = import_erp_orders(
            source,
            SqlAlchemyOrderStore(DATABASE_URL),
            SqlAlchemyImportJournal(DATABASE_URL),
            batch_size=ERP_IMPORT_BATCH_SIZE,
        )
    finally:
        source.close()

    if report.rejection_reasons:
        print(f"Motifs de rejet : {dict(report.rejection_reasons)}")
    return report


if __name__ == "__main__":
    main()
