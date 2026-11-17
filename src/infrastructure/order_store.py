from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from src.abstraction.order_store import DuplicateOrderError, OrderStore
from src.domain.features import FEATURE_COLUMNS, TARGET_COLUMN
from src.infrastructure.migrations import current_revision, head_revision


class Base(DeclarativeBase):
    pass


class OrderRecord(Base):
    """Table unique `commandes`, une ligne par commande (ADR-0001)."""

    __tablename__ = "commandes"
    __table_args__ = (
        CheckConstraint("weekend IN (0, 1)", name="ck_commandes_weekend"),
        CheckConstraint("stock_available IN (0, 1)", name="ck_commandes_stock"),
        CheckConstraint(
            "express_eligible IN (0, 1)", name="ck_commandes_express_eligible"
        ),
    )

    order_id: Mapped[str] = mapped_column(String, primary_key=True)
    hour: Mapped[int] = mapped_column(Integer)
    day_of_week: Mapped[int] = mapped_column(Integer)
    weekend: Mapped[int] = mapped_column(Integer)
    distance_km: Mapped[float] = mapped_column(Float)
    order_value_eur: Mapped[float] = mapped_column(Float)
    weight_kg: Mapped[float] = mapped_column(Float)
    stock_available: Mapped[int] = mapped_column(Integer)
    preparation_time_min: Mapped[float] = mapped_column(Float)
    carrier_capacity: Mapped[float] = mapped_column(Float)
    weather: Mapped[str] = mapped_column(String)
    delivery_zone: Mapped[str] = mapped_column(String)
    customer_type: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    # Résultat observé (cible d'entraînement), connu après coup (migration 0002).
    express_eligible: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PredictionRecord(Base):
    """Dernière prédiction calculée pour une commande."""

    __tablename__ = "predictions"

    order_id: Mapped[str] = mapped_column(String, primary_key=True)
    express_eligible: Mapped[bool] = mapped_column(Boolean)
    decision: Mapped[str] = mapped_column(String)
    probability: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String)
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)


class SqlAlchemyOrderStore(OrderStore):
    """Implémentation SQLAlchemy, valable pour SQLite (dev) et PostgreSQL (prod)."""

    def __init__(self, database_url):
        # Le schéma est créé par Alembic (alembic upgrade head), pas ici.
        self._engine = create_engine(database_url)

    def save(self, order):
        record = OrderRecord(**order)

        with Session(self._engine) as session:
            session.add(record)
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                if session.get(OrderRecord, order["order_id"]) is not None:
                    raise DuplicateOrderError(order["order_id"]) from error
                raise

    def get(self, order_id):
        with Session(self._engine) as session:
            record = session.get(OrderRecord, order_id)

            if record is None:
                return None

            return {
                column: getattr(record, column)
                for column in ["order_id", *FEATURE_COLUMNS]
            }

    def record_outcome(self, order_id, express_eligible):
        with Session(self._engine) as session:
            record = session.get(OrderRecord, order_id)

            if record is None:
                return None

            record.express_eligible = int(express_eligible)
            record.outcome_recorded_at = datetime.now(UTC)
            session.commit()

            return {
                "order_id": order_id,
                "express_eligible": bool(record.express_eligible),
                "recorded_at": _as_utc(record.outcome_recorded_at),
            }

    def export_labeled_orders(self):
        columns = [
            OrderRecord.order_id,
            OrderRecord.created_at.label("order_date"),
            *(getattr(OrderRecord, column) for column in FEATURE_COLUMNS),
            OrderRecord.express_eligible.label(TARGET_COLUMN),
        ]
        query = (
            select(*columns)
            .where(OrderRecord.express_eligible.is_not(None))
            .order_by(OrderRecord.created_at)
        )

        with self._engine.connect() as connection:
            orders = pd.read_sql(query, connection)

        # Dates en UTC sans fuseau : même représentation pour SQLite et PostgreSQL.
        orders["order_date"] = pd.to_datetime(orders["order_date"], utc=True).dt.tz_localize(None)
        return orders

    def ping(self):
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001 - sonde de santé : toute erreur = base injoignable
            return False

        return True

    def save_prediction(self, prediction):
        with Session(self._engine) as session:
            session.merge(PredictionRecord(**prediction))
            session.commit()

    def get_prediction(self, order_id):
        with Session(self._engine) as session:
            record = session.get(PredictionRecord, order_id)

            if record is None:
                return None

            prediction = {
                column.name: getattr(record, column.name)
                for column in PredictionRecord.__table__.columns
            }

            prediction["predicted_at"] = _as_utc(prediction["predicted_at"])
            return prediction

    def schema_is_current(self):
        try:
            return current_revision(self._engine) == head_revision()
        except Exception:  # noqa: BLE001 - sonde de santé : toute erreur = schéma non vérifiable
            return False


def _as_utc(value):
    """SQLite ne conserve pas le fuseau horaire : les dates relues sont en UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
