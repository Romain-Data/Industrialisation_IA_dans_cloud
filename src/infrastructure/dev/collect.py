"""
Génère les données synthétiques pour l'environnement de dev
"""

import numpy as np
import pandas as pd

from src.abstraction.collect import Collect
from src.domain.eligibility import eligibility_probability


class CollectDev(Collect):
    """Générateur de commandes synthétiques étiquetées par la règle de calcul du notebook."""

    def collect_data(self, n_rows=6000, random_state=42):
        """
        Génère un jeu de données fictif représentant des commandes.
        Le jeu de données est volontairement synthétique afin que le notebook
        soit exécutable sans source externe.
        """
        rng = np.random.default_rng(random_state)

        order_date = pd.date_range(
            start="2025-01-01",
            end="2025-12-31",
            periods=n_rows
        )

        hour = rng.integers(7, 23, size=n_rows)
        day_of_week = pd.Series(order_date).dt.dayofweek.to_numpy()
        weekend = (day_of_week >= 5).astype(int)

        data = pd.DataFrame({
            "order_id": [f"CMD-{i:06d}" for i in range(1, n_rows + 1)],
            "order_date": order_date,
            "hour": hour,
            "day_of_week": day_of_week,
            "weekend": weekend,
            "distance_km": np.round(rng.gamma(shape=2.0, scale=4.0, size=n_rows), 2),
            "order_value_eur": np.round(rng.uniform(10, 250, size=n_rows), 2),
            "weight_kg": np.round(rng.uniform(0.2, 25, size=n_rows), 2),
            "stock_available": rng.binomial(1, 0.85, size=n_rows),
            "preparation_time_min": np.round(
                rng.normal(loc=25, scale=10, size=n_rows).clip(5, 90),
                1
            ),
            # Vocabulaire et échelles de l'ERP (ADR-0007) : capacité de 5 à 50.
            "carrier_capacity": np.round(
                rng.uniform(5, 50, size=n_rows),
                2
            ),
            "weather": rng.choice(
                ["clear", "rain", "wind", "snow"],
                size=n_rows,
                p=[0.60, 0.20, 0.12, 0.08]
            ),
            "delivery_zone": rng.choice(
                ["centre", "suburb", "rural"],
                size=n_rows,
                p=[0.40, 0.40, 0.20]
            ),
            "customer_type": rng.choice(
                ["individual", "business"],
                size=n_rows,
                p=[0.75, 0.25]
            ),
        })

        # Cible : règle de calcul du notebook, adaptée au vocabulaire ERP (domaine).
        probability = eligibility_probability(data)

        data["express_eligible"] = rng.binomial(1, probability)

        return data
