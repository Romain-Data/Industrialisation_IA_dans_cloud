from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.domain.features import (
    CUSTOMER_TYPE_VALUES,
    DELIVERY_ZONE_VALUES,
    WEATHER_VALUES,
)

# Vocabulaire de l'ERP (ADR-0007), défini une seule fois dans le domaine.
Weather = Literal[WEATHER_VALUES]
DeliveryZone = Literal[DELIVERY_ZONE_VALUES]
CustomerType = Literal[CUSTOMER_TYPE_VALUES]


class OrderFeatures(BaseModel):
    """Caractéristiques d'une commande (FEATURE_COLUMNS du notebook)."""

    model_config = ConfigDict(extra="forbid")

    order_id: str | None = Field(
        default=None,
        description="Identifiant métier de la commande. Généré par le serveur si absent.",
        examples=["CMD-000001"],
    )
    hour: int = Field(ge=0, le=23, examples=[14])
    day_of_week: int = Field(
        ge=0, le=6, description="0 = lundi ... 6 = dimanche", examples=[2]
    )
    weekend: Literal[0, 1] = Field(examples=[0])
    distance_km: float = Field(ge=0, examples=[3.5])
    order_value_eur: float = Field(ge=0, examples=[89.9])
    weight_kg: float = Field(ge=0, examples=[2.4])
    stock_available: Literal[0, 1] = Field(examples=[1])
    preparation_time_min: float = Field(ge=0, examples=[18])
    carrier_capacity: float = Field(
        ge=0, description="Capacité disponible du transporteur (unités de l'ERP)", examples=[34.5]
    )
    weather: Weather
    delivery_zone: DeliveryZone
    customer_type: CustomerType


class OrderEvent(BaseModel):
    """Événement publié dans la file à chaque commande enregistrée."""

    event_id: str
    event_type: Literal["order.created"]
    occurred_at: datetime
    order: OrderFeatures
    schema_version: int = 1


class OrderAccepted(BaseModel):
    order_id: str
    status: Literal["accepted"]


class OrderOutcome(BaseModel):
    """Résultat observé d'une commande (cible d'entraînement)."""

    model_config = ConfigDict(extra="forbid")

    express_eligible: bool = Field(
        description="La commande est-elle réellement partie en livraison express ?",
        examples=[True],
    )


class OrderOutcomeRecorded(BaseModel):
    order_id: str
    express_eligible: bool
    recorded_at: datetime


class Prediction(BaseModel):
    order_id: str
    express_eligible: bool
    decision: Literal["oui", "non"]
    probability: float = Field(ge=0, le=1)
    model_version: str
    predicted_at: datetime
    latency_ms: float | None = Field(
        default=None, description="Temps de calcul de la prédiction"
    )


class ModelCard(BaseModel):
    """Model card de la cellule 55 du notebook."""

    project: str
    model_version: str
    model_type: str
    task: str
    target: str
    threshold: float
    trained_at: datetime | None = None
    features: list[str]
    metrics: dict[str, float]
    limitations: list[str] | None = None


class HealthStatus(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadinessStatus(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, str]
    version: str | None = None


class Error(BaseModel):
    error: str = Field(description="Code d'erreur stable", examples=["validation_error"])
    message: str = Field(description="Message destiné à l'humain")
    details: list[str] | None = None
