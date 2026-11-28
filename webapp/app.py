"""SaaSWatch — application Flask : API REST (Sprint 3) + interface web (Sprint 4).

API REST versionnée /api/v1, documentée avec Swagger : http://localhost:8000/apidocs

Organisation du code :
  extensions.py   connexions Elasticsearch, MongoDB, Redis
  auth.py         connexion (JWT), rôles admin / analyste, utilisateurs
  validation.py   contrôle des fichiers CSV / JSON
  api_uploads.py  import des fichiers + métadonnées MongoDB
  api_logs.py     recherche Query DSL, statistiques (cache Redis), historique
  api_alerts.py   règles d'alerte (MongoDB)
  web.py          pages de l'interface web (templates/ + static/)
"""
import logging
import os

from elasticsearch import ConnectionError as ESConnectionError
from flasgger import Swagger
from flask import Flask, jsonify, redirect, request, url_for
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

import api_alerts
import api_logs
import api_uploads
import auth
import web
from extensions import ES_INDEX, cache, es, mongo

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-change-me")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024        # 20 Mo par fichier
app.json.ensure_ascii = False                               # « é » lisible dans les réponses
app.json.sort_keys = False

Swagger(app, template={
    "info": {
        "title": "SaaSWatch API",
        "version": "1.0",
        "description": (
            "API de monitoring des logs d'une application SaaS "
            "(Elasticsearch + MongoDB + Redis).\n\n"
            "**Pour tester :** 1) `POST /api/v1/auth/login` avec admin / admin123, "
            "2) copier le token, 3) bouton **Authorize** → `Bearer <token>`."
        ),
    },
    "securityDefinitions": {
        "Bearer": {"type": "apiKey", "name": "Authorization", "in": "header",
                   "description": "Saisir : Bearer <token>"},
    },
})

for module in (auth, api_uploads, api_logs, api_alerts, web):
    app.register_blueprint(module.bp)

try:
    auth.init_users()
except PyMongoError as exc:      # MongoDB pas encore prêt : l'app démarre quand même
    logging.warning("Compte admin non créé : %s", exc)


def check(fn):
    try:
        fn()
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"erreur : {exc.__class__.__name__}"


# --------------------------------------------------------------------------
# Santé (sans authentification)
# --------------------------------------------------------------------------
@app.get("/health")
def health():
    """Test simple utilisé par le healthcheck Docker.
    ---
    tags: [Santé]
    responses:
      200: {description: L'application répond}
    """
    return jsonify(status="ok")


@app.get("/status")
def status():
    """Vérifie la connexion à Elasticsearch, MongoDB et Redis.
    ---
    tags: [Santé]
    responses:
      200: {description: Tous les services répondent}
      503: {description: Au moins un service ne répond pas}
    """
    services = {
        "elasticsearch": check(lambda: es.info()),
        "mongodb": check(lambda: mongo.admin.command("ping")),
        "redis": check(lambda: cache.ping()),
    }
    try:
        nb_logs = es.count(index=ES_INDEX)["count"]
    except Exception:  # noqa: BLE001
        nb_logs = 0
    tout_ok = all(v == "ok" for v in services.values())
    return jsonify(application="SaaSWatch", version="1.0", services=services, logs_indexes=nb_logs,
                   statut="opérationnel" if tout_ok else "dégradé"), (200 if tout_ok else 503)


# --------------------------------------------------------------------------
# Erreurs renvoyées en JSON (et non en page HTML)
# --------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_):
    if not request.path.startswith("/api/"):
        return redirect(url_for("web.accueil"))
    return jsonify(erreur=f"route introuvable : {request.path}"), 404


@app.errorhandler(405)
def method_not_allowed(_):
    return jsonify(erreur=f"méthode {request.method} non autorisée sur {request.path}"), 405


@app.errorhandler(413)
def too_large(_):
    return jsonify(erreur="fichier trop volumineux (20 Mo maximum)"), 413


@app.errorhandler(ESConnectionError)
def es_down(_):
    return jsonify(erreur="Elasticsearch ne répond pas"), 503


@app.errorhandler(PyMongoError)
def mongo_down(exc):
    return jsonify(erreur=f"erreur MongoDB : {exc.__class__.__name__}"), 503


@app.errorhandler(RedisError)
def redis_down(_):
    return jsonify(erreur="Redis ne répond pas"), 503
