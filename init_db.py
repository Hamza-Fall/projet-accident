"""
init_db.py : crée la base SQLite `accidents.db` et la remplit à partir des CSV du dossier data/.

Usage (une seule commande) :   python init_db.py
La base est entièrement recréée à chaque exécution ; elle n'est jamais versionnée.
"""
import os
import sqlite3
import time

import pandas as pd

import db

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

SCHEMA = """
CREATE TABLE communes (
    code_insee   TEXT PRIMARY KEY,
    departement  TEXT NOT NULL,
    nom          TEXT,                  -- renseigné si data/communes.csv existe
    population   INTEGER                -- idem (pour calculer des taux par habitant)
);

CREATE TABLE accidents (
    id_accident   TEXT PRIMARY KEY,
    date_heure    TEXT NOT NULL,        -- 'AAAA-MM-JJ HH:MM:SS'
    annee         INTEGER NOT NULL,
    mois          INTEGER NOT NULL,
    heure         INTEGER NOT NULL,
    jour_semaine  INTEGER NOT NULL,     -- 0 = lundi ... 6 = dimanche
    latitude      REAL,                 -- vide si GPS absent ou invalide
    longitude     REAL,
    code_insee    TEXT NOT NULL REFERENCES communes(code_insee),
    luminosite    INTEGER,
    agglomeration INTEGER,
    intersection  INTEGER,
    meteo         INTEGER,
    collision     INTEGER,
    adresse       TEXT
);

CREATE TABLE lieux (
    id_accident        TEXT PRIMARY KEY REFERENCES accidents(id_accident),
    categorie_route    INTEGER,
    numero_voie        TEXT,
    regime_circulation INTEGER,
    nb_voies           INTEGER,
    etat_surface       INTEGER,
    infrastructure     INTEGER,
    situation          INTEGER,
    vitesse_max        INTEGER
);

CREATE TABLE vehicules (
    id_vehicule        TEXT PRIMARY KEY,
    id_accident        TEXT NOT NULL REFERENCES accidents(id_accident),
    num_veh            TEXT,
    categorie_vehicule INTEGER,
    obstacle_fixe      INTEGER,
    obstacle_mobile    INTEGER,
    point_choc         INTEGER,
    manoeuvre          INTEGER,
    motorisation       INTEGER
);

CREATE TABLE usagers (
    id_usager           TEXT PRIMARY KEY,
    id_accident         TEXT NOT NULL REFERENCES accidents(id_accident),
    id_vehicule         TEXT REFERENCES vehicules(id_vehicule),   -- les piétons sont rattachés au véhicule qui les a heurtés
    categorie_usager    INTEGER,
    gravite             INTEGER,
    sexe                INTEGER,
    annee_naissance     INTEGER,
    trajet              INTEGER,
    equipement_securite INTEGER
);

CREATE TABLE libelles (                 -- table de référence : sens des codes de la base BAAC
    variable TEXT NOT NULL,
    code     INTEGER NOT NULL,
    libelle  TEXT NOT NULL,
    PRIMARY KEY (variable, code)
);

CREATE INDEX idx_accidents_date     ON accidents(date_heure);
CREATE INDEX idx_accidents_commune  ON accidents(code_insee);
CREATE INDEX idx_vehicules_accident ON vehicules(id_accident);
CREATE INDEX idx_usagers_accident   ON usagers(id_accident);
CREATE INDEX idx_usagers_vehicule   ON usagers(id_vehicule);
"""

# Libellés issus de la documentation officielle de l'ONISR (« Description des bases de données annuelles »)
LIBELLES = {
    "jour_semaine": {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi", 4: "Vendredi", 5: "Samedi", 6: "Dimanche"},
    "luminosite": {1: "Plein jour", 2: "Crépuscule ou aube", 3: "Nuit sans éclairage public",
                   4: "Nuit avec éclairage public non allumé", 5: "Nuit avec éclairage public allumé"},
    "agglomeration": {1: "Hors agglomération", 2: "En agglomération"},
    "intersection": {1: "Hors intersection", 2: "Intersection en X", 3: "Intersection en T", 4: "Intersection en Y",
                     5: "Intersection à plus de 4 branches", 6: "Giratoire", 7: "Place", 8: "Passage à niveau",
                     9: "Autre intersection"},
    "meteo": {1: "Normale", 2: "Pluie légère", 3: "Pluie forte", 4: "Neige - grêle", 5: "Brouillard - fumée",
              6: "Vent fort - tempête", 7: "Temps éblouissant", 8: "Temps couvert", 9: "Autre"},
    "collision": {1: "Deux véhicules - frontale", 2: "Deux véhicules - par l'arrière", 3: "Deux véhicules - par le côté",
                  4: "Trois véhicules et plus - en chaîne", 5: "Trois véhicules et plus - collisions multiples",
                  6: "Autre collision", 7: "Sans collision"},
    "categorie_route": {1: "Autoroute", 2: "Route nationale", 3: "Route départementale", 4: "Voie communale",
                        5: "Hors réseau public", 6: "Parc de stationnement", 7: "Route de métropole urbaine", 9: "Autre"},
    "regime_circulation": {1: "À sens unique", 2: "Bidirectionnelle", 3: "À chaussées séparées", 4: "Voies d'affectation variable"},
    "etat_surface": {1: "Normale", 2: "Mouillée", 3: "Flaques", 4: "Inondée", 5: "Enneigée", 6: "Boue", 7: "Verglacée",
                     8: "Corps gras - huile", 9: "Autre"},
    "infrastructure": {0: "Aucun", 1: "Souterrain - tunnel", 2: "Pont - autopont", 3: "Bretelle d'échangeur ou de raccordement",
                       4: "Voie ferrée", 5: "Carrefour aménagé", 6: "Zone piétonne", 7: "Zone de péage", 8: "Chantier", 9: "Autres"},
    "situation": {0: "Aucun", 1: "Sur chaussée", 2: "Sur bande d'arrêt d'urgence", 3: "Sur accotement", 4: "Sur trottoir",
                  5: "Sur piste cyclable", 6: "Sur autre voie spéciale", 8: "Autres"},
    "categorie_vehicule": {0: "Indéterminable", 1: "Bicyclette", 2: "Cyclomoteur < 50 cm3", 3: "Voiturette", 7: "VL seul",
                           10: "VU seul (1,5 T à 3,5 T)", 13: "PL seul 3,5 T à 7,5 T", 14: "PL seul > 7,5 T",
                           15: "PL > 3,5 T + remorque", 16: "Tracteur routier seul", 17: "Tracteur routier + semi-remorque",
                           20: "Engin spécial", 21: "Tracteur agricole", 30: "Scooter < 50 cm3",
                           31: "Motocyclette 50 à 125 cm3", 32: "Scooter 50 à 125 cm3", 33: "Motocyclette > 125 cm3",
                           34: "Scooter > 125 cm3", 35: "Quad léger", 36: "Quad lourd", 37: "Autobus", 38: "Autocar",
                           39: "Train", 40: "Tramway", 41: "3RM <= 50 cm3", 42: "3RM 50 à 125 cm3", 43: "3RM > 125 cm3",
                           50: "EDP à moteur", 60: "EDP sans moteur", 80: "VAE", 99: "Autre véhicule"},
    "obstacle_fixe": {0: "Sans objet", 1: "Véhicule en stationnement", 2: "Arbre", 3: "Glissière métallique",
                      4: "Glissière béton", 5: "Autre glissière", 6: "Bâtiment, mur, pile de pont",
                      7: "Support de signalisation verticale", 8: "Poteau", 9: "Mobilier urbain", 10: "Parapet",
                      11: "Îlot, refuge, borne haute", 12: "Bordure de trottoir", 13: "Fossé, talus, paroi rocheuse",
                      14: "Autre obstacle fixe sur chaussée", 15: "Autre obstacle fixe sur trottoir ou accotement",
                      16: "Sortie de chaussée sans obstacle", 17: "Buse - tête d'aqueduc"},
    "obstacle_mobile": {0: "Aucun", 1: "Piéton", 2: "Véhicule", 4: "Véhicule sur rail", 5: "Animal domestique",
                        6: "Animal sauvage", 9: "Autre"},
    "point_choc": {0: "Aucun", 1: "Avant", 2: "Avant droit", 3: "Avant gauche", 4: "Arrière", 5: "Arrière droit",
                   6: "Arrière gauche", 7: "Côté droit", 8: "Côté gauche", 9: "Chocs multiples (tonneaux)"},
    "motorisation": {0: "Inconnue", 1: "Hydrocarbures", 2: "Hybride électrique", 3: "Électrique", 4: "Hydrogène",
                     5: "Humaine", 6: "Autre"},
    "categorie_usager": {1: "Conducteur", 2: "Passager", 3: "Piéton"},
    "gravite": {1: "Indemne", 2: "Tué", 3: "Blessé hospitalisé", 4: "Blessé léger"},
    "sexe": {1: "Masculin", 2: "Féminin"},
    "trajet": {0: "Non renseigné", 1: "Domicile - travail", 2: "Domicile - école", 3: "Courses - achats",
               4: "Utilisation professionnelle", 5: "Promenade - loisirs", 9: "Autre"},
    "equipement_securite": {0: "Aucun équipement", 1: "Ceinture", 2: "Casque", 3: "Dispositif enfants",
                            4: "Gilet réfléchissant", 5: "Airbag (2RM/3RM)", 6: "Gants (2RM/3RM)",
                            7: "Gants + airbag (2RM/3RM)", 8: "Non déterminable", 9: "Autre"},
}
VARIABLES_AVEC_NON_RENSEIGNE = [v for v in LIBELLES if v != "jour_semaine"]       # -1 = « Non renseigné » dans la source

ORDRE_CHARGEMENT = [("accidents", "accidents.csv"), ("lieux", "lieux.csv"), ("vehicules", "vehicules.csv"), ("usagers", "usagers.csv")]


def lire(nom):
    chemin = os.path.join(DATA, nom)
    if not os.path.exists(chemin):
        raise FileNotFoundError(f"{chemin} introuvable. Lancez d'abord : python preparer_donnees.py")
    return pd.read_csv(chemin, dtype={"id_accident": str, "id_vehicule": str, "id_usager": str, "code_insee": str,
                                      "numero_voie": str, "num_veh": str, "adresse": str})


def inserer(conn, table, df):
    df = df.astype(object).where(df.notna(), None)                 # valeurs absentes -> NULL
    colonnes = ", ".join(df.columns)
    marques = ", ".join("?" * len(df.columns))
    conn.executemany(f"INSERT INTO {table} ({colonnes}) VALUES ({marques})", df.itertuples(index=False, name=None))


def construire_base(afficher=True):
    t0 = time.time()
    temporaire = db.DB_PATH + ".tmp"
    if os.path.exists(temporaire):
        os.remove(temporaire)
    donnees = {table: lire(nom) for table, nom in ORDRE_CHARGEMENT}

    # communes : celles qui apparaissent dans les accidents ; nom et population viennent de data/communes.csv s'il existe
    communes = pd.DataFrame({"code_insee": sorted(donnees["accidents"]["code_insee"].unique())})
    communes["departement"] = communes["code_insee"].str[:2]
    chemin_communes = os.path.join(DATA, "communes.csv")
    if os.path.exists(chemin_communes):
        ref = pd.read_csv(chemin_communes, dtype={"code_insee": str})[["code_insee", "nom", "population"]]
        communes = communes.merge(ref, on="code_insee", how="left")
    else:
        communes["nom"], communes["population"] = None, None

    conn = sqlite3.connect(temporaire)
    try:
        conn.execute("PRAGMA journal_mode = OFF")                   # base jetable et régénérable : on privilégie la vitesse
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        inserer(conn, "communes", communes[["code_insee", "departement", "nom", "population"]])
        for table, _ in ORDRE_CHARGEMENT:
            inserer(conn, table, donnees[table])
        lignes = [(variable, code, libelle) for variable, d in LIBELLES.items() for code, libelle in d.items()]
        lignes += [(variable, -1, "Non renseigné") for variable in VARIABLES_AVEC_NON_RENSEIGNE]
        conn.executemany("INSERT INTO libelles (variable, code, libelle) VALUES (?,?,?)", lignes)
        conn.commit()
    finally:
        conn.close()
    os.replace(temporaire, db.DB_PATH)                              # la nouvelle base remplace l'ancienne d'un seul coup

    # ---- vérifications : intégrité et cohérence avec les CSV
    with db.connexion() as conn:
        orphelins = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert not orphelins, f"Clés étrangères invalides : {orphelins[:5]}"
    comptes = db.comptes_tables().set_index("table_")["lignes"]
    for table, _ in ORDRE_CHARGEMENT:
        assert comptes[table] == len(donnees[table]), f"{table} : {comptes[table]} lignes en base, {len(donnees[table])} dans le CSV"
    tues_csv = int((donnees["usagers"]["gravite"] == 2).sum())
    tues_sql = int(db.requete("SELECT COUNT(*) AS n FROM usagers WHERE gravite = 2")["n"].iloc[0])
    assert tues_csv == tues_sql, "Nombre de tués différent entre le CSV et la base"

    if afficher:
        print("Vérification OK : clés étrangères valides, nombre de lignes et de tués identiques entre CSV et base.")
        print(f"Base créée : {db.DB_PATH}  ({time.time() - t0:.0f} s)")
    return db.DB_PATH


def main():
    construire_base()
    print("\nLignes par table :")
    print(db.comptes_tables().to_string(index=False))
    print("\nRequête 1 – Accidents, usagers, tués et blessés hospitalisés par année :")
    print(db.accidents_par_annee().to_string(index=False))
    print("\nRequête 2 – Répartition des usagers par gravité :")
    print(db.usagers_par_gravite().to_string(index=False))

    sans_nom = db.communes_sans_nom()
    if os.path.exists(os.path.join(DATA, "communes.csv")):
        total = int(db.requete("SELECT COUNT(*) AS n FROM accidents")["n"].iloc[0])
        print(f"\nCommunes sans nom : {len(sans_nom)} (soit {sans_nom['accidents'].sum()} accidents sur {total})")
        if len(sans_nom):
            print(sans_nom.head(5).to_string(index=False))
    else:
        print("\nNoms et populations des communes non chargés (lancez python telecharger_communes.py, puis python init_db.py).")


if __name__ == "__main__":
    main()