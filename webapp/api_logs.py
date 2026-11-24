"""Recherche dans les logs (Query DSL), statistiques (cache Redis)
et historique des recherches (MongoDB).
"""
import json
import math
import os
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from auth import login_required
from extensions import ES_INDEX, cache, db, es

bp = Blueprint("logs", __name__, url_prefix="/api/v1")

FILTRES_EXACTS = ["level", "service", "endpoint", "tenant", "source", "user_id"]
FUSEAU = os.getenv("TZ_OFFSET", "+01:00")       # heure de Tunisie pour les dates saisies
STATS_TTL = 60                                   # durée du cache Redis (secondes)


class ParametreInvalide(ValueError):
    pass


def _date(valeur, nom):
    try:
        datetime.fromisoformat(valeur)
    except ValueError as exc:
        raise ParametreInvalide(f"{nom} invalide : format AAAA-MM-JJ ou AAAA-MM-JJTHH:MM") from exc
    return valeur


def construire_requete(args):
    """Traduit les paramètres de l'URL en requête Elasticsearch (Query DSL).

    Exemple : ?service=billing&status_min=500&date_from=2026-11-06
    devient :
      {"bool": {"filter": [
          {"term":  {"service": "billing"}},
          {"range": {"status_code": {"gte": 500}}},
          {"range": {"@timestamp": {"gte": "2026-11-06", "time_zone": "+01:00"}}}]}}
    """
    filtres = [{"term": {champ: (args[champ].upper() if champ == "level" else args[champ])}}
               for champ in FILTRES_EXACTS if args.get(champ)]

    status = {}
    for param, op in (("status_min", "gte"), ("status_max", "lte")):
        if args.get(param):
            try:
                status[op] = int(args[param])
            except ValueError as exc:
                raise ParametreInvalide(f"{param} doit être un nombre") from exc
    if status:
        filtres.append({"range": {"status_code": status}})

    if args.get("min_response_time"):
        try:
            filtres.append({"range": {"response_time": {"gte": float(args["min_response_time"])}}})
        except ValueError as exc:
            raise ParametreInvalide("min_response_time doit être un nombre") from exc

    periode = {}
    if args.get("date_from"):
        periode["gte"] = _date(args["date_from"], "date_from")
    if args.get("date_to"):
        fin = _date(args["date_to"], "date_to")
        periode["lte"] = fin + "T23:59:59.999" if len(fin) == 10 else fin   # jour entier inclus
    if periode:
        periode["time_zone"] = FUSEAU
        filtres.append({"range": {"@timestamp": periode}})

    texte = [{"match": {"message": {"query": args["q"], "operator": "and"}}}] if args.get("q") else []
    return {"bool": {"must": texte, "filter": filtres}}


@bp.errorhandler(ParametreInvalide)
def parametre_invalide(exc):
    return jsonify(erreur=str(exc)), 400


@bp.get("/logs")
@login_required("admin", "analyste")
def search_logs():
    """Rechercher dans les logs (combinaison libre des filtres).
    Chaque recherche est enregistrée dans l'historique (MongoDB).
    ---
    tags: [Logs]
    security: [{Bearer: []}]
    parameters:
      - {name: q, in: query, type: string, description: "Mots à chercher dans le message (plein texte)", example: ""}
      - {name: level, in: query, type: string, enum: [DEBUG, INFO, WARNING, ERROR, CRITICAL]}
      - {name: service, in: query, type: string, enum: [api, auth, billing, search, export, database]}
      - {name: endpoint, in: query, type: string, description: "ex. /api/payments"}
      - {name: tenant, in: query, type: string, description: "Entreprise cliente, ex. hamel"}
      - {name: source, in: query, type: string, enum: [nginx, flask, db]}
      - {name: user_id, in: query, type: string, description: "ex. u_1044"}
      - {name: status_min, in: query, type: integer, description: "ex. 500 pour les erreurs serveur"}
      - {name: status_max, in: query, type: integer}
      - {name: min_response_time, in: query, type: number, description: "Requêtes lentes : durée minimum en secondes, ex. 2"}
      - {name: date_from, in: query, type: string, description: "Début : AAAA-MM-JJ ou AAAA-MM-JJTHH:MM (heure de Tunisie)"}
      - {name: date_to, in: query, type: string, description: "Fin : AAAA-MM-JJ (jour inclus) ou AAAA-MM-JJTHH:MM"}
      - {name: sort, in: query, type: string, enum: [desc, asc], default: desc, description: "Tri par date"}
      - {name: page, in: query, type: integer, default: 1}
      - {name: size, in: query, type: integer, default: 20, description: "Résultats par page (max. 100)"}
    responses:
      200: {description: "Résultats paginés : total, page, pages, logs"}
      400: {description: Paramètre invalide}
      401: {description: Non connecté}
    """
    args = request.args
    try:
        page = max(int(args.get("page", 1)), 1)
        size = min(max(int(args.get("size", 20)), 1), 100)
    except ValueError:
        return jsonify(erreur="page et size doivent être des nombres"), 400
    if page * size > 10000:
        return jsonify(erreur="pagination limitée aux 10 000 premiers résultats : affinez la recherche"), 400
    ordre = "asc" if args.get("sort") == "asc" else "desc"

    requete = construire_requete(args)
    res = es.search(index=ES_INDEX, query=requete, sort=[{"@timestamp": ordre}],
                    from_=(page - 1) * size, size=size, track_total_hits=True)
    total = res["hits"]["total"]["value"]
    logs = [{"id": h["_id"], **h["_source"]} for h in res["hits"]["hits"]]

    filtres_utilises = {k: v for k, v in args.items() if v and k not in ("page", "size", "sort")}
    db.search_history.insert_one({
        "utilisateur": g.user["username"],
        "filtres": filtres_utilises,
        "total": total,
        "duree_ms": res["took"],
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return jsonify(total=total, page=page, pages=math.ceil(total / size), size=size,
                   duree_ms=res["took"], filtres=filtres_utilises, logs=logs)


@bp.get("/logs/<log_id>")
@login_required("admin", "analyste")
def get_log(log_id):
    """Détail d'un log (avec son index).
    ---
    tags: [Logs]
    security: [{Bearer: []}]
    parameters:
      - {name: log_id, in: path, type: string, required: true, description: "Champ id d'un résultat de recherche"}
    responses:
      200: {description: Le log}
      404: {description: Log introuvable}
    """
    res = es.search(index=ES_INDEX, query={"ids": {"values": [log_id]}}, size=1)
    hits = res["hits"]["hits"]
    if not hits:
        return jsonify(erreur="log introuvable"), 404
    return jsonify(id=hits[0]["_id"], index=hits[0]["_index"], **hits[0]["_source"])


@bp.get("/stats")
@login_required("admin", "analyste")
def stats():
    """Statistiques globales des logs, gardées 60 s dans le cache Redis.
    ---
    tags: [Logs]
    security: [{Bearer: []}]
    responses:
      200: {description: "Statistiques (champ source = elasticsearch ou cache_redis)"}
    """
    en_cache = cache.get("stats")
    if en_cache:
        return jsonify(source="cache_redis", expire_dans_s=cache.ttl("stats"), **json.loads(en_cache))

    res = es.search(index=ES_INDEX, size=0, track_total_hits=True, aggs={
        "par_service": {"terms": {"field": "service"}},
        "par_niveau": {"terms": {"field": "level"}},
        "par_source": {"terms": {"field": "source"}},
        "erreurs_5xx": {"filter": {"range": {"status_code": {"gte": 500}}}},
        "temps_moyen": {"avg": {"field": "response_time"}},
        "endpoints_lents": {
            "terms": {"field": "endpoint", "size": 5, "order": {"moyenne": "desc"}},
            "aggs": {"moyenne": {"avg": {"field": "response_time"}}},
        },
        "periode": {"stats": {"field": "@timestamp"}},
    })
    total = res["hits"]["total"]["value"]
    a = res["aggregations"]
    erreurs = a["erreurs_5xx"]["doc_count"]
    data = {
        "total_logs": total,
        "periode": {"debut": a["periode"].get("min_as_string"), "fin": a["periode"].get("max_as_string")},
        "par_service": {b["key"]: b["doc_count"] for b in a["par_service"]["buckets"]},
        "par_niveau": {b["key"]: b["doc_count"] for b in a["par_niveau"]["buckets"]},
        "par_source": {b["key"]: b["doc_count"] for b in a["par_source"]["buckets"]},
        "erreurs_5xx": erreurs,
        "taux_erreur_5xx_pct": round(100 * erreurs / total, 2) if total else 0,
        "temps_reponse_moyen_s": round(a["temps_moyen"]["value"] or 0, 3),
        "endpoints_les_plus_lents": [
            {"endpoint": b["key"], "temps_moyen_s": round(b["moyenne"]["value"] or 0, 3), "requetes": b["doc_count"]}
            for b in a["endpoints_lents"]["buckets"]],
    }
    cache.setex("stats", STATS_TTL, json.dumps(data))
    return jsonify(source="elasticsearch", **data)


@bp.get("/search-history")
@login_required("admin", "analyste")
def search_history():
    """Historique des recherches (les siennes ; un admin peut voir celles de tous).
    ---
    tags: [Historique]
    security: [{Bearer: []}]
    parameters:
      - {name: limit, in: query, type: integer, default: 20}
      - {name: all, in: query, type: boolean, default: false, description: "admin : voir tous les utilisateurs"}
    responses:
      200: {description: Dernières recherches, de la plus récente à la plus ancienne}
    """
    try:
        limit = min(max(int(request.args.get("limit", 20)), 1), 200)
    except ValueError:
        return jsonify(erreur="limit doit être un nombre"), 400
    tous = request.args.get("all", "").lower() == "true" and g.user["role"] == "admin"
    critere = {} if tous else {"utilisateur": g.user["username"]}
    items = list(db.search_history.find(critere, {"_id": 0}).sort("date", -1).limit(limit))
    return jsonify(total=len(items), recherches=items)


@bp.delete("/search-history")
@login_required("admin", "analyste")
def clear_history():
    """Effacer son propre historique de recherches.
    ---
    tags: [Historique]
    security: [{Bearer: []}]
    responses:
      200: {description: Historique effacé}
    """
    res = db.search_history.delete_many({"utilisateur": g.user["username"]})
    return jsonify(message="historique effacé", supprimees=res.deleted_count)
