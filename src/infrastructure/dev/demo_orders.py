"""Commandes de démonstration pour la page du logisticien (ADR-0013, hors cas métier).

Mêmes plages de valeurs et même vocabulaire que le simulateur ERP du cours : les
commandes sont réalistes pour le modèle. Leur identifiant commence par `DEMO-` pour les
distinguer des vraies commandes ; sans résultat réel, elles n'entrent jamais dans un
entraînement.
"""

import random
import uuid
from datetime import UTC, datetime
from typing import Any

from src.domain.features import (
    CUSTOMER_TYPE_VALUES,
    DELIVERY_ZONE_VALUES,
    WEATHER_VALUES,
)

DEMO_PREFIX = "DEMO-"


def demo_order(rng: random.Random, now: datetime | None = None) -> dict[str, Any]:
    """Une commande au format du contrat `OrderFeatures`, datée de maintenant."""
    now = now or datetime.now(UTC)
    return {
        "order_id": f"{DEMO_PREFIX}{uuid.uuid4().hex[:8]}",
        "hour": now.hour,
        "day_of_week": now.weekday(),
        "weekend": int(now.weekday() >= 5),
        "distance_km": round(rng.uniform(1, 40), 2),
        "order_value_eur": round(rng.uniform(15, 250), 2),
        "weight_kg": round(rng.uniform(0.2, 25), 2),
        "stock_available": rng.randint(0, 1),
        "preparation_time_min": round(rng.uniform(5, 45), 2),
        "carrier_capacity": round(rng.uniform(5, 50), 2),
        "weather": rng.choice(WEATHER_VALUES),
        "delivery_zone": rng.choice(DELIVERY_ZONE_VALUES),
        "customer_type": rng.choice(CUSTOMER_TYPE_VALUES),
    }


def demo_orders(count: int, rng: random.Random | None = None) -> list[dict[str, Any]]:
    """`count` commandes de démonstration."""
    rng = rng or random.Random()
    return [demo_order(rng) for _ in range(count)]
