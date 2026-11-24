"""Authentification par jeton JWT et gestion des rôles.

Rôles :
  admin     : tout, y compris créer des utilisateurs, créer/supprimer des alertes,
              supprimer des fichiers
  analyste  : rechercher, consulter les statistiques, importer des fichiers

Utilisation dans Swagger :
  1. POST /api/v1/auth/login  -> copier le "token"
  2. bouton "Authorize" en haut -> coller : Bearer <token>
"""
import os
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import Blueprint, current_app, g, jsonify, request
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db

bp = Blueprint("auth", __name__, url_prefix="/api/v1")

ROLES = ("admin", "analyste")
TOKEN_HOURS = 8


# --------------------------------------------------------------------------
# Outils
# --------------------------------------------------------------------------
def create_token(user):
    payload = {
        "sub": user["username"],
        "role": user["role"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def login_required(*roles):
    """Décorateur : exige un jeton valide, et un des rôles donnés (si précisés)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            token = header[7:] if header.lower().startswith("bearer ") else header
            if not token:
                return jsonify(erreur="jeton manquant : connectez-vous avec /api/v1/auth/login"), 401
            try:
                data = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
            except jwt.ExpiredSignatureError:
                return jsonify(erreur="jeton expiré, reconnectez-vous"), 401
            except jwt.InvalidTokenError:
                return jsonify(erreur="jeton invalide"), 401
            if roles and data["role"] not in roles:
                return jsonify(erreur=f"accès refusé : rôle requis {', '.join(roles)}"), 403
            g.user = {"username": data["sub"], "role": data["role"]}
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def init_users():
    """Crée l'index unique et le compte admin par défaut (une seule fois)."""
    db.users.create_index("username", unique=True)
    db.users.update_one(
        {"username": os.getenv("ADMIN_USERNAME", "admin")},
        {"$setOnInsert": {
            "password": generate_password_hash(os.getenv("ADMIN_PASSWORD", "admin123")),
            "role": "admin",
            "cree_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }},
        upsert=True,
    )


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@bp.post("/auth/login")
def login():
    """Se connecter et recevoir un jeton JWT (valable 8 heures).
    ---
    tags: [Authentification]
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [username, password]
          properties:
            username: {type: string, example: admin}
            password: {type: string, example: admin123}
    responses:
      200: {description: "Connexion réussie : copier le token"}
      401: {description: Identifiants incorrects}
    """
    data = request.get_json(silent=True) or {}
    user = db.users.find_one({"username": data.get("username", "")})
    if not user or not check_password_hash(user["password"], data.get("password", "")):
        return jsonify(erreur="identifiants incorrects"), 401
    return jsonify(token=create_token(user), type="Bearer", expire_dans_heures=TOKEN_HOURS,
                   utilisateur={"username": user["username"], "role": user["role"]})


@bp.get("/auth/me")
@login_required()
def me():
    """Utilisateur connecté (vérifie que le jeton fonctionne).
    ---
    tags: [Authentification]
    security: [{Bearer: []}]
    responses:
      200: {description: Utilisateur connecté}
      401: {description: Jeton manquant ou invalide}
    """
    return jsonify(utilisateur=g.user)


@bp.post("/users")
@login_required("admin")
def create_user():
    """Créer un utilisateur (admin uniquement).
    ---
    tags: [Utilisateurs]
    security: [{Bearer: []}]
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [username, password, role]
          properties:
            username: {type: string, example: analyste1}
            password: {type: string, example: analyste123}
            role: {type: string, enum: [admin, analyste], example: analyste}
    responses:
      201: {description: Utilisateur créé}
      400: {description: Données invalides}
      403: {description: Réservé aux admins}
      409: {description: Nom d'utilisateur déjà pris}
    """
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    role = data.get("role", "analyste")
    if len(username) < 3 or len(password) < 6:
        return jsonify(erreur="username (3 caractères min.) et password (6 caractères min.) obligatoires"), 400
    if role not in ROLES:
        return jsonify(erreur=f"rôle invalide : {', '.join(ROLES)}"), 400
    try:
        db.users.insert_one({
            "username": username,
            "password": generate_password_hash(password),
            "role": role,
            "cree_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cree_par": g.user["username"],
        })
    except DuplicateKeyError:
        return jsonify(erreur="ce nom d'utilisateur existe déjà"), 409
    return jsonify(message="utilisateur créé", utilisateur={"username": username, "role": role}), 201


@bp.get("/users")
@login_required("admin")
def list_users():
    """Liste des utilisateurs (admin uniquement, sans les mots de passe).
    ---
    tags: [Utilisateurs]
    security: [{Bearer: []}]
    responses:
      200: {description: Liste des utilisateurs}
    """
    users = list(db.users.find({}, {"_id": 0, "password": 0}))
    return jsonify(total=len(users), utilisateurs=users)
