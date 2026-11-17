"""Nettoyage et validation d'une commande importée d'un système source (ETL, ADR-0007).

Le cours le rappelle : ne pas faire confiance à la qualité des données. Chaque commande
de l'ERP est nettoyée (corrections sûres et sans perte), puis validée ; une commande
invalide est rejetée avec ses motifs, jamais corrigée par supposition.
"""

from dataclasses import fields, replace

from src.domain.entities import OrderEntity
from src.domain.features import CATEGORY_VALUES

NON_NEGATIVE = (
    "distance_km",
    "order_value_eur",
    "weight_kg",
    "preparation_time_min",
    "carrier_capacity",
)
BINARY = ("weekend", "stock_available")
REQUIRED = tuple(f.name for f in fields(OrderEntity) if f.name != "order_date")


def clean_order(order: OrderEntity) -> OrderEntity:
    """Corrige ce qui peut l'être sans rien inventer.

    - week-end manquant (données d'avant la migration de 2015) : déduit du jour ;
    - catégories : espaces superflus retirés et minuscules.
    """
    changes = {}
    if order.weekend is None and isinstance(order.day_of_week, int):
        changes["weekend"] = int(order.day_of_week >= 5)
    for column in CATEGORY_VALUES:
        value = getattr(order, column)
        if isinstance(value, str) and value != value.strip().lower():
            changes[column] = value.strip().lower()
    return replace(order, **changes) if changes else order


def order_errors(order: OrderEntity) -> list[str]:
    """Motifs de rejet d'une commande (liste vide si elle est valide)."""
    errors = [f"{name} manquant" for name in REQUIRED if getattr(order, name) is None]
    if errors:
        return errors

    numeric = ("hour", "day_of_week", *BINARY, *NON_NEGATIVE)
    errors = [
        f"{name} non numérique"
        for name in numeric
        if isinstance(getattr(order, name), bool) or not isinstance(getattr(order, name), int | float)
    ]
    if errors:
        return errors

    if not 0 <= order.hour <= 23:
        errors.append(f"hour hors bornes ({order.hour})")
    if not 0 <= order.day_of_week <= 6:
        errors.append(f"day_of_week hors bornes ({order.day_of_week})")
    errors += [f"{name} doit valoir 0 ou 1" for name in BINARY if getattr(order, name) not in (0, 1)]
    errors += [f"{name} négatif" for name in NON_NEGATIVE if getattr(order, name) < 0]
    errors += [
        f"{column} inconnu ({getattr(order, column)!r})"
        for column, allowed in CATEGORY_VALUES.items()
        if getattr(order, column) not in allowed
    ]
    return errors
