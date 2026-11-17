"""Règle de calcul de la cible express_eligible (notebook, cellule 8, adaptée à l'ERP)."""

import math
from datetime import date

import pandas as pd
import pytest

from src.domain.eligibility import eligibility_probability
from tests.erp_simulator import TODAY, load_erp_module

erp_generator = load_erp_module("generator")


def test_simulator_and_domain_apply_the_same_rule():
    """La copie de la règle dans le simulateur (système externe) reste identique à la nôtre."""
    generator = erp_generator.OrderGenerator()
    # Commandes récentes et anciennes (valeurs vides avant les migrations de 2015 et 2017).
    orders = generator.recent_history(500, TODAY) + generator.old_history(
        500, TODAY, first_sequence=501
    )

    ours = eligibility_probability(pd.DataFrame(orders))
    theirs = [erp_generator.express_probability(order) for order in orders]

    assert list(ours) == pytest.approx(theirs, abs=1e-12)


def test_erp_orders_carry_a_deterministic_label():
    generator = erp_generator.OrderGenerator()
    first = generator.build(42, date(2024, 3, 1))
    again = generator.build(42, date(2024, 3, 1))

    assert first["express_eligible"] in (0, 1)
    assert first == again


def test_erp_labels_follow_the_rule():
    """Sur un grand échantillon, le taux observé suit la probabilité moyenne de la règle."""
    orders = erp_generator.OrderGenerator().recent_history(5000, TODAY)
    expected = eligibility_probability(pd.DataFrame(orders)).mean()
    observed = sum(order["express_eligible"] for order in orders) / len(orders)

    assert observed == pytest.approx(expected, abs=0.02)
    assert 0 < observed < 1


def test_rule_matches_the_notebook_on_a_hand_computed_order():
    order = pd.DataFrame([{
        "hour": 20, "day_of_week": 5, "weekend": 1, "distance_km": 10.0,
        "order_value_eur": 50.0, "weight_kg": 4.0, "stock_available": 1,
        "preparation_time_min": 20.0, "carrier_capacity": 25.0,
        "weather": "rain", "delivery_zone": "suburb", "customer_type": "business",
    }])
    score = (2.5 - 0.18 * 10 - 0.035 * 20 - 0.035 * 4 - 0.20 - 0.10 + 1.8
             + 1.3 * 25 / 50 + 0.15 - 0.40 - 0.08 * 2)

    assert eligibility_probability(order)[0] == pytest.approx(1 / (1 + math.exp(-score)))
