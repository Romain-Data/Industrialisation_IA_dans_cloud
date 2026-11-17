"""Dépendances FastAPI : accès aux objets créés au démarrage de l'application (app.state)."""

from fastapi import Request


def get_model(request: Request):
    """Modèle champion chargé au démarrage (None s'il n'y en a pas)."""
    return request.app.state.model


def get_model_card(request: Request):
    """Model card du champion chargé (None s'il n'y en a pas)."""
    return request.app.state.model_card


def get_order_store(request: Request):
    """Stockage des commandes et des prédictions."""
    return request.app.state.order_store


def get_order_queue(request: Request):
    """File d'attente des commandes à prédire."""
    return request.app.state.order_queue


def get_worker(request: Request):
    """Worker qui calcule les prédictions en arrière-plan."""
    return request.app.state.worker
