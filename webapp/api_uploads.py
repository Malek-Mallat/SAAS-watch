"""Import des fichiers de logs.

Chemin d'un fichier :
  1. POST /api/v1/uploads : l'API valide le fichier ligne par ligne
  2. s'il est valide, il est enregistré dans /data/uploads (dossier lu par Logstash)
     et ses métadonnées sont stockées dans MongoDB (collection "uploads")
  3. Logstash l'indexe dans Elasticsearch
  4. GET /api/v1/uploads compare les lignes du fichier aux documents indexés
     (champ file_name) pour afficher le statut : en_attente / en_cours / indexé
"""
import os
import uuid
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from flask import Blueprint, g, jsonify, request
from werkzeug.utils import secure_filename

from auth import login_required
from extensions import ES_INDEX, UPLOAD_DIR, cache, db, es
from validation import valider

bp = Blueprint("uploads", __name__, url_prefix="/api/v1")

EXTENSIONS = {"csv", "json"}


def _nb_indexes(nom_fichier):
    try:
        return es.count(index=ES_INDEX, query={"term": {"file_name": nom_fichier}})["count"]
    except Exception:  # noqa: BLE001  (ES indisponible : on n'empêche pas l'affichage)
        return None


def _avec_statut(doc):
    """Ajoute le statut d'indexation calculé à partir d'Elasticsearch."""
    doc["id"] = str(doc.pop("_id"))
    indexes = _nb_indexes(doc["fichier_stocke"])
    doc["documents_indexes"] = indexes
    if indexes is None:
        doc["statut"] = "inconnu (Elasticsearch indisponible)"
    elif indexes == 0:
        doc["statut"] = "en_attente"
    elif indexes < doc["lignes"]:
        doc["statut"] = "en_cours"
    else:
        doc["statut"] = "indexé"
    return doc


def _trouver(upload_id):
    try:
        return db.uploads.find_one({"_id": ObjectId(upload_id)})
    except InvalidId:
        return None


@bp.post("/uploads")
@login_required("admin", "analyste")
def upload_file():
    """Importer un fichier de logs (CSV ou JSON, 20 Mo max.).
    Le fichier est validé ligne par ligne avant d'être envoyé à Logstash.
    ---
    tags: [Import de fichiers]
    security: [{Bearer: []}]
    consumes: [multipart/form-data]
    parameters:
      - {name: file, in: formData, type: file, required: true,
         description: "Fichier .csv (14 colonnes, séparateur virgule) ou .json (un objet par ligne)"}
    responses:
      201: {description: Fichier accepté et envoyé à l'indexation}
      400: {description: "Fichier refusé : la réponse liste les erreurs"}
      413: {description: Fichier trop volumineux}
    """
    fichier = request.files.get("file")
    if not fichier or not fichier.filename:
        return jsonify(erreur="aucun fichier envoyé (champ « file »)"), 400
    nom = secure_filename(fichier.filename)
    extension = nom.rsplit(".", 1)[-1].lower() if "." in nom else ""
    if extension not in EXTENSIONS:
        return jsonify(erreur="format refusé : seuls .csv et .json sont acceptés"), 400

    contenu = fichier.read()
    texte, lignes, erreurs = valider(contenu, extension)
    if erreurs:
        return jsonify(erreur="fichier refusé", fichier=nom, lignes_lues=lignes,
                       erreurs=erreurs), 400

    # Nom unique : évite d'écraser un fichier et de le faire réindexer deux fois
    horodatage = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stocke = f"{horodatage}_{uuid.uuid4().hex[:6]}_{nom}"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    chemin = os.path.join(UPLOAD_DIR, stocke)
    # Écriture dans un .tmp puis renommage : Logstash ne lit jamais un fichier à moitié écrit
    with open(chemin + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write(texte)
    os.replace(chemin + ".tmp", chemin)

    meta = {
        "nom_original": fichier.filename,
        "fichier_stocke": stocke,
        "format": extension,
        "taille_octets": len(contenu),
        "lignes": lignes,
        "importe_par": g.user["username"],
        "importe_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    res = db.uploads.insert_one(dict(meta))
    cache.delete("stats")                      # les statistiques vont changer
    return jsonify(message="fichier accepté : indexation par Logstash en cours (≈ 30 s)",
                   id=str(res.inserted_id), **meta), 201


@bp.get("/uploads")
@login_required("admin", "analyste")
def list_uploads():
    """Liste des fichiers importés, avec leur statut d'indexation.
    ---
    tags: [Import de fichiers]
    security: [{Bearer: []}]
    responses:
      200: {description: "Fichiers (statut : en_attente, en_cours ou indexé)"}
    """
    docs = [_avec_statut(d) for d in db.uploads.find().sort("importe_le", -1).limit(100)]
    return jsonify(total=len(docs), fichiers=docs)


@bp.get("/uploads/<upload_id>")
@login_required("admin", "analyste")
def get_upload(upload_id):
    """Détail d'un fichier importé.
    ---
    tags: [Import de fichiers]
    security: [{Bearer: []}]
    parameters:
      - {name: upload_id, in: path, type: string, required: true}
    responses:
      200: {description: Métadonnées et statut}
      404: {description: Fichier introuvable}
    """
    doc = _trouver(upload_id)
    if not doc:
        return jsonify(erreur="fichier introuvable"), 404
    return jsonify(_avec_statut(doc))


@bp.delete("/uploads/<upload_id>")
@login_required("admin")
def delete_upload(upload_id):
    """Supprimer un fichier et tous ses logs indexés (admin uniquement).
    ---
    tags: [Import de fichiers]
    security: [{Bearer: []}]
    parameters:
      - {name: upload_id, in: path, type: string, required: true}
    responses:
      200: {description: Fichier et logs supprimés}
      404: {description: Fichier introuvable}
    """
    doc = _trouver(upload_id)
    if not doc:
        return jsonify(erreur="fichier introuvable"), 404
    res = es.delete_by_query(index=ES_INDEX, query={"term": {"file_name": doc["fichier_stocke"]}},
                             refresh=True, conflicts="proceed")
    chemin = os.path.join(UPLOAD_DIR, doc["fichier_stocke"])
    if os.path.exists(chemin):
        os.remove(chemin)
    db.uploads.delete_one({"_id": doc["_id"]})
    cache.delete("stats")
    return jsonify(message="fichier supprimé", logs_supprimes=res.get("deleted", 0))
