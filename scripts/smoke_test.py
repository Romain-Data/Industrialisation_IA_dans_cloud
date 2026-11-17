"""Tests de fumée d'un environnement déployé (préprod ou prod), lancés par la CI/CD (ADR-0004).

Usage :
    python scripts/smoke_test.py https://express-delivery-preprod.example.com --mode full
    python scripts/smoke_test.py https://express-delivery.example.com --mode readonly

- `readonly` (prod) : santé, disponibilité, model card et prédiction synchrone ; rien
  n'est écrit dans la base.
- `full` (préprod) : en plus, une commande de test est enregistrée et l'on attend que
  le worker calcule sa prédiction (parcours asynchrone complet).

Bibliothèque standard uniquement : le script tourne tel quel sur un runner GitHub.
Code de sortie 0 si tout passe, 1 sinon.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

# Commande au format de l'ERP (contrat 2.0.0).
ERP_ORDER = {
    "hour": 14,
    "day_of_week": 2,
    "weekend": 0,
    "distance_km": 6.5,
    "order_value_eur": 89.9,
    "weight_kg": 2.4,
    "stock_available": 1,
    "preparation_time_min": 18,
    "carrier_capacity": 34.5,
    "weather": "rain",
    "delivery_zone": "suburb",
    "customer_type": "business",
}


def call(base_url, method, path, body=None, timeout=10):
    """Appelle l'API ; retourne (code HTTP, corps JSON ou None)."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        base_url + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or "null")
    except urllib.error.HTTPError as error:
        return error.code, None
    except (urllib.error.URLError, TimeoutError):
        return None, None


def wait_until_ready(base_url, timeout):
    """Attend que /health/ready réponde 200 (redémarrage, chargement du modèle)."""
    deadline = time.monotonic() + timeout
    while True:
        status, body = call(base_url, "GET", "/health/ready")
        if status == 200:
            return body
        if time.monotonic() > deadline:
            raise AssertionError(f"/health/ready ne répond pas 200 (dernier statut : {status}, {body})")
        time.sleep(5)


def check(name, condition, detail=""):
    """Affiche le résultat d'un contrôle et lève une erreur s'il échoue."""
    print(f"{'✓' if condition else '✗'} {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        raise AssertionError(name)


def run(base_url, mode, ready_timeout):
    """Enchaîne les contrôles ; s'arrête au premier échec."""
    ready = wait_until_ready(base_url, ready_timeout)
    check("disponibilité (/health/ready)", ready.get("status") == "ready", json.dumps(ready["checks"]))

    status, health = call(base_url, "GET", "/health")
    check("vivacité (/health)", status == 200 and health["status"] == "ok", f"version {health and health['version']}")

    status, card = call(base_url, "GET", "/v1/model")
    check("model card (/v1/model)", status == 200 and bool(card.get("metrics")),
          f"roc_auc={card and round(card['metrics'].get('roc_auc', 0), 3)}")

    status, prediction = call(base_url, "POST", "/v1/predictions", ERP_ORDER)
    check("prédiction synchrone", status == 200 and 0 <= prediction["probability"] <= 1,
          f"{prediction and prediction['decision']} ({prediction and prediction['probability']})")

    status, _ = call(base_url, "POST", "/v1/predictions", {**ERP_ORDER, "weather": "orage"})
    check("ancien vocabulaire refusé (422)", status == 422)

    if mode == "full":
        status, accepted = call(base_url, "POST", "/v1/orders", ERP_ORDER)
        check("commande acceptée (202)", status == 202)
        order_id = accepted["order_id"]
        deadline = time.monotonic() + 30
        while (result := call(base_url, "GET", f"/v1/predictions/{order_id}"))[0] != 200:
            if time.monotonic() > deadline:
                break
            time.sleep(1)
        check("prédiction asynchrone par le worker", result[0] == 200, order_id)


def main():
    """Point d'entrée en ligne de commande."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("base_url")
    parser.add_argument("--mode", choices=["full", "readonly"], default="readonly")
    parser.add_argument("--ready-timeout", type=int, default=180)
    args = parser.parse_args()

    print(f"Tests de fumée ({args.mode}) : {args.base_url}")
    try:
        run(args.base_url.rstrip("/"), args.mode, args.ready_timeout)
    except AssertionError as error:
        print(f"ÉCHEC : {error}")
        return 1
    print("Tous les contrôles sont passés.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
