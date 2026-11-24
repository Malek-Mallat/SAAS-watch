"""Connexions partagées : Elasticsearch, MongoDB et Redis.

Chaque module de l'application importe ses clients depuis ce fichier,
pour n'ouvrir qu'une seule connexion par service.
"""
import os

import redis
from elasticsearch import Elasticsearch
from pymongo import MongoClient

ES_INDEX = "logs-saas-*"
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/data/uploads")

es = Elasticsearch(os.getenv("ES_HOST", "http://elasticsearch:9200"), request_timeout=10)
mongo = MongoClient(os.getenv("MONGO_URI"), serverSelectionTimeoutMS=3000)
db = mongo["saaswatch"]                     # base MongoDB de l'application
cache = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))

# Collections MongoDB utilisées
#   users           comptes et rôles
#   uploads         métadonnées des fichiers importés
#   search_history  historique des recherches
#   alert_rules     règles d'alerte
