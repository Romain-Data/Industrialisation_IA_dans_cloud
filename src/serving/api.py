import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.abstraction.order_store import DuplicateOrderError
from src.config import DATABASE_URL, MODEL_VERSION, PROJECT_NAME
from src.infrastructure.dev.order_queue import InMemoryOrderQueue
from src.infrastructure.order_store import SqlAlchemyOrderStore
from src.serving.dependencies import (
    get_model,
    get_order_queue,
    get_order_store,
    get_worker,
)
from src.serving.model_loader import load_model
from src.serving.schemas import (
    Error,
    HealthStatus,
    OrderAccepted,
    OrderEvent,
    OrderFeatures,
    Prediction,
    ReadinessStatus,
)
from src.serving.service import compute_prediction
from src.serving.worker import OrderWorker

router = APIRouter()


def error_response(status_code, error, message, details=None):
    body = Error(error=error, message=message, details=details)
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


def new_order_id():
    return f"CMD-{uuid.uuid4().hex[:8]}"


async def validation_error_handler(request: Request, exc: RequestValidationError):
    details = [
        f"{'.'.join(str(part) for part in err['loc'][1:])}: {err['msg']}"
        for err in exc.errors()
    ]
    return error_response(422, "validation_error", "Commande invalide.", details)


async def internal_error_handler(request: Request, exc: Exception):
    return error_response(500, "internal_error", "Erreur interne.")


@router.get("/health", tags=["health"], operation_id="getHealth", response_model=HealthStatus)
def get_health():
    return HealthStatus(status="ok", service=PROJECT_NAME, version=MODEL_VERSION)


@router.get(
    "/health/ready",
    tags=["health"],
    operation_id="getReadiness",
    response_model=ReadinessStatus,
    responses={503: {"model": ReadinessStatus}},
)
def get_readiness(
    model=Depends(get_model),
    order_store=Depends(get_order_store),
    worker=Depends(get_worker),
):
    checks = {
        "model": "loaded" if model is not None else "not_loaded",
        "order_store": "reachable" if order_store.ping() else "unreachable",
        "schema": "up_to_date" if order_store.schema_is_current() else "outdated",
        "worker": "running" if worker.is_alive() else "stopped",
    }
    ready = checks == {
        "model": "loaded",
        "order_store": "reachable",
        "schema": "up_to_date",
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
    order_store=Depends(get_order_store),
    order_queue=Depends(get_order_queue),
):
    order_data = order.model_dump()
    order_data["order_id"] = order.order_id or new_order_id()

    try:
        order_store.save(order_data)
    except DuplicateOrderError:
        return error_response(
            422,
            "duplicate_order",
            "Une commande avec cet identifiant existe déjà.",
            [f"order_id: {order_data['order_id']}"],
        )

    event = OrderEvent(
        event_id=str(uuid.uuid4()),
        event_type="order.created",
        occurred_at=datetime.now(UTC),
        order=OrderFeatures(**order_data),
    )
    order_queue.publish(event.model_dump(mode="json"))

    return OrderAccepted(order_id=order_data["order_id"], status="accepted")


@router.get(
    "/v1/orders/{order_id}",
    tags=["orders"],
    operation_id="getOrder",
    summary="Relire une commande collectée",
    response_model=OrderFeatures,
    responses={404: {"model": Error}},
)
def get_order(order_id: str, order_store=Depends(get_order_store)):
    order = order_store.get(order_id)

    if order is None:
        return error_response(404, "order_not_found", f"Commande inconnue : {order_id}")

    return order


@router.post(
    "/v1/predictions",
    tags=["predictions"],
    operation_id="createPrediction",
    summary="Prédire l'éligibilité express d'une commande",
    response_model=Prediction,
    responses={422: {"model": Error}, 503: {"model": Error}},
)
def create_prediction(order: OrderFeatures, model=Depends(get_model)):
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
def get_prediction(order_id: str, order_store=Depends(get_order_store)):
    prediction = order_store.get_prediction(order_id)

    if prediction is None:
        return error_response(
            404, "prediction_not_found", f"Aucune prédiction pour : {order_id}"
        )

    return prediction


def create_app(database_url=DATABASE_URL, model_loader=load_model, order_queue=None):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            app.state.model = model_loader()
        except FileNotFoundError:
            app.state.model = None

        app.state.order_store = SqlAlchemyOrderStore(database_url)
        app.state.order_queue = order_queue or InMemoryOrderQueue()
        app.state.worker = OrderWorker(
            app.state.order_queue,
            app.state.order_store,
            lambda: app.state.model,
        )
        app.state.worker.start()

        yield

        app.state.worker.stop()

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
