"""Journal des imports ETL dans notre base (table erp_imports, migration 0003)."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.abstraction.import_journal import ImportJournal
from src.domain.entities import ImportReport
from src.infrastructure.order_store import ImportRecord


class SqlAlchemyImportJournal(ImportJournal):
    """Implémentation SQLAlchemy, dans la même base que les commandes."""

    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)

    def last_order_id(self, source: str) -> str | None:
        query = (
            select(ImportRecord.last_order_id)
            .where(ImportRecord.source == source, ImportRecord.last_order_id.is_not(None))
            .order_by(ImportRecord.id.desc())
            .limit(1)
        )
        with self._engine.connect() as connection:
            return connection.execute(query).scalar()

    def record(self, source: str, report: ImportReport) -> None:
        with Session(self._engine) as session:
            session.add(
                ImportRecord(
                    source=source,
                    started_at=report.started_at,
                    finished_at=report.finished_at,
                    last_order_id=report.last_order_id,
                    read=report.read,
                    imported=report.imported,
                    already_present=report.already_present,
                    rejected=report.rejected,
                    unlabeled=report.unlabeled,
                )
            )
            session.commit()
