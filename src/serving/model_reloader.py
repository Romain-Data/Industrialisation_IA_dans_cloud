"""Rechargement du modèle champion sans redémarrer l'API (ADR-0009).

Après un entraînement lancé par l'orchestrateur, l'alias `champion` peut changer de
version. Plutôt que de redémarrer l'API (ADR-0004, qui demandait un accès à Coolify ou
au socket Docker), l'API lit la version du champion à intervalle régulier et recharge
le modèle et sa model card quand elle change. Si MLflow est injoignable, le modèle en
service est conservé.
"""

import logging
import threading

logger = logging.getLogger(__name__)


class ModelReloader:
    """Thread qui recharge le modèle quand la version du champion change."""

    def __init__(self, read_version, reload, interval_seconds):
        self._read_version = read_version
        self._reload = reload
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread = None
        self.current_version = None

    def check_once(self):
        """Recharge si le champion a changé. Retourne True s'il y a eu rechargement."""
        try:
            version = self._read_version()
        except Exception:  # noqa: BLE001 - registre injoignable : on garde le modèle servi
            logger.warning("Version du champion illisible : modèle en service conservé.")
            return False

        if version is None or version == self.current_version:
            return False

        self._reload()
        logger.info("Modèle rechargé : champion %s -> %s.", self.current_version, version)
        self.current_version = version
        return True

    def start(self, current_version):
        """Démarre la surveillance (désactivée si l'intervalle vaut 0)."""
        self.current_version = current_version
        if self._interval <= 0:
            return
        self._thread = threading.Thread(target=self._run, name="model-reloader", daemon=True)
        self._thread.start()

    def stop(self):
        """Arrête la surveillance."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self):
        while not self._stop.wait(self._interval):
            self.check_once()
