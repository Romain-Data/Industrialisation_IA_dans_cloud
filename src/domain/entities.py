"""Entités du domaine, indépendantes de toute technologie de stockage.

Alignées sur la correction de l'enseignant (`OrderEntity`) : une commande ne porte que
ses caractéristiques. La cible (`express_eligible`) n'en fait pas partie : on ne
prédit pas ce qu'on connaît ; elle est fournie à part pour l'entraînement.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class OrderEntity:
    """Commande : les 12 caractéristiques du modèle, son identifiant et sa date."""

    hour: int
    day_of_week: int
    weekend: int | None
    distance_km: float
    order_value_eur: float
    weight_kg: float
    stock_available: int
    preparation_time_min: float | None
    carrier_capacity: float
    weather: str
    delivery_zone: str
    customer_type: str
    order_id: str | None = None
    # Absente de la correction : la date de commande de l'ERP (utile à l'entraînement).
    order_date: datetime | None = None


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
    rejection_reasons: Counter[str] = field(default_factory=Counter)
