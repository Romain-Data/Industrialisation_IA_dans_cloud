"""Déploie une image sur une application Coolify et attend le résultat (CI/CD, ADR-0004).

Usage (variables COOLIFY_URL et COOLIFY_TOKEN dans l'environnement) :
    python scripts/coolify_deploy.py <app_uuid> <image> <tag> [--timeout 900]

1. fixe l'image et le tag de l'application (PATCH /applications/{uuid}) ;
2. lance le déploiement (POST /deploy) ;
3. attend sa fin : Coolify ne le déclare « finished » que si le health check de la
   nouvelle version passe ; sinon « failed », et l'ancienne version reste en service.

Bibliothèque standard uniquement. Code de sortie 0 si le déploiement réussit, 1 sinon.
"""

import argparse
import json
import os
import sys
import time
import urllib.request

FINAL_STATES = {"finished", "failed", "cancelled-by-user"}


def api(method, path, body=None):
    """Appel de l'API Coolify (les réponses peuvent contenir des caractères de contrôle)."""
    base = os.environ["COOLIFY_URL"].rstrip("/")
    request = urllib.request.Request(
        f"{base}/api/v1{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {os.environ['COOLIFY_TOKEN']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    return json.loads(raw, strict=False) if raw else {}


def deploy(app_uuid, image, tag, timeout):
    """Déploie et retourne l'état final du déploiement."""
    api("PATCH", f"/applications/{app_uuid}",
        {"docker_registry_image_name": image, "docker_registry_image_tag": tag})
    print(f"Application {app_uuid} pointée sur {image}:{tag}")

    deployment = api("POST", f"/deploy?uuid={app_uuid}")["deployments"][0]["deployment_uuid"]
    print(f"Déploiement {deployment} lancé, attente du résultat…")

    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        status = api("GET", f"/deployments/{deployment}").get("status")
        if status in FINAL_STATES:
            break
        time.sleep(10)
    print(f"État final : {status}")
    return status


def main():
    """Point d'entrée en ligne de commande."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("app_uuid")
    parser.add_argument("image")
    parser.add_argument("tag")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    status = deploy(args.app_uuid, args.image.lower(), args.tag, args.timeout)
    return 0 if status == "finished" else 1


if __name__ == "__main__":
    sys.exit(main())
