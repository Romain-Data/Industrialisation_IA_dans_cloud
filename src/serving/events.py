"""Construction des événements échangés par la file des commandes (contrat `OrderEvent`)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from src.domain.features import FEATURE_COLUMNS
from src.serving.schemas import OrderEvent, OrderFeatures


def order_created_event(order_data: dict[str, Any]) -> dict[str, Any]:
    """Événement `order.created` d'une commande enregistrée, prêt à publier (JSON).

    Seuls les champs du contrat `OrderFeatures` sont repris (pas la date ni la cible).
    """
    features = {name: order_data.get(name) for name in ("order_id", *FEATURE_COLUMNS)}
    event = OrderEvent(
        event_id=str(uuid.uuid4()),
        event_type="order.created",
        occurred_at=datetime.now(UTC),
        order=OrderFeatures(**features),
    )
    return event.model_dump(mode="json")
