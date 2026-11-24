"""Règles d'alerte stockées dans MongoDB (collection "alert_rules").

Au Sprint 3 on enregistre les règles. Leur déclenchement automatique
(module "alerting intelligent") est prévu pour un sprint suivant.
"""
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from flask import Blueprint, g, jsonify, request

from auth import login_required
from extensions import db

bp = Blueprint("alerts", __name__, url_prefix="/api/v1")


def _sortie(doc):
    doc["id"] = str(doc.pop("_id"))
    return doc


@bp.get("/alerts")
@login_required("admin", "analyste")
def list_alerts():
    """Liste des règles d'alerte.
    ---
    tags: [Alertes]
    security: [{Bearer: []}]
    responses:
      200: {description: Règles enregistrées dans MongoDB}
    """
    regles = [_sortie(d) for d in db.alert_rules.find().sort("cree_le", -1)]
    return jsonify(total=len(regles), regles=regles)


@bp.post("/alerts")
@login_required("admin")
def create_alert():
    """Créer une règle d'alerte (admin uniquement).
    ---
    tags: [Alertes]
    security: [{Bearer: []}]
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [nom, service, seuil_erreurs]
          properties:
            nom: {type: string, example: "Pannes paiement"}
            service: {type: string, example: billing}
            seuil_erreurs: {type: integer, example: 50, description: "Nombre d'erreurs 5xx qui déclenche l'alerte"}
            fenetre_minutes: {type: integer, example: 10, description: "Période observée"}
            email: {type: string, example: "admin@saaswatch.tn"}
    responses:
      201: {description: Règle créée}
      400: {description: Champ manquant ou invalide}
      403: {description: Réservé aux admins}
    """
    data = request.get_json(silent=True) or {}
    manquants = [c for c in ("nom", "service", "seuil_erreurs") if c not in data]
    if manquants:
        return jsonify(erreur=f"champs manquants : {', '.join(manquants)}"), 400
    try:
        seuil = int(data["seuil_erreurs"])
        fenetre = int(data.get("fenetre_minutes", 10))
    except (TypeError, ValueError):
        return jsonify(erreur="seuil_erreurs et fenetre_minutes doivent être des nombres"), 400
    if seuil <= 0 or fenetre <= 0:
        return jsonify(erreur="seuil_erreurs et fenetre_minutes doivent être positifs"), 400
    regle = {
        "nom": str(data["nom"]),
        "service": str(data["service"]),
        "seuil_erreurs": seuil,
        "fenetre_minutes": fenetre,
        "email": str(data.get("email", "")),
        "active": True,
        "cree_par": g.user["username"],
        "cree_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    res = db.alert_rules.insert_one(dict(regle))
    return jsonify(message="règle créée", id=str(res.inserted_id), regle=regle), 201


@bp.delete("/alerts/<alert_id>")
@login_required("admin")
def delete_alert(alert_id):
    """Supprimer une règle d'alerte (admin uniquement).
    ---
    tags: [Alertes]
    security: [{Bearer: []}]
    parameters:
      - {name: alert_id, in: path, type: string, required: true}
    responses:
      200: {description: Règle supprimée}
      404: {description: Règle introuvable}
    """
    try:
        res = db.alert_rules.delete_one({"_id": ObjectId(alert_id)})
    except InvalidId:
        return jsonify(erreur="identifiant invalide"), 404
    if res.deleted_count == 0:
        return jsonify(erreur="règle introuvable"), 404
    return jsonify(message="règle supprimée")
