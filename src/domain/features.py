"""Variables du modèle, cible et vocabulaire ERP (ADR-0007) : source unique du projet."""

TARGET_COLUMN = "express_eligible"

# Vocabulaire des données : celui de l'ERP, système de référence de l'entreprise (ADR-0007).
# Changer ce vocabulaire rend les modèles existants incompatibles : incrémenter alors
# DATA_SCHEMA_VERSION, enregistré avec chaque entraînement (voir training/registry.py).
DATA_SCHEMA_VERSION = "erp-v1"

WEATHER_VALUES = ("clear", "rain", "wind", "snow")
DELIVERY_ZONE_VALUES = ("centre", "suburb", "rural")
CUSTOMER_TYPE_VALUES = ("individual", "business")

CATEGORY_VALUES = {
    "weather": WEATHER_VALUES,
    "delivery_zone": DELIVERY_ZONE_VALUES,
    "customer_type": CUSTOMER_TYPE_VALUES,
}

# Les identifiants et les dates brutes ne sont pas utilisés directement
# par le modèle dans cette première version.
FEATURE_COLUMNS = [
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
]

NUMERIC_FEATURES = [
    "hour",
    "day_of_week",
    "weekend",
    "distance_km",
    "order_value_eur",
    "weight_kg",
    "stock_available",
    "preparation_time_min",
    "carrier_capacity",
]

CATEGORICAL_FEATURES = [
    "weather",
    "delivery_zone",
    "customer_type",
]
