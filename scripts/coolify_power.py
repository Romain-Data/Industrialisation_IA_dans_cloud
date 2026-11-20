"""Allume ou éteint le projet sur Coolify, dans l'ordre des dépendances.

Usage (variables COOLIFY_URL, ou COOLIFY_BASE_URL, et COOLIFY_TOKEN dans l'environnement) :
    python scripts/coolify_power.py status [preprod|prod|all]
    python scripts/coolify_power.py off    [preprod|prod|all] [--dry-run]
    python scripts/coolify_power.py on     [preprod|prod|all] [--dry-run]

Pourquoi : le VPS est partagé (ADR-0003, ADR-0011). Entre deux vérifications, on éteint le
projet pour rendre la mémoire aux autres projets ; les données restent dans les volumes.

Ordre :
- extinction : applications (orchestrateur, puis API, puis serveur Prefect), services
  (RabbitMQ...), puis bases de données ;
- allumage : l'inverse, en attendant que chaque base soit « running » avant de démarrer
  ce qui en dépend.

Pendant que la préprod est éteinte, la CI échoue à l'étape « Déploiement préprod ».

Bibliothèque standard uniquement. Code de sortie 0 si tout s'est bien passé, 1 sinon.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

PROJECT_UUID = os.getenv("COOLIFY_PROJECT_UUID", "fj6ugnxefggyjsqw7gcbetb0")
ENVIRONMENTS = {"preprod": "preprod", "prod": "production"}
# Clés de la réponse « environnement » de l'API Coolify qui listent des bases de données.
DATABASE_KEYS = ("postgresqls", "mongodbs", "mysqls", "mariadbs", "redis", "keydbs", "dragonflies", "clickhouses")
WAIT_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class Resource:
    """Ressource Coolify à allumer ou éteindre."""

    kind: str  # "applications", "services" ou "databases" (segment de l'URL de l'API)
    uuid: str
    name: str
    status: str

    @property
    def is_running(self) -> bool:
        """Vrai si Coolify déclare la ressource en marche (même partiellement)."""
        return self.status.startswith("running")


def api(method: str, path: str) -> dict[str, Any]:
    """Appel de l'API Coolify (les réponses peuvent contenir des caractères de contrôle)."""
    base = (os.getenv("COOLIFY_URL") or os.environ["COOLIFY_BASE_URL"]).rstrip("/")
    request = urllib.request.Request(
        f"{base}/api/v1{path}",
        method=method,
        headers={"Authorization": f"Bearer {os.environ['COOLIFY_TOKEN']}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    return json.loads(raw, strict=False) if raw else {}


def app_rank(name: str) -> int:
    """Ordre d'allumage des applications : serveur Prefect, puis API, puis orchestrateur."""
    lowered = name.lower()
    if "prefect" in lowered:
        return 0
    if "orchestrator" in lowered:
        return 2
    return 1


def resources(environment: str) -> list[Resource]:
    """Ressources d'un environnement, dans l'ordre d'ALLUMAGE."""
    env = api("GET", f"/projects/{PROJECT_UUID}/{ENVIRONMENTS[environment]}")
    databases = [
        Resource("databases", item["uuid"], item["name"], item.get("status", ""))
        for key in DATABASE_KEYS
        for item in env.get(key) or []
    ]
    services = [
        Resource("services", item["uuid"], item["name"], item.get("status", ""))
        for item in env.get("services") or []
    ]
    applications = sorted(
        (
            Resource("applications", item["uuid"], item["name"], item.get("status", ""))
            for item in env.get("applications") or []
        ),
        key=lambda resource: app_rank(resource.name),
    )
    return databases + services + applications


def current_status(resource: Resource) -> str:
    """État actuel d'une ressource, relu dans l'API."""
    return api("GET", f"/{resource.kind}/{resource.uuid}").get("status", "")


def wait_running(resource: Resource) -> bool:
    """Attend qu'une ressource soit « running » ; False après WAIT_TIMEOUT_SECONDS."""
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if current_status(resource).startswith("running"):
            return True
        time.sleep(5)
    return False


def power(action: str, environment: str, dry_run: bool) -> bool:
    """Allume (`on`) ou éteint (`off`) un environnement ; retourne True si tout a réussi."""
    plan = resources(environment)
    if action == "off":
        plan = list(reversed(plan))
    ok = True

    print(f"== {environment} : {'allumage' if action == 'on' else 'extinction'}")
    for resource in plan:
        label = f"{resource.kind[:-1]:<11} {resource.name} ({resource.status or 'inconnu'})"
        if (action == "on") == resource.is_running:
            print(f"   déjà {'allumé' if action == 'on' else 'éteint'} : {label}")
            continue
        if dry_run:
            print(f"   [simulation] {action} : {label}")
            continue

        verb = "start" if action == "on" else "stop"
        try:
            api("POST", f"/{resource.kind}/{resource.uuid}/{verb}")
        except urllib.error.HTTPError as error:
            print(f"   ÉCHEC {verb} : {label} (HTTP {error.code})")
            ok = False
            continue
        print(f"   {verb} : {label}")

        # Une base doit être prête avant de démarrer les applications qui s'y connectent.
        if action == "on" and resource.kind != "applications" and not wait_running(resource):
            print(f"   ÉCHEC : {resource.name} n'est pas « running » après {WAIT_TIMEOUT_SECONDS} s")
            ok = False
    return ok


def show_status(environment: str) -> None:
    """Affiche l'état de chaque ressource d'un environnement."""
    print(f"== {environment}")
    for resource in resources(environment):
        print(f"   {resource.kind[:-1]:<11} {resource.name:<40} {resource.status or 'inconnu'}")


def main() -> int:
    """Point d'entrée en ligne de commande."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("action", choices=["on", "off", "status"])
    parser.add_argument("environment", nargs="?", default="all", choices=[*ENVIRONMENTS, "all"])
    parser.add_argument("--dry-run", action="store_true", help="affiche le plan sans rien changer")
    args = parser.parse_args()

    environments = list(ENVIRONMENTS) if args.environment == "all" else [args.environment]
    if args.action == "status":
        for environment in environments:
            show_status(environment)
        return 0

    # Chaque environnement est traité, même si le précédent a échoué.
    results = [power(args.action, environment, args.dry_run) for environment in environments]
    ok = all(results)
    if args.action == "on" and not args.dry_run:
        print("Les API démarrent (health check /health/ready, ~1 min). Vérifier ensuite avec :")
        print("  python scripts/smoke_test.py https://express-delivery-preprod.romaincollery.com --mode full")
        print("  python scripts/smoke_test.py https://express-delivery.romaincollery.com --mode readonly")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
