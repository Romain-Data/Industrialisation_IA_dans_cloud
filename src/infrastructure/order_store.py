from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Boolean,
    Float,
    Integer,
    String,
    create_engine,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from src.abstraction.order_store import DuplicateOrderError, OrderStore
from src.domain.features import FEATURE_COLUMNS
from src.infrastructure.migrations import current_revision, head_revision


class Base(DeclarativeBase):
    pass


class OrderRecord(Base):
    """Table unique `commandes`, une ligne par commande (ADR-0001)."""

    __tablename__ = "commandes"
    __table_args__ = (
        CheckConstraint("weekend IN (0, 1)", name="ck_commandes_weekend"),
        CheckConstraint("stock_available IN (0, 1)", name="ck_commandes_stock"),
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
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
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

    def ping(self):
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
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

            # SQLite ne conserve pas le fuseau horaire.
            if prediction["predicted_at"].tzinfo is None:
                prediction["predicted_at"] = prediction["predicted_at"].replace(
                    tzinfo=timezone.utc
                )

            return prediction

    def schema_is_current(self):
        try:
            return current_revision(self._engine) == head_revision()
        except Exception:
            return False
