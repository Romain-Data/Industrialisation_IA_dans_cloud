"""API FastAPI : commandes, prédictions, résultat réel, model card, sondes de santé, et
flux temps réel du logisticien (ADR-0013)."""

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from src.abstraction.order_queue import OrderQueue
from src.abstraction.order_repository import OrderRepository
from src.abstraction.order_store import DuplicateOrderError, OrderStore
from src.abstraction.prediction_events import PredictionEvents
from src.config import (
    DATABASE_URL,
    ERP_MONGO_COLLECTION,
    ERP_MONGO_DATABASE,
    ERP_MONGO_URI,
    ERP_STREAM_POLL_SECONDS,
    MODEL_RELOAD_INTERVAL_SECONDS,
    MODEL_VERSION,
    PROJECT_NAME,
    RABBITMQ_ORDERS_QUEUE,
    RABBITMQ_PREDICTIONS_EXCHANGE,
    RABBITMQ_URL,
)
from src.domain.classifier import Classifier
from src.infrastructure.dev.order_queue import InMemoryOrderQueue
from src.infrastructure.dev.prediction_events import InMemoryPredictionEvents
from src.infrastructure.mongo_order_repository import MongoOrderRepository
from src.infrastructure.order_store import SqlAlchemyOrderStore
from src.infrastructure.rabbitmq import RabbitMQOrderQueue, RabbitMQPredictionEvents
from src.serving.broadcaster import SseBroadcaster, event_stream
from src.serving.dependencies import (
    get_broadcaster,
    get_erp_stream_connector,
    get_model,
    get_model_card,
    get_order_queue,
    get_order_store,
    get_worker,
)
from src.serving.erp_stream import ErpStream, ErpUnavailableError
from src.serving.events import order_created_event
from src.serving.model_loader import champion_version, load_model, load_model_card
from src.serving.model_reloader import ModelReloader
from src.serving.schemas import (
    ErpStreamStatus,
    ErpStreamUpdate,
    Error,
    HealthStatus,
    ModelCard,
    OrderAccepted,
    OrderFeatures,
    OrderOutcome,
    OrderOutcomeRecorded,
    Prediction,
    PredictionList,
    ReadinessStatus,
)
from src.serving.service import compute_prediction
from src.serving.worker import OrderWorker

router = APIRouter()
STATIC_DIR = Path(__file__).parent / "static"


def error_response(
    status_code: int, error: str, message: str, details: list[str] | None = None
) -> JSONResponse:
    """Réponse d'erreur au format du contrat (code stable, message, détails)."""
    body = Error(error=error, message=message, details=details)
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


def new_order_id() -> str:
    """Identifiant de commande généré quand le client n'en fournit pas."""
    return f"CMD-{uuid.uuid4().hex[:8]}"


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Erreur de validation Pydantic -> 422 au format du contrat, champ par champ."""
    details = [
        f"{'.'.join(str(part) for part in err['loc'][1:])}: {err['msg']}"
        for err in exc.errors()
    ]
    return error_response(422, "validation_error", "Commande invalide.", details)


async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Erreur inattendue -> 500 avec un message générique, sans détail interne (ADR-0005)."""
    return error_response(500, "internal_error", "Erreur interne.")


@router.get("/health", tags=["health"], operation_id="getHealth", response_model=HealthStatus)
def get_health() -> HealthStatus:
    """Sonde de vivacité : le service répond."""
    return HealthStatus(status="ok", service=PROJECT_NAME, version=MODEL_VERSION)


@router.get(
    "/health/ready",
    tags=["health"],
    operation_id="getReadiness",
    response_model=ReadinessStatus,
    responses={503: {"model": ReadinessStatus}},
)
def get_readiness(
    model: Classifier | None = Depends(get_model),
    order_store: OrderStore = Depends(get_order_store),
    order_queue: OrderQueue = Depends(get_order_queue),
    worker: OrderWorker = Depends(get_worker),
) -> JSONResponse:
    """Sonde de disponibilité : modèle, base, schéma, file et worker (503 si un contrôle échoue)."""
    checks = {
        "model": "loaded" if model is not None else "not_loaded",
        "order_store": "reachable" if order_store.ping() else "unreachable",
        "schema": "up_to_date" if order_store.schema_is_current() else "outdated",
        "queue": "reachable" if order_queue.ping() else "unreachable",
        "worker": "running" if worker.is_alive() else "stopped",
    }
    ready = checks == {
        "model": "loaded",
        "order_store": "reachable",
        "schema": "up_to_date",
        "queue": "reachable",
        "worker": "running",
    }

    body = ReadinessStatus(
        status="ready" if ready else "not_ready",
        checks=checks,
        version=MODEL_VERSION,
    )
    return JSONResponse(
        status_code=200 if ready else 503,
        content=body.model_dump(exclude_none=True),
    )


@router.post(
    "/v1/orders",
    tags=["orders"],
    operation_id="createOrder",
    summary="Enregistrer une commande à prédire",
    status_code=202,
    response_model=OrderAccepted,
    responses={422: {"model": Error}, 500: {"model": Error}},
)
def create_order(
    order: OrderFeatures,
    order_store: OrderStore = Depends(get_order_store),
    order_queue: OrderQueue = Depends(get_order_queue),
) -> OrderAccepted | JSONResponse:
    """Enregistre la commande, publie l'événement pour le worker, répond 202 sans attendre."""
    order_data = order.model_dump()
    order_data["order_id"] = order.order_id or new_order_id()

    try:
        accept_order(order_data, order_store, order_queue)
    except DuplicateOrderError:
        return error_response(
            422,
            "duplicate_order",
            "Une commande avec cet identifiant existe déjà.",
            [f"order_id: {order_data['order_id']}"],
        )

    return OrderAccepted(order_id=order_data["order_id"], status="accepted")


def accept_order(
    order_data: dict[str, Any], order_store: OrderStore, order_queue: OrderQueue
) -> None:
    """Enregistre la commande (source de vérité), puis publie son événement pour le worker.

    Chemin commun aux commandes reçues et aux commandes de démonstration (ADR-0013).
    """
    order_store.save(order_data)
    order_queue.publish(order_created_event(order_data))


@router.get(
    "/v1/orders/{order_id}",
    tags=["orders"],
    operation_id="getOrder",
    summary="Relire une commande collectée",
    response_model=OrderFeatures,
    responses={404: {"model": Error}},
)
def get_order(
    order_id: str, order_store: OrderStore = Depends(get_order_store)
) -> dict[str, Any] | JSONResponse:
    """Relit une commande enregistrée (404 si inconnue)."""
    order = order_store.get(order_id)

    if order is None:
        return error_response(404, "order_not_found", f"Commande inconnue : {order_id}")

    return order


@router.get(
    "/v1/model",
    tags=["model"],
    operation_id="getModelCard",
    summary="Métadonnées et métriques du modèle en service",
    response_model=ModelCard,
    responses={503: {"model": Error}},
)
def get_model_card_route(
    model_card: dict[str, Any] | None = Depends(get_model_card),
) -> dict[str, Any] | JSONResponse:
    """Model card du champion en service (503 si aucun modèle n'est chargé)."""
    if model_card is None:
        return error_response(503, "model_unavailable", "Aucun modèle en service.")

    return model_card


@router.put(
    "/v1/orders/{order_id}/outcome",
    tags=["orders"],
    operation_id="recordOrderOutcome",
    summary="Enregistrer le résultat réel d'une commande",
    response_model=OrderOutcomeRecorded,
    responses={404: {"model": Error}, 422: {"model": Error}},
)
def record_order_outcome(
    order_id: str, outcome: OrderOutcome, order_store: OrderStore = Depends(get_order_store)
) -> dict[str, Any] | JSONResponse:
    """Enregistre le résultat réel d'une commande, cible des entraînements (404 si inconnue)."""
    recorded = order_store.record_outcome(order_id, outcome.express_eligible)

    if recorded is None:
        return error_response(404, "order_not_found", f"Commande inconnue : {order_id}")

    return recorded


@router.post(
    "/v1/predictions",
    tags=["predictions"],
    operation_id="createPrediction",
    summary="Prédire l'éligibilité express d'une commande",
    response_model=Prediction,
    responses={422: {"model": Error}, 503: {"model": Error}},
)
def create_prediction(
    order: OrderFeatures, model: Classifier | None = Depends(get_model)
) -> dict[str, Any] | JSONResponse:
    """Prédiction immédiate, sans enregistrer la commande (503 sans modèle, 422 si invalide)."""
    if model is None:
        return error_response(503, "model_unavailable", "Le modèle n'est pas chargé.")

    try:
        return compute_prediction(
            order.order_id or new_order_id(),
            order.model_dump(exclude={"order_id"}),
            model,
        )
    except ValueError as error:
        return error_response(422, "validation_error", str(error))


@router.get(
    "/v1/predictions/{order_id}",
    tags=["predictions"],
    operation_id="getPrediction",
    summary="Relire une prédiction déjà calculée",
    response_model=Prediction,
    responses={404: {"model": Error}},
)
def get_prediction(
    order_id: str, order_store: OrderStore = Depends(get_order_store)
) -> dict[str, Any] | JSONResponse:
    """Relit la prédiction calculée par le worker (404 si elle n'existe pas encore)."""
    prediction = order_store.get_prediction(order_id)

    if prediction is None:
        return error_response(
            404, "prediction_not_found", f"Aucune prédiction pour : {order_id}"
        )

    return prediction


@router.get(
    "/v1/predictions",
    tags=["predictions"],
    operation_id="listPredictions",
    summary="Dernières prédictions calculées",
    response_model=PredictionList,
    responses={422: {"model": Error}},
)
def list_predictions(
    limit: int = Query(default=20, ge=1, le=100, description="Nombre de prédictions"),
    order_store: OrderStore = Depends(get_order_store),
) -> PredictionList:
    """Dernières prédictions, de la plus récente à la plus ancienne (historique de la page)."""
    predictions = [Prediction(**item) for item in order_store.recent_predictions(limit)]
    return PredictionList(predictions=predictions, count=len(predictions))


@router.get(
    "/v1/events/predictions",
    tags=["predictions"],
    operation_id="streamPredictions",
    summary="Flux temps réel des prédictions (Server-Sent Events)",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Flux text/event-stream d'événements prediction.created",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def stream_predictions(
    request: Request, broadcaster: SseBroadcaster = Depends(get_broadcaster)
) -> StreamingResponse:
    """Chaque prédiction enregistrée est poussée au navigateur dès qu'elle est calculée."""
    return StreamingResponse(
        event_stream(broadcaster, request.is_disconnected),
        media_type="text/event-stream",
        # Pas de cache ni de mise en tampon par un proxy : les événements partent tout de suite.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/v1/erp-stream",
    tags=["erp"],
    operation_id="getErpStream",
    summary="État du flux temps réel des commandes de l'ERP",
    response_model=ErpStreamStatus,
)
def get_erp_stream(erp_stream: ErpStream = Depends(get_erp_stream_connector)) -> dict[str, Any]:
    """Le flux est-il actif, depuis quand, et combien de commandes a-t-il apportées ?"""
    return erp_stream.status()


@router.put(
    "/v1/erp-stream",
    tags=["erp"],
    operation_id="updateErpStream",
    summary="Activer ou couper le flux temps réel de l'ERP",
    response_model=ErpStreamStatus,
    responses={422: {"model": Error}, 503: {"model": Error}},
)
def update_erp_stream(
    update: ErpStreamUpdate, erp_stream: ErpStream = Depends(get_erp_stream_connector)
) -> dict[str, Any] | JSONResponse:
    """Le logisticien prend son poste (active) ou le quitte (coupe) ; 503 si l'ERP ne répond pas."""
    if not update.active:
        return erp_stream.stop()
    try:
        return erp_stream.start()
    except ErpUnavailableError:
        return error_response(503, "erp_unavailable", "L'ERP ne répond pas : flux non activé.")


@router.get("/logisticien", include_in_schema=False)
def logistician_page() -> HTMLResponse:
    """Page du logisticien : prédictions en direct et notification des commandes express."""
    html = (STATIC_DIR / "logisticien.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


def _mongo_erp_source() -> OrderRepository:
    """Base analytique de l'ERP (MongoDB, lecture seule), lue par le flux temps réel."""
    return MongoOrderRepository(
        ERP_MONGO_URI, database=ERP_MONGO_DATABASE, collection=ERP_MONGO_COLLECTION, timeout_ms=3000
    )


def create_app(
    database_url: str = DATABASE_URL,
    model_loader: Callable[[], Classifier] = load_model,
    order_queue: OrderQueue | None = None,
    model_card_loader: Callable[[], dict[str, Any] | None] = load_model_card,
    version_reader: Callable[[], str | None] = champion_version,
    reload_interval: float = MODEL_RELOAD_INTERVAL_SECONDS,
    prediction_events: PredictionEvents | None = None,
    rabbitmq_url: str | None = RABBITMQ_URL,
    erp_source_factory: Callable[[], OrderRepository] | None = None,
    erp_poll_seconds: float = ERP_STREAM_POLL_SECONDS,
) -> FastAPI:
    """Construit l'application ; les dépendances sont injectables pour les tests."""

    def load_champion() -> None:
        """Charge le modèle champion et sa model card (qui décrit toujours la version servie)."""
        try:
            model = model_loader()
        except FileNotFoundError:
            model = None
        app.state.model_card = model_card_loader() if model is not None else None
        app.state.model = model

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        version = version_reader()
        load_champion()
        # Recharge le champion quand l'orchestrateur en promeut un nouveau (ADR-0009).
        app.state.reloader = ModelReloader(version_reader, load_champion, reload_interval)
        app.state.reloader.start(version if app.state.model is not None else None)

        app.state.order_store = SqlAlchemyOrderStore(database_url)
        # RabbitMQ si RABBITMQ_URL est défini (préprod, prod), sinon en mémoire (ADR-0013).
        app.state.order_queue = order_queue or (
            RabbitMQOrderQueue(rabbitmq_url, RABBITMQ_ORDERS_QUEUE)
            if rabbitmq_url
            else InMemoryOrderQueue()
        )
        app.state.prediction_events = prediction_events or (
            RabbitMQPredictionEvents(rabbitmq_url, RABBITMQ_PREDICTIONS_EXCHANGE)
            if rabbitmq_url
            else InMemoryPredictionEvents()
        )
        # Les prédictions diffusées sont relayées aux navigateurs connectés (SSE).
        app.state.broadcaster = SseBroadcaster()
        app.state.prediction_events.listen(app.state.broadcaster.dispatch)
        app.state.worker = OrderWorker(
            app.state.order_queue,
            app.state.order_store,
            lambda: app.state.model,
            app.state.prediction_events,
        )
        app.state.worker.start()
        # Flux ERP du logisticien : inactif au démarrage, activé depuis la page (ADR-0013).
        app.state.erp_stream = ErpStream(
            erp_source_factory or _mongo_erp_source,
            app.state.order_store,
            app.state.order_queue,
            poll_seconds=erp_poll_seconds,
        )

        yield

        app.state.erp_stream.stop()
        app.state.reloader.stop()
        app.state.worker.stop()
        app.state.prediction_events.close()
        app.state.order_queue.close()

    app = FastAPI(
        title=f"{PROJECT_NAME} API",
        version=MODEL_VERSION,
        description="API de prédiction d'éligibilité à la livraison express.",
        lifespan=lifespan,
    )
    app.include_router(router)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, internal_error_handler)

    return app


app = create_app()
