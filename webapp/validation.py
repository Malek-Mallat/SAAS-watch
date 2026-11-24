"""Validation des fichiers de logs avant leur import.

Un fichier est accepté seulement si TOUTES ses lignes sont valides.
Sinon, l'API renvoie la liste des erreurs (10 premières) et le fichier
n'est pas enregistré : Elasticsearch ne reçoit jamais de données cassées.
"""
import csv
import io
import json
from datetime import datetime

COLONNES = ["timestamp", "level", "service", "source", "http_method", "endpoint",
            "status_code", "response_time", "user_id", "tenant", "feature",
            "client_ip", "sql_query", "message"]
OBLIGATOIRES = ["timestamp", "level", "service", "message"]
NIVEAUX = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
MAX_ERREURS = 10


def _verifier_log(log, num):
    """Contrôle une ligne. Renvoie la liste de ses erreurs (vide si tout va bien)."""
    erreurs = []
    for champ in OBLIGATOIRES:
        if not str(log.get(champ, "")).strip():
            erreurs.append(f"ligne {num} : champ « {champ} » vide")
    ts = str(log.get("timestamp", ""))
    if ts:
        try:
            datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            erreurs.append(f"ligne {num} : date invalide « {ts[:30]} » (format ISO 8601 attendu)")
    level = str(log.get("level", "")).upper()
    if level and level not in NIVEAUX:
        erreurs.append(f"ligne {num} : niveau « {level} » inconnu")
    for champ, conv in (("status_code", int), ("response_time", float)):
        val = log.get(champ, "")
        if val not in ("", None):
            try:
                conv(val)
            except (TypeError, ValueError):
                erreurs.append(f"ligne {num} : « {champ} » doit être un nombre")
    return erreurs


def valider_csv(texte):
    lignes = texte.split("\n")
    entete = lignes[0].strip() if lignes else ""
    if ";" in entete and "," not in entete:
        return 0, ["séparateur « ; » détecté (fichier enregistré par Excel ?) : "
                   "le séparateur attendu est la virgule"]
    if [c.strip() for c in entete.split(",")] != COLONNES:
        return 0, ["en-tête incorrect. Attendu : " + ",".join(COLONNES)]

    erreurs, nb = [], 0
    for num, row in enumerate(csv.reader(io.StringIO(texte)), start=1):
        if num == 1 or not any(row):          # en-tête ou ligne vide
            continue
        nb += 1
        if len(row) != len(COLONNES):
            erreurs.append(f"ligne {num} : {len(row)} colonnes au lieu de {len(COLONNES)}")
        else:
            erreurs += _verifier_log(dict(zip(COLONNES, row)), num)
        if len(erreurs) >= MAX_ERREURS:
            break
    return nb, erreurs


def valider_json(texte):
    """Format NDJSON : un objet JSON par ligne (comme le générateur)."""
    erreurs, nb = [], 0
    for num, ligne in enumerate(texte.split("\n"), start=1):
        if not ligne.strip():
            continue
        nb += 1
        try:
            log = json.loads(ligne)
        except json.JSONDecodeError:
            erreurs.append(f"ligne {num} : JSON invalide (un objet JSON par ligne attendu)")
        else:
            if not isinstance(log, dict):
                erreurs.append(f"ligne {num} : un objet {{...}} est attendu")
            else:
                erreurs += _verifier_log(log, num)
        if len(erreurs) >= MAX_ERREURS:
            break
    return nb, erreurs


def valider(contenu: bytes, extension: str):
    """Renvoie (texte normalisé, nombre de lignes, erreurs)."""
    try:
        texte = contenu.decode("utf-8-sig")        # -sig : ignore le BOM ajouté par Excel
    except UnicodeDecodeError:
        return "", 0, ["le fichier doit être encodé en UTF-8"]
    texte = texte.replace("\r\n", "\n").replace("\r", "\n")   # fins de ligne Windows
    if not texte.strip():
        return "", 0, ["le fichier est vide"]
    nb, erreurs = valider_csv(texte) if extension == "csv" else valider_json(texte)
    if nb == 0 and not erreurs:
        erreurs = ["aucune ligne de log dans le fichier"]
    if not texte.endswith("\n"):
        texte += "\n"                               # Logstash lit la dernière ligne
    return texte, nb, erreurs
