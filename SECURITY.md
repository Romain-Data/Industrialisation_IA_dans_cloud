# Politique de sécurité

## Versions maintenues

Seule la dernière version publiée (dernière [GitHub Release](https://github.com/Romain-Data/Industrialisation_IA_dans_cloud/releases), déployée en prod) reçoit des correctifs de sécurité. Les correctifs sont livrés par une nouvelle version corrective (`hotfix/x.y.z`, voir [CONTRIBUTING.md](CONTRIBUTING.md)).

| Version | Correctifs de sécurité |
|---|---|
| Dernière release | ✅ |
| Versions antérieures | ❌ |

## Signaler une vulnérabilité

**N'ouvrez pas d'issue publique** pour une faille de sécurité.

Utilisez le signalement privé de GitHub : onglet **Security** du dépôt, puis **Report a vulnerability** ([lien direct](https://github.com/Romain-Data/Industrialisation_IA_dans_cloud/security/advisories/new)). Seuls les mainteneurs voient le rapport.

Indiquez si possible :

- le composant concerné (API, image Docker, CI, dépendance) et la version ou le commit ;
- une description de la faille et de son impact ;
- les étapes pour la reproduire, sans données réelles ;
- une piste de correction si vous en avez une.

## Ce qui se passe ensuite

- accusé de réception sous **7 jours** ;
- évaluation de la gravité et, si la faille est confirmée, correctif et nouvelle version dès que possible (sous **30 jours** pour une faille critique) ;
- publication d'un avis de sécurité GitHub une fois le correctif déployé, en vous créditant si vous le souhaitez.

Ce projet est maintenu dans un cadre de formation : ces délais sont des objectifs, pas des engagements contractuels.

## Mesures en place

- **Image Docker** : construction en deux étapes, image de base `python:slim` avec les correctifs de sécurité Debian appliqués, exécution avec un utilisateur non root, aucun secret dans l'image (`.dockerignore`).
- **CI** : scan de l'image avec [Trivy](https://trivy.dev/) avant chaque publication ; la publication échoue sur toute vulnérabilité critique corrigeable.
- **Secrets** : aucun secret dans le dépôt (`.env` ignoré). Les secrets d'exécution sont stockés dans Coolify, ceux de déploiement dans les secrets GitHub Actions ; le jeton de déploiement est limité au projet Coolify de l'application.
- **Dépendances** : versions figées par `uv.lock`.
- **API** : validation stricte des entrées (Pydantic, champs inconnus refusés), HTTPS assuré par le proxy de Coolify.

Les limites connues (notamment l'absence d'authentification sur l'API) et les évolutions prévues sont décrites dans l'[ADR-0005](IndusIAdansCloud/ADR/ADR-0005%20-%20S%C3%A9curisation.md).
