"""Génération déterministe des commandes ERP."""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

# Cible express_eligible (oubli du jeu fourni, confirmé par l'enseignant) : règle de
# calcul du notebook (cellule 8), adaptée au vocabulaire de l'ERP. L'application
# en a une copie dans src/domain/eligibility.py ; un test vérifie leur accord.
ZONE_PENALTY = {"centre": 0.0, "suburb": 0.20, "rural": 0.45}
WEATHER_PENALTY = {"clear": 0.0, "rain": 0.10, "wind": 0.15, "snow": 0.25}


def express_probability(order: dict[str, object]) -> float:
    """Probabilité d'éligibilité express : sigmoïde d'un score métier linéaire."""
    weekend = order["weekend"] if order["weekend"] is not None else int(order["day_of_week"] >= 5)
    preparation = order["preparation_time_min"] if order["preparation_time_min"] is not None else 25.0
    score = (
        2.5
        - 0.18 * order["distance_km"]
        - 0.035 * preparation
        - 0.035 * order["weight_kg"]
        - ZONE_PENALTY[order["delivery_zone"]]
        - WEATHER_PENALTY[order["weather"]]
        + 1.8 * order["stock_available"]
        + 1.3 * order["carrier_capacity"] / 50
        + 0.15 * (order["customer_type"] == "business")
        - 0.40 * weekend
        - 0.08 * max(order["hour"] - 18, 0)
    )
    return 1 / (1 + math.exp(-score))


class OrderGenerator:
    """Produit les flux métier sans dépendre d'une base de données."""

    @staticmethod
    def build(sequence: int, order_date: date) -> dict[str, object]:
        rng = random.Random(sequence)
        order = {
            "order_id": f"ERP-{sequence:08d}",
            "order_date": order_date,
            "hour": 8 + sequence % 12,
            "day_of_week": order_date.weekday(),
            "weekend": int(order_date.weekday() >= 5) if order_date >= date(2015, 7, 1) else None,
            "distance_km": round(rng.uniform(1, 40), 2),
            "order_value_eur": round(rng.uniform(15, 250), 2),
            "weight_kg": round(rng.uniform(0.2, 25), 2),
            "stock_available": rng.randint(0, 1),
            "preparation_time_min": (
                round(rng.uniform(5, 45), 2) if order_date >= date(2017, 7, 1) else None
            ),
            "carrier_capacity": round(rng.uniform(5, 50), 2),
            "weather": rng.choice(["clear", "rain", "wind", "snow"]),
            "delivery_zone": rng.choice(["centre", "suburb", "rural"]),
            "customer_type": rng.choice(["individual", "business"]),
        }
        # Tiré après les caractéristiques : elles restent identiques à celles d'avant.
        order["express_eligible"] = int(rng.random() < express_probability(order))
        return order

    def old_history(self, count: int, today: date, first_sequence: int = 1) -> list[dict[str, object]]:
        return self._history(count, date(2015, 1, 1), min(date(2022, 12, 31), today - timedelta(days=1)), first_sequence)

    def recent_history(self, count: int, today: date, first_sequence: int = 1) -> list[dict[str, object]]:
        return self._history(count, date(2023, 1, 1), today - timedelta(days=1), first_sequence)

    def live_batch(self, first_sequence: int, size: int, live_date: date) -> list[dict[str, object]]:
        return [
            self.build(sequence, live_date)
            for sequence in range(first_sequence, first_sequence + size)
        ]

    def _history(self, count: int, start: date, end: date, first_sequence: int) -> list[dict[str, object]]:
        if count <= 0 or end < start:
            return []
        span_days = (end - start).days + 1
        return [
            self.build(sequence, start + timedelta(days=(sequence - first_sequence) % span_days))
            for sequence in range(first_sequence, first_sequence + count)
        ]
