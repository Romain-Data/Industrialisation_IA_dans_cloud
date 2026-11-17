"""Contrôles de qualité des données : colonnes, bornes et catégories autorisées."""

from src.domain.features import CATEGORY_VALUES, FEATURE_COLUMNS


def _check_value_ranges(df):
    """Contrôles de bornes communs à l'entraînement et à la prédiction."""
    if not df["hour"].between(0, 23).all():
        raise ValueError("Certaines heures sont invalides.")

    if not df["distance_km"].ge(0).all():
        raise ValueError("La distance ne peut pas être négative.")

    if not df["weight_kg"].ge(0).all():
        raise ValueError("Le poids ne peut pas être négatif.")

    if not df["preparation_time_min"].ge(0).all():
        raise ValueError("Le temps de préparation ne peut pas être négatif.")

    if not df["carrier_capacity"].ge(0).all():
        raise ValueError("La capacité du transporteur ne peut pas être négative.")

    if not df["stock_available"].isin([0, 1]).all():
        raise ValueError(
            "La variable stock_available doit contenir uniquement 0 ou 1."
        )

    # Les valeurs manquantes sont admises ici : elles sont imputées par le modèle.
    for column, allowed in CATEGORY_VALUES.items():
        unknown = set(df[column].dropna()) - set(allowed)
        if unknown:
            raise ValueError(
                f"Valeurs inconnues pour {column} : {sorted(unknown)} "
                f"(attendu : {list(allowed)})."
            )


def validate_dataset(df):
    """
    Contrôles de qualité élémentaires sur les données d'entrée.
    Cette fonction pourra ensuite être déplacée dans un module data_quality.py.
    """
    required_columns = {
        "order_id",
        "order_date",
        "hour",
        "day_of_week",
        "weekend",
        "distance_km",
        "order_value_eur",
        "weight_kg",
        "stock_available",
        "preparation_time_min",
        "carrier_capacity",
        "weather",
        "delivery_zone",
        "customer_type",
        "express_eligible",
    }

    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise ValueError(
            f"Colonnes obligatoires absentes : {sorted(missing_columns)}"
        )

    if df["order_id"].duplicated().any():
        raise ValueError("Des identifiants de commande sont dupliqués.")

    if df["express_eligible"].isna().any():
        raise ValueError("La variable cible contient des valeurs manquantes.")

    _check_value_ranges(df)

    return True


def validate_order(df):
    """
    Contrôles sur une ou plusieurs commandes à prédire.
    Contrairement à validate_dataset, la cible et les identifiants
    ne sont pas requis.
    """
    missing_features = set(FEATURE_COLUMNS) - set(df.columns)

    if missing_features:
        raise ValueError(
            f"Variables manquantes : {sorted(missing_features)}"
        )

    _check_value_ranges(df)

    return True
