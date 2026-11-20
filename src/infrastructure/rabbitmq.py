"""File des commandes et diffusion des prédictions sur RabbitMQ (ADR-0013).

- `RabbitMQOrderQueue` : file durable `orders`, messages persistants ; un événement publié
  avant un redémarrage de l'API est traité après.
- `RabbitMQPredictionEvents` : échange *fanout* `predictions` ; chaque instance de l'API
  l'écoute par une file exclusive, supprimée à la déconnexion.

`pika.BlockingConnection` n'est pas sûre entre threads : la publication passe par une
connexion protégée par un verrou (`_Publisher`), et chaque consommateur ouvre sa propre
connexion dans le thread qui consomme. Une connexion perdue est rouverte au prochain appel.
"""

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.exceptions import AMQPError

from src.abstraction.order_queue import OrderQueue
from src.abstraction.prediction_events import PredictionEvents, PredictionListener

logger = logging.getLogger(__name__)

PERSISTENT = pika.DeliveryMode.Persistent
CONTENT_TYPE = "application/json"


def _connect(url: str) -> pika.BlockingConnection:
    """Ouvre une connexion (l'URL amqp:// porte l'hôte, l'utilisateur et le mot de passe)."""
    parameters = pika.URLParameters(url)
    parameters.connection_attempts = 3
    parameters.retry_delay = 2
    return pika.BlockingConnection(parameters)


class _Publisher:
    """Connexion de publication partagée entre threads, protégée par un verrou."""

    def __init__(self, url: str, declare: Callable[[BlockingChannel], None]) -> None:
        self._url = url
        self._declare = declare
        self._lock = threading.Lock()
        self._connection: pika.BlockingConnection | None = None
        self._channel: BlockingChannel | None = None

    def _ensure_channel(self) -> BlockingChannel:
        if self._channel is None or self._channel.is_closed:
            self._close_connection()
            self._connection = _connect(self._url)
            self._channel = self._connection.channel()
            self._declare(self._channel)
        return self._channel

    def publish(self, exchange: str, routing_key: str, body: bytes, persistent: bool) -> None:
        """Publie un message ; une connexion perdue est rouverte une fois."""
        properties = pika.BasicProperties(
            content_type=CONTENT_TYPE, delivery_mode=PERSISTENT if persistent else None
        )
        with self._lock:
            for attempt in (1, 2):
                try:
                    self._ensure_channel().basic_publish(exchange, routing_key, body, properties)
                    return
                except AMQPError:
                    self._channel = None
                    if attempt == 2:
                        raise
                    logger.warning("Connexion RabbitMQ perdue : reconnexion.")

    def ping(self) -> bool:
        """Vrai si la connexion de publication est (ou peut être) ouverte."""
        with self._lock:
            try:
                self._ensure_channel()
                if self._connection is not None:
                    self._connection.process_data_events(time_limit=0)
            except AMQPError:
                self._channel = None
                return False
        return True

    def _close_connection(self) -> None:
        if self._connection is not None and self._connection.is_open:
            try:
                self._connection.close()
            except AMQPError:
                pass
        self._connection = None

    def close(self) -> None:
        """Ferme la connexion de publication."""
        with self._lock:
            self._close_connection()
            self._channel = None


class RabbitMQOrderQueue(OrderQueue):
    """File durable des événements `order.created`."""

    def __init__(self, url: str, queue: str = "orders") -> None:
        self._url = url
        self._queue = queue
        self._publisher = _Publisher(url, self._declare)
        # Connexion de consommation : propre au thread du worker.
        self._consumer = threading.local()

    def _declare(self, channel: BlockingChannel) -> None:
        channel.queue_declare(queue=self._queue, durable=True)

    def publish(self, event: dict[str, Any]) -> None:
        self._publisher.publish("", self._queue, json.dumps(event).encode(), persistent=True)

    def _consumer_channel(self) -> BlockingChannel:
        channel = getattr(self._consumer, "channel", None)
        if channel is None or channel.is_closed:
            connection = _connect(self._url)
            channel = connection.channel()
            self._declare(channel)
            self._consumer.connection = connection
            self._consumer.channel = channel
        return channel

    def consume(self, timeout: float = 1.0) -> dict[str, Any] | None:
        """Prochain événement, acquitté à la réception (ADR-0013) ; None après `timeout` s.

        `basic_get` ne retire qu'un message à la fois : les autres restent dans la file
        durable (et survivent à un arrêt de l'API), au lieu d'être poussés dans un tampon.
        """
        try:
            channel = self._consumer_channel()
            _method, _properties, body = channel.basic_get(self._queue, auto_ack=True)
            if body is not None:
                return json.loads(body)
            if timeout > 0:
                self._consumer.connection.sleep(timeout)  # traite aussi les heartbeats
        except AMQPError:
            logger.warning("Consommation RabbitMQ interrompue : reconnexion au prochain appel.")
            self._consumer.channel = None
        return None

    def ping(self) -> bool:
        return self._publisher.ping()

    def close(self) -> None:
        self._publisher.close()
        connection = getattr(self._consumer, "connection", None)
        if connection is not None and connection.is_open:
            try:
                connection.close()
            except AMQPError:
                pass


class RabbitMQPredictionEvents(PredictionEvents):
    """Diffusion des prédictions par un échange *fanout*."""

    def __init__(self, url: str, exchange: str = "predictions") -> None:
        self._url = url
        self._exchange = exchange
        self._publisher = _Publisher(url, self._declare)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def _declare(self, channel: BlockingChannel) -> None:
        channel.exchange_declare(exchange=self._exchange, exchange_type="fanout", durable=True)

    def publish(self, event: dict[str, Any]) -> None:
        self._publisher.publish(self._exchange, "", json.dumps(event).encode(), persistent=False)

    def listen(self, listener: PredictionListener) -> None:
        thread = threading.Thread(
            target=self._listen_forever, args=(listener,), name="prediction-events", daemon=True
        )
        self._threads.append(thread)
        thread.start()

    def _listen_forever(self, listener: PredictionListener) -> None:
        """Écoute l'échange par une file exclusive ; se reconnecte après une coupure."""
        while not self._stop.is_set():
            try:
                connection = _connect(self._url)
                try:
                    channel = connection.channel()
                    self._declare(channel)
                    queue = channel.queue_declare(queue="", exclusive=True).method.queue
                    channel.queue_bind(queue=queue, exchange=self._exchange)
                    for _method, _properties, body in channel.consume(
                        queue, auto_ack=True, inactivity_timeout=1
                    ):
                        if self._stop.is_set():
                            break
                        if body is not None:
                            self._deliver(listener, body)
                finally:
                    if connection.is_open:
                        connection.close()
            except AMQPError:
                logger.warning("Écoute des prédictions interrompue : nouvelle tentative dans 5 s.")
                self._stop.wait(5)

    @staticmethod
    def _deliver(listener: PredictionListener, body: bytes) -> None:
        try:
            listener(json.loads(body))
        except Exception:  # un événement en erreur ne coupe pas l'écoute
            logger.exception("Événement de prédiction non relayé.")

    def ping(self) -> bool:
        return self._publisher.ping()

    def close(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=3)
        self._publisher.close()
