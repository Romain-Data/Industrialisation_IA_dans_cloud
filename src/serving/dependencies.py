"""Dépendances FastAPI : accès aux objets créés au démarrage de l'application (app.state)."""

from typing import Any

from fastapi import Request

from src.abstraction.order_queue import OrderQueue
from src.abstraction.order_store import OrderStore
from src.domain.classifier import Classifier
from src.serving.broadcaster import SseBroadcaster
from src.serving.erp_stream import ErpStream
from src.serving.worker import OrderWorker


def get_model(request: Request) -> Classifier | None:
    """Modèle champion chargé au démarrage (None s'il n'y en a pas)."""
    return request.app.state.model


def get_model_card(request: Request) -> dict[str, Any] | None:
    """Model card du champion chargé (None s'il n'y en a pas)."""
    return request.app.state.model_card


def get_order_store(request: Request) -> OrderStore:
    """Stockage des commandes et des prédictions."""
    return request.app.state.order_store


def get_order_queue(request: Request) -> OrderQueue:
    """File d'attente des commandes à prédire."""
    return request.app.state.order_queue


def get_worker(request: Request) -> OrderWorker:
    """Worker qui calcule les prédictions en arrière-plan."""
    return request.app.state.worker


def get_broadcaster(request: Request) -> SseBroadcaster:
    """Relais des prédictions vers les navigateurs connectés (SSE)."""
    return request.app.state.broadcaster


def get_erp_stream_connector(request: Request) -> ErpStream:
    """Flux temps réel des commandes de l'ERP (activé par le logisticien)."""
    return request.app.state.erp_stream
