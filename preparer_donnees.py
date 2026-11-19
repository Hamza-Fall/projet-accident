"""
preparer_donnees.py : nettoie les fichiers bruts BAAC et ne garde que l'Île-de-France.

Entrée  : data/raw/<année>/caract-<année>.csv, lieux-…, vehicules-…, usagers-…   (non versionnés)
Sortie  : data/accidents.csv, data/lieux.csv, data/vehicules.csv, data/usagers.csv (versionnés, légers)

À lancer une seule fois en local :   python preparer_donnees.py
Source des données : ONISR / Ministère de l'Intérieur, « Bases de données annuelles des accidents corporels de la
circulation routière » (data.gouv.fr), licence ouverte.
"""
import glob
import os

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "data", "raw")
SORTIE = os.path.join(BASE, "data")

ANNEES = [2022, 2023, 2024]
DEP_IDF = ["75", "77", "78", "91", "92", "93", "94", "95"]          # Île-de-France
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 48.0, 49.4, 1.3, 3.7           # cadre englobant l'Île-de-France
MIN_ACCIDENTS_PAR_AN = 3000                                          # garde-fou : si le filtre ne garde presque rien, on s'arrête

bilan = []        # lignes du compte rendu de nettoyage


# --------------------------------------------------------------------------- lecture
def trouver(annee, prefixe):
    chemins = glob.glob(os.path.join(RAW, str(annee), f"{prefixe}*{annee}*.csv"))
    if len(chemins) != 1:
        raise FileNotFoundError(f"Fichier '{prefixe}…{annee}.csv' introuvable (ou ambigu) dans {os.path.join(RAW, str(annee))}")
    return chemins[0]


def lire_csv(chemin, cles):
    """Lit un CSV BAAC en texte brut. Teste ';' puis ',' (et utf-8 puis latin-1) jusqu'à trouver la colonne clé."""
    for enc in ("utf-8-sig", "latin-1"):
        for sep in (";", ","):
            try:
                df = pd.read_csv(chemin, sep=sep, encoding=enc, dtype=str)
            except UnicodeDecodeError:
                break
            df.columns = [c.strip() for c in df.columns]
            if any(c in df.columns for c in cles):
                return df
    raise ValueError(f"Impossible de lire {chemin} (colonne clé {cles} absente)")


# --------------------------------------------------------------------------- nettoyage de colonnes
def chiffres(s):
    """Identifiant : ne garde que les chiffres (supprime espaces, espaces insécables, etc.)."""
    return s.str.replace(r"\D+", "", regex=True).replace("", pd.NA)


def nombre(s):
    return pd.to_numeric(s.str.strip(), errors="coerce")


def code(s):
    """Variable codée : entier, -1 (« non renseigné ») si absent ou illisible."""
    return nombre(s).fillna(-1).astype(int)


def entier_ou_vide(s):
    return nombre(s).round().astype("Int64")


# --------------------------------------------------------------------------- une table après l'autre
def preparer_accidents(annee):
    df = lire_csv(trouver(annee, "caract"), ("Num_Acc", "Accident_Id"))
    df = df.rename(columns={"Accident_Id": "Num_Acc"})          # 2022 : colonne clé renommée
    n_france = len(df)
    df["id_accident"] = chiffres(df["Num_Acc"])
    df["dep"] = df["dep"].str.strip()
    df = df[df["dep"].isin(DEP_IDF) & df["id_accident"].notna()].copy()
    n_idf = len(df)
    if n_idf < MIN_ACCIDENTS_PAR_AN:
        raise ValueError(f"{annee} : seulement {n_idf} accidents en Île-de-France sur {n_france} (filtre sur 'dep' à vérifier)")

    # date et heure
    hm = df["hrmn"].str.extract(r"(\d{1,2}):(\d{2})")
    dt = pd.to_datetime(dict(year=nombre(df["an"]), month=nombre(df["mois"]), day=nombre(df["jour"]),
                             hour=nombre(hm[0]), minute=nombre(hm[1])), errors="coerce")
    n_date_ko = int(dt.isna().sum())
    df = df[dt.notna()].copy()
    dt = dt[dt.notna()]
    df["date_heure"] = dt.dt.strftime("%Y-%m-%d %H:%M:%S")
    df["annee"], df["mois"], df["heure"], df["jour_semaine"] = dt.dt.year, dt.dt.month, dt.dt.hour, dt.dt.day_of_week

    # coordonnées : virgule décimale, valeurs hors Île-de-France ou absentes -> vides (l'accident est conservé)
    lat = nombre(df["lat"].str.replace(",", ".", regex=False))
    lon = nombre(df["long"].str.replace(",", ".", regex=False))
    valide = lat.between(LAT_MIN, LAT_MAX) & lon.between(LON_MIN, LON_MAX)
    n_gps_ko = int((~valide).sum())
    df["latitude"], df["longitude"] = lat.where(valide), lon.where(valide)

    df["code_insee"] = df["com"].str.strip().str.zfill(5)
    df["luminosite"], df["agglomeration"], df["intersection"] = code(df["lum"]), code(df["agg"]), code(df["int"])
    df["meteo"], df["collision"] = code(df["atm"]), code(df["col"])
    df["adresse"] = df["adr"].str.strip()
    bilan.append((annee, "accidents", n_france, n_idf, f"{n_date_ko} date(s) invalide(s) écartée(s) ; {n_gps_ko} GPS invalide(s) ou absent(s)"))
    return df[["id_accident", "date_heure", "annee", "mois", "heure", "jour_semaine", "latitude", "longitude",
               "code_insee", "luminosite", "agglomeration", "intersection", "meteo", "collision", "adresse"]]


def preparer_lieux(annee, ids):
    df = lire_csv(trouver(annee, "lieux"), ("Num_Acc",))
    n_brut = len(df)
    df["id_accident"] = chiffres(df["Num_Acc"])
    df = df[df["id_accident"].isin(ids)]
    n_idf = len(df)
    df = df.drop_duplicates("id_accident", keep="first").copy()            # 2023-2024 : une ligne par voie -> on garde la première
    df["categorie_route"], df["regime_circulation"] = code(df["catr"]), code(df["circ"])
    df["etat_surface"], df["infrastructure"], df["situation"] = code(df["surf"]), code(df["infra"]), code(df["situ"])
    df["numero_voie"] = df["voie"].str.strip()
    nbv, vma = nombre(df["nbv"]), nombre(df["vma"])
    df["nb_voies"] = nbv.where(nbv.between(1, 20)).round().astype("Int64")
    df["vitesse_max"] = vma.where(vma.between(5, 130)).round().astype("Int64")
    bilan.append((annee, "lieux", n_brut, len(df), f"{n_idf - len(df)} ligne(s) supplémentaire(s) par accident écartée(s)"))
    return df[["id_accident", "categorie_route", "numero_voie", "regime_circulation", "nb_voies",
               "etat_surface", "infrastructure", "situation", "vitesse_max"]]


def preparer_vehicules(annee, ids):
    df = lire_csv(trouver(annee, "vehicules"), ("Num_Acc",))
    n_brut = len(df)
    df["id_accident"], df["id_vehicule"] = chiffres(df["Num_Acc"]), chiffres(df["id_vehicule"])
    df = df[df["id_accident"].isin(ids) & df["id_vehicule"].notna()].drop_duplicates("id_vehicule").copy()
    df["num_veh"] = df["num_veh"].str.strip()
    df["categorie_vehicule"], df["obstacle_fixe"], df["obstacle_mobile"] = code(df["catv"]), code(df["obs"]), code(df["obsm"])
    df["point_choc"], df["manoeuvre"], df["motorisation"] = code(df["choc"]), code(df["manv"]), code(df["motor"])
    bilan.append((annee, "vehicules", n_brut, len(df), ""))
    return df[["id_vehicule", "id_accident", "num_veh", "categorie_vehicule", "obstacle_fixe", "obstacle_mobile",
               "point_choc", "manoeuvre", "motorisation"]]


def preparer_usagers(annee, ids, ids_vehicules):
    df = lire_csv(trouver(annee, "usagers"), ("Num_Acc",))
    n_brut = len(df)
    df["id_accident"] = chiffres(df["Num_Acc"])
    df["id_usager"], df["id_vehicule"] = chiffres(df["id_usager"]), chiffres(df["id_vehicule"])
    df = df[df["id_accident"].isin(ids) & df["id_usager"].notna()].drop_duplicates("id_usager").copy()
    orphelins = int((df["id_vehicule"].notna() & ~df["id_vehicule"].isin(ids_vehicules)).sum())
    df["id_vehicule"] = df["id_vehicule"].where(df["id_vehicule"].isin(ids_vehicules))      # véhicule inconnu -> vide
    df["categorie_usager"], df["gravite"], df["sexe"] = code(df["catu"]), code(df["grav"]), code(df["sexe"])
    df["trajet"], df["equipement_securite"] = code(df["trajet"]), code(df["secu1"])
    naiss = nombre(df["an_nais"])
    df["annee_naissance"] = naiss.where(naiss.between(1900, annee)).round().astype("Int64")
    bilan.append((annee, "usagers", n_brut, len(df), f"{orphelins} usager(s) rattaché(s) à un véhicule inconnu (lien vidé)"))
    return df[["id_usager", "id_accident", "id_vehicule", "categorie_usager", "gravite", "sexe",
               "annee_naissance", "trajet", "equipement_securite"]]


def main():
    tables = {"accidents": [], "lieux": [], "vehicules": [], "usagers": []}
    for annee in ANNEES:
        acc = preparer_accidents(annee)
        ids = set(acc["id_accident"])
        veh = preparer_vehicules(annee, ids)
        tables["accidents"].append(acc)
        tables["lieux"].append(preparer_lieux(annee, ids))
        tables["vehicules"].append(veh)
        tables["usagers"].append(preparer_usagers(annee, ids, set(veh["id_vehicule"])))

    os.makedirs(SORTIE, exist_ok=True)
    cles = {"accidents": "id_accident", "lieux": "id_accident", "vehicules": "id_vehicule", "usagers": "id_usager"}
    print("\nBilan du nettoyage (lignes brutes France -> lignes conservées Île-de-France)")
    for annee, table, brut, garde, remarque in bilan:
        print(f"  {annee}  {table:<10} {brut:>8} -> {garde:>7}   {remarque}")
    print()
    for nom, morceaux in tables.items():
        df = pd.concat(morceaux, ignore_index=True)
        doublons = int(df.duplicated(cles[nom]).sum())
        if doublons:
            print(f"  attention : {doublons} identifiant(s) en double dans {nom}, doublons supprimés")
            df = df.drop_duplicates(cles[nom])
        df.to_csv(os.path.join(SORTIE, f"{nom}.csv"), index=False)
        print(f"  data/{nom}.csv : {len(df)} lignes")
    print("\nTerminé. Étape suivante : python init_db.py")


if __name__ == "__main__":
    main()