"""Règle de calcul de l'éligibilité express : celle qui génère la cible des données.

C'est la règle de la cellule 8 du notebook, reprise à l'identique dans la correction
de l'enseignant (`generate_labeled_orders`) : un score métier linéaire, transformé en
probabilité par une sigmoïde, puis un tirage. Les données de l'ERP auraient dû être
étiquetées par cette règle ; la cible manquait (oubli confirmé par l'enseignant).

Seul le vocabulaire est adapté à l'ERP (ADR-0007). Correspondances avec le notebook :

| Notebook                          | ERP                       | Valeur |
|-----------------------------------|---------------------------|--------|
| météo normal / pluie / neige       | clear / rain / snow       | 0 / 0,10 / 0,25 |
| météo orage (0,30)                 | wind (pas d'équivalent)   | 0,15 (hypothèse) |
| centre / banlieue / rurale         | centre / suburb / rural   | 0 / 0,20 (moyenne de 0,10 et 0,25) / 0,45 |
| client premium (+0,15)             | business                  | +0,15 |
| capacité de 0 à 1 (× 1,3)          | capacité de 5 à 50        | × 1,3 / 50 |

Le simulateur ERP (`erp_simulator/`, système externe) applique la même règle avec sa
propre copie ; un test vérifie que les deux donnent les mêmes probabilités.
"""

import numpy as np
import pandas as pd

ZONE_PENALTY = {"centre": 0.0, "suburb": 0.20, "rural": 0.45}
WEATHER_PENALTY = {"clear": 0.0, "rain": 0.10, "wind": 0.15, "snow": 0.25}
BUSINESS_BONUS = 0.15
CAPACITY_SCALE = 50

# Valeurs manquantes des anciennes données de l'ERP (avant les migrations de 2015 et
# 2017) : le week-end se déduit du jour, le temps de préparation prend la moyenne du
# notebook (25 min).
DEFAULT_PREPARATION_TIME_MIN = 25.0


def eligibility_score(orders: pd.DataFrame) -> pd.Series:
    """Score métier latent : plus il est élevé, plus la livraison express est faisable."""
    weekend = orders["weekend"].fillna((orders["day_of_week"] >= 5).astype(int))
    preparation = orders["preparation_time_min"].fillna(DEFAULT_PREPARATION_TIME_MIN)

    return (
        2.5
        - 0.18 * orders["distance_km"]
        - 0.035 * preparation
        - 0.035 * orders["weight_kg"]
        - orders["delivery_zone"].map(ZONE_PENALTY)
        - orders["weather"].map(WEATHER_PENALTY)
        + 1.8 * orders["stock_available"]
        + 1.3 * orders["carrier_capacity"] / CAPACITY_SCALE
        + BUSINESS_BONUS * (orders["customer_type"] == "business").astype(int)
        - 0.40 * weekend
        - 0.08 * np.maximum(orders["hour"] - 18, 0)
    )


def eligibility_probability(orders: pd.DataFrame) -> pd.Series:
    """Probabilité d'éligibilité express : sigmoïde du score métier."""
    return 1 / (1 + np.exp(-eligibility_score(orders)))
