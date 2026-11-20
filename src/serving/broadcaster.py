"""Relais des événements de prédiction vers les navigateurs, en Server-Sent Events (ADR-0013).

Les événements arrivent dans un thread (écoute RabbitMQ, ou worker en mémoire) ; chaque
navigateur connecté a sa file asyncio, alimentée sans bloquer depuis ce thread. Un
navigateur trop lent perd les événements en trop plutôt que de ralentir les autres.
"""

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

KEEPALIVE_SECONDS = 15.0
SUBSCRIBER_BUFFER = 100
# Délai de reconnexion conseillé au navigateur (EventSource) après une coupure.
RETRY_MILLISECONDS = 3000


class SseBroadcaster:
    """Diffuse chaque événement reçu à tous les abonnés (un par navigateur connecté)."""

    def __init__(self) -> None:
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue:
        """Nouvel abonné, dans la boucle asyncio courante."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_BUFFER)
        with self._lock:
            self._subscribers.add((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Retire un abonné (navigateur déconnecté)."""
        with self._lock:
            self._subscribers = {item for item in self._subscribers if item[1] is not queue}

    @property
    def subscriber_count(self) -> int:
        """Nombre de navigateurs connectés."""
        with self._lock:
            return len(self._subscribers)

    def dispatch(self, event: dict[str, Any]) -> None:
        """Transmet un événement à tous les abonnés ; appelable depuis n'importe quel thread."""
        with self._lock:
            subscribers = list(self._subscribers)
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(_put_or_drop, queue, event)
            except RuntimeError:  # boucle fermée : l'abonné sera retiré à sa déconnexion
                pass


def _put_or_drop(queue: asyncio.Queue, event: dict[str, Any]) -> None:
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        logger.warning("Navigateur trop lent : événement de prédiction abandonné.")


def format_sse(event: dict[str, Any]) -> str:
    """Message SSE : identifiant, type et données JSON sur une ligne."""
    return (
        f"id: {event['event_id']}\n"
        f"event: {event['event_type']}\n"
        f"data: {json.dumps(event, default=str)}\n\n"
    )


async def event_stream(
    broadcaster: SseBroadcaster,
    is_disconnected: Callable[[], Awaitable[bool]],
    keepalive_seconds: float = KEEPALIVE_SECONDS,
) -> AsyncIterator[str]:
    """Flux SSE d'un navigateur : événements, et commentaire de maintien toutes les 15 s."""
    queue = broadcaster.subscribe()
    try:
        yield f"retry: {RETRY_MILLISECONDS}\n\n"
        while not await is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=keepalive_seconds)
            except TimeoutError:
                # Commentaire SSE : maintient la connexion ouverte à travers le proxy.
                yield ": keepalive\n\n"
                continue
            yield format_sse(event)
    finally:
        broadcaster.unsubscribe(queue)
