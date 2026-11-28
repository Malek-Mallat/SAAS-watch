"""Pages de l'interface web (Sprint 4).

Les pages sont de simples gabarits HTML : toutes les données viennent de l'API
/api/v1 appelée en JavaScript (static/app.js) avec le jeton JWT de l'utilisateur.
"""
import os

from flask import Blueprint, render_template

bp = Blueprint("web", __name__)

KIBANA_URL = os.getenv("KIBANA_PUBLIC_URL", "http://localhost:5601")
DASHBOARD_URL = os.getenv("KIBANA_DASHBOARD_URL", "")


@bp.get("/login")
def login():
    return render_template("login.html")


@bp.get("/")
def accueil():
    return render_template("accueil.html", page="accueil")


@bp.get("/import")
def importer():
    return render_template("import.html", page="import")


@bp.get("/recherche")
def recherche():
    return render_template("recherche.html", page="recherche")


@bp.get("/historique")
def historique():
    return render_template("historique.html", page="historique")


@bp.get("/dashboard")
def dashboard():
    return render_template("dashboard.html", page="dashboard",
                           dashboard_url=DASHBOARD_URL, kibana_url=KIBANA_URL)
