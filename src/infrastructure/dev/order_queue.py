import queue

from src.abstraction.order_queue import OrderQueue


class InMemoryOrderQueue(OrderQueue):
    """File en mémoire du processus, pour le dev. Perdue au redémarrage."""

    def __init__(self):
        self._queue = queue.Queue()

    def publish(self, event):
        self._queue.put(event)

    def consume(self, timeout=1.0):
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
