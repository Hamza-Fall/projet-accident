"""
db.py : accès aux données (SQLite) pour le dashboard.

Règle : aucune connexion n'est gardée ouverte. Chaque requête ouvre sa connexion puis la ferme (voir `connexion()`).
"""
import os
import sqlite3
from contextlib import contextmanager

import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accidents.db")


@contextmanager
def connexion():
    """Ouvre une connexion SQLite et la ferme toujours à la sortie."""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Base introuvable ({DB_PATH}). Lancez d'abord : python init_db.py")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def requete(sql, params=()):
    """Exécute une requête SELECT et renvoie un DataFrame (connexion ouverte puis fermée)."""
    with connexion() as conn:
        return pd.read_sql_query(sql, conn, params=params)


# --------------------------------------------------------------------------- requêtes de contrôle du chargement
def comptes_tables():
    """Nombre de lignes de chaque table."""
    tables = ["communes", "accidents", "lieux", "vehicules", "usagers", "libelles"]
    sql = " UNION ALL ".join(f"SELECT '{t}' AS table_, COUNT(*) AS lignes FROM {t}" for t in tables)
    return requete(sql)


def accidents_par_annee():
    """Nombre d'accidents, d'usagers, de tués et de blessés hospitalisés par année."""
    return requete("""
        SELECT a.annee,
               COUNT(DISTINCT a.id_accident)                    AS accidents,
               COUNT(u.id_usager)                               AS usagers,
               SUM(CASE WHEN u.gravite = 2 THEN 1 ELSE 0 END)   AS tues,
               SUM(CASE WHEN u.gravite = 3 THEN 1 ELSE 0 END)   AS blesses_hospitalises
        FROM accidents a LEFT JOIN usagers u ON u.id_accident = a.id_accident
        GROUP BY a.annee ORDER BY a.annee
    """)


def usagers_par_gravite():
    """Répartition des usagers par gravité (avec le libellé, grâce à la table libelles)."""
    return requete("""
        SELECT l.libelle AS gravite, COUNT(*) AS usagers
        FROM usagers u JOIN libelles l ON l.variable = 'gravite' AND l.code = u.gravite
        GROUP BY l.libelle ORDER BY usagers DESC
    """)


def communes_sans_nom():
    """Communes présentes dans les accidents mais sans nom (absentes de data/communes.csv), avec leur nombre d'accidents."""
    return requete("""
        SELECT c.code_insee, COUNT(a.id_accident) AS accidents
        FROM communes c JOIN accidents a ON a.code_insee = c.code_insee
        WHERE c.nom IS NULL
        GROUP BY c.code_insee ORDER BY accidents DESC
    """)


# =========================================================================== requêtes du dashboard
TYPES_USAGERS = ["Piéton", "Vélo / trottinette", "Deux-roues motorisé", "Voiture", "Utilitaire / poids lourd", "Autre"]

# Type d'usager : un piéton est identifié par sa catégorie, les autres par la catégorie du véhicule qu'ils occupent.
_TYPE_USAGER = """CASE WHEN {u}.categorie_usager = 3 THEN 'Piéton'
                        WHEN {v}.categorie_vehicule IN (1, 50, 60, 80) THEN 'Vélo / trottinette'
                        WHEN {v}.categorie_vehicule IN (2, 30, 31, 32, 33, 34, 41, 42, 43) THEN 'Deux-roues motorisé'
                        WHEN {v}.categorie_vehicule IN (3, 7) THEN 'Voiture'
                        WHEN {v}.categorie_vehicule IN (10, 13, 14, 15, 16, 17) THEN 'Utilitaire / poids lourd'
                        ELSE 'Autre' END"""

# Accidents « graves » : au moins un usager tué (gravité 2) ou hospitalisé (3). a_tue = 1 si au moins un tué.
_GRAVES = "(SELECT id_accident, MAX(gravite = 2) AS a_tue FROM usagers WHERE gravite IN (2, 3) GROUP BY id_accident)"


def _filtre(annees, deps, graves_seulement, usager):
    """Table temporaire `acc` : les accidents qui respectent les filtres du dashboard (+ paramètres SQL)."""
    conditions = [f"a.annee IN ({','.join('?' * len(annees))})", f"c.departement IN ({','.join('?' * len(deps))})"]
    params = list(annees) + list(deps)
    if graves_seulement:
        conditions.append("EXISTS (SELECT 1 FROM usagers ug WHERE ug.id_accident = a.id_accident AND ug.gravite IN (2, 3))")
    if usager and usager != "Tous":
        conditions.append("EXISTS (SELECT 1 FROM usagers u2 LEFT JOIN vehicules v2 ON v2.id_vehicule = u2.id_vehicule "
                          "WHERE u2.id_accident = a.id_accident AND " + _TYPE_USAGER.format(u="u2", v="v2") + " = ?)")
        params.append(usager)
    cte = ("acc AS (SELECT a.id_accident, a.annee, a.mois, a.jour_semaine, a.heure, a.latitude, a.longitude, "
           "a.code_insee, a.adresse FROM accidents a JOIN communes c ON c.code_insee = a.code_insee WHERE "
           + " AND ".join(conditions) + ")")
    return cte, params


def indicateurs(annees, deps, graves_seulement=False, usager="Tous"):
    """Chiffres clés : accidents, accidents graves, usagers, tués, blessés hospitalisés."""
    cte, params = _filtre(annees, deps, graves_seulement, usager)
    return requete(f"""
        WITH {cte}
        SELECT (SELECT COUNT(*) FROM acc) AS accidents,
               (SELECT COUNT(*) FROM acc JOIN {_GRAVES} g ON g.id_accident = acc.id_accident) AS accidents_graves,
               COUNT(u.id_usager) AS usagers,
               COALESCE(SUM(u.gravite = 2), 0) AS tues,
               COALESCE(SUM(u.gravite = 3), 0) AS hospitalises
        FROM acc LEFT JOIN usagers u ON u.id_accident = acc.id_accident
    """, params).iloc[0]


def accidents_par_mois(annees, deps, graves_seulement=False, usager="Tous"):
    cte, params = _filtre(annees, deps, graves_seulement, usager)
    return requete(f"WITH {cte} SELECT annee, mois, COUNT(*) AS accidents FROM acc GROUP BY annee, mois ORDER BY annee, mois", params)


def accidents_jour_heure(annees, deps, graves_seulement=False, usager="Tous"):
    cte, params = _filtre(annees, deps, graves_seulement, usager)
    return requete(f"WITH {cte} SELECT jour_semaine, heure, COUNT(*) AS accidents FROM acc GROUP BY jour_semaine, heure", params)


def gravite_par_usager(annees, deps, graves_seulement=False, usager="Tous"):
    """Nombre d'usagers par type d'usager et par gravité (libellé issu de la table libelles)."""
    cte, params = _filtre(annees, deps, graves_seulement, usager)
    return requete(f"""
        WITH {cte}
        SELECT {_TYPE_USAGER.format(u='u', v='v')} AS type_usager,
               COALESCE(l.libelle, 'Non renseigné') AS gravite,
               COUNT(*) AS usagers
        FROM acc
        JOIN usagers u ON u.id_accident = acc.id_accident
        LEFT JOIN vehicules v ON v.id_vehicule = u.id_vehicule
        LEFT JOIN libelles l ON l.variable = 'gravite' AND l.code = u.gravite
        GROUP BY type_usager, gravite
    """, params)


def communes_accidents(annees, deps, graves_seulement=False, usager="Tous"):
    """Par commune : accidents, accidents graves et population (pour calculer des taux par habitant)."""
    cte, params = _filtre(annees, deps, graves_seulement, usager)
    return requete(f"""
        WITH {cte}
        SELECT acc.code_insee AS code_insee,
               COALESCE(c.nom, acc.code_insee) AS commune,
               c.population AS population,
               COUNT(*) AS accidents,
               COUNT(g.id_accident) AS accidents_graves
        FROM acc
        JOIN communes c ON c.code_insee = acc.code_insee
        LEFT JOIN {_GRAVES} g ON g.id_accident = acc.id_accident
        GROUP BY acc.code_insee, commune, c.population
    """, params)


def points_noirs(annees, deps, graves_seulement=False, usager="Tous", limite=300):
    """Lieux (coordonnées arrondies à ~100 m) classés par nombre d'accidents graves puis d'accidents."""
    cte, params = _filtre(annees, deps, graves_seulement, usager)
    return requete(f"""
        WITH {cte}
        SELECT ROUND(acc.latitude, 3) AS lat, ROUND(acc.longitude, 3) AS lon,
               COUNT(*) AS accidents,
               COUNT(g.id_accident) AS graves,
               COALESCE(SUM(g.a_tue), 0) AS tues,
               MAX(acc.adresse) AS lieu,
               MAX(COALESCE(c.nom, acc.code_insee)) AS commune
        FROM acc
        JOIN communes c ON c.code_insee = acc.code_insee
        LEFT JOIN {_GRAVES} g ON g.id_accident = acc.id_accident
        WHERE acc.latitude IS NOT NULL
        GROUP BY lat, lon
        ORDER BY graves DESC, accidents DESC
        LIMIT ?
    """, list(params) + [limite])