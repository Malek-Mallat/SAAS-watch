# SaaSWatch

Plateforme de monitoring et d'analyse des logs d'une application SaaS avec la stack **ELK** (Elasticsearch, Logstash, Kibana), **MongoDB** et **Redis**.

Mini-projet Big Data — ITBS 2026-2027 — Scénario D (Application Web SaaS).

## Architecture

| Service | Rôle | Port |
|---|---|---|
| elasticsearch | Stockage et recherche des logs (index `logs-saas-*`) | 9200 |
| logstash | Ingestion des fichiers CSV et JSON de `data/uploads` | 9600 |
| kibana | Visualisations et dashboards | 5601 |
| mongodb | Métadonnées, historique, règles d'alerte | 27017 |
| redis | Cache, sessions, files d'attente | 6379 |
| webapp | Application Flask (interface + API) | 8000 |
| es-init | Crée l'index template au démarrage, puis s'arrête | — |

## Prérequis

- Docker Desktop (Docker 24+ et Docker Compose 2+)
- 6 Go de RAM disponibles pour Docker
- Python 3.11 (uniquement pour le générateur de logs)

## Installation

```bash
git clone https://github.com/Malek-Mallat/saaswatch.git
cd saaswatch
cp .env.example .env        # sous Windows : copy .env.example .env
docker compose up -d --build
```

Attendre 1 à 2 minutes, puis vérifier :

```bash
docker compose ps
```

Tous les services doivent être `running` ou `healthy`, sauf `es-init` qui est `exited (0)` (normal : il s'arrête après avoir créé le template).

## Vérifications

| URL | Résultat attendu |
|---|---|
| http://localhost:9200 | Réponse JSON d'Elasticsearch |
| http://localhost:5601 | Interface Kibana |
| http://localhost:8000/status | Les 3 services à `ok` |

## Générer et importer des logs

```bash
cd generator
pip install -r requirements.txt
python generate_logs.py --rows 5000 --format csv --out ../data/uploads/logs_api.csv --incident
python generate_logs.py --rows 2000 --format json --out ../data/uploads/logs_app.json
```

Logstash lit automatiquement tout fichier `.csv` ou `.json` déposé dans `data/uploads`.
Des fichiers d'exemple sont aussi disponibles dans `data/samples` : il suffit de les copier dans `data/uploads`.

Vérifier l'import :

```bash
curl "http://localhost:9200/_cat/indices/logs-saas-*?v"
curl "http://localhost:9200/logs-saas-*/_count"
```

## API REST (Sprint 3)

Documentation et tests interactifs : **http://localhost:8000/apidocs** (Swagger).

1. `POST /api/v1/auth/login` avec `admin` / `admin123` (compte créé au premier démarrage, voir `.env`)
2. copier le `token`, cliquer sur **Authorize** et saisir `Bearer <token>`

| Méthode | Route | Rôle | Description |
|---|---|---|---|
| POST | `/api/v1/auth/login` | public | Connexion, renvoie un jeton JWT (8 h) |
| GET | `/api/v1/auth/me` | connecté | Utilisateur courant |
| POST / GET | `/api/v1/users` | admin | Créer / lister les utilisateurs |
| POST | `/api/v1/uploads` | admin, analyste | Importer un fichier CSV/JSON (validé ligne par ligne) |
| GET | `/api/v1/uploads[/<id>]` | admin, analyste | Fichiers importés et statut d'indexation |
| DELETE | `/api/v1/uploads/<id>` | admin | Supprimer un fichier et ses logs |
| GET | `/api/v1/logs` | admin, analyste | Recherche : `q`, `level`, `service`, `endpoint`, `tenant`, `source`, `user_id`, `status_min/max`, `min_response_time`, `date_from/to`, pagination |
| GET | `/api/v1/logs/<id>` | admin, analyste | Détail d'un log |
| GET | `/api/v1/stats` | admin, analyste | Statistiques (cache Redis 60 s) |
| GET / DELETE | `/api/v1/search-history` | admin, analyste | Historique des recherches (MongoDB) |
| GET / POST / DELETE | `/api/v1/alerts` | lecture : tous, écriture : admin | Règles d'alerte (MongoDB) |

Rôle de chaque base :

| Base | Données |
|---|---|
| Elasticsearch | les logs (recherche, agrégations) |
| MongoDB | `users`, `uploads` (métadonnées des fichiers), `search_history`, `alert_rules` |
| Redis | cache des statistiques |

### Tests Postman

Importer `docs/postman/SaaSWatch.postman_collection.json` dans Postman, choisir le fichier
`data/samples/test_upload.csv` dans la requête « Importer un CSV », puis lancer la collection
avec le **Collection Runner** (27 requêtes, tests automatiques).

## Interface web (Sprint 4)

Ouvrir **http://localhost:8000** et se connecter (admin / admin123 par défaut).

| Page | Contenu |
|---|---|
| Accueil `/` | Indicateurs (logs, erreurs 5xx, taux d'erreur, temps moyen), activité dans le temps, logs par service et par niveau, endpoints les plus lents (Chart.js) |
| Import `/import` | Glisser-déposer de fichiers CSV/JSON, erreurs de validation, statut d'indexation en direct |
| Recherche `/recherche` | Filtres combinables, tableau paginé (DataTables), détail d'un log, export CSV |
| Historique `/historique` | Recherches passées, bouton « Relancer » |
| Dashboard `/dashboard` | Dashboard Kibana intégré (variable `KIBANA_DASHBOARD_URL` du `.env`) |

L'interface n'accède jamais directement aux bases : chaque page appelle l'API `/api/v1` en JavaScript avec le jeton JWT de l'utilisateur.

## Arrêt

```bash
docker compose stop        # arrêter
docker compose down        # arrêter et supprimer les conteneurs (les données restent)
docker compose down -v     # tout supprimer, y compris les données
```

## Structure du projet

```
saaswatch/
├── docker-compose.yml
├── .env.example
├── elasticsearch/      index template + script d'initialisation
├── logstash/           configuration et pipelines CSV / JSON
├── webapp/             application Flask : API REST /api/v1 + Swagger, interface web (templates/, static/)
├── generator/          générateur de logs (Faker)
├── data/uploads/       fichiers à ingérer
├── data/samples/       fichiers d'exemple
└── docs/               dossier d'analyse et de conception, collection Postman
```
