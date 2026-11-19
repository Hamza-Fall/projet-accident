"""
telecharger_communes.py : récupère le nom et la population des communes d'Île-de-France.

Source : API Géo (geo.api.gouv.fr), Etalab, licence ouverte. Pas de clé nécessaire.
À lancer une seule fois en local :   python telecharger_communes.py
Résultat : data/communes.csv (colonnes code_insee, nom, population), lu ensuite par init_db.py.

Paris est une « commune » (75056) découpée en 20 arrondissements (75101 à 75120). Les accidents de la base BAAC
portent le code de l'arrondissement : on récupère donc aussi les arrondissements.
"""
import json
import os
import time
import urllib.request

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
SORTIE = os.path.join(BASE, "data", "communes.csv")
API = "https://geo.api.gouv.fr"
DEPARTEMENTS = ["75", "77", "78", "91", "92", "93", "94", "95"]
PARIS = "75056"


def appeler(url, essais=3):
    erreur = None
    for i in range(essais):
        try:
            requete = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "projet-accidents-etudiant"})
            with urllib.request.urlopen(requete, timeout=30) as reponse:
                return json.loads(reponse.read().decode("utf-8"))
        except Exception as e:                       # réseau coupé, erreur serveur...
            erreur = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"Échec de l'appel {url} : {erreur}")


def main():
    lignes = []
    for dep in DEPARTEMENTS:
        communes = appeler(f"{API}/departements/{dep}/communes?fields=code,nom,population")
        print(f"  département {dep} : {len(communes)} communes")
        lignes += communes

    arrondissements = appeler(f"{API}/communes?codeParent={PARIS}&type=arrondissement-municipal&fields=code,nom,population")
    print(f"  Paris : {len(arrondissements)} arrondissements")
    lignes += arrondissements

    df = pd.DataFrame(lignes).rename(columns={"code": "code_insee"})
    df = df[["code_insee", "nom", "population"]].drop_duplicates("code_insee")
    os.makedirs(os.path.dirname(SORTIE), exist_ok=True)
    df.to_csv(SORTIE, index=False)

    sans_pop = int(df["population"].isna().sum())
    print(f"\n{len(df)} communes et arrondissements écrits dans data/communes.csv")
    if len(arrondissements) != 20:
        print(f"  attention : {len(arrondissements)} arrondissements reçus au lieu de 20")
    if sans_pop:
        print(f"  attention : {sans_pop} ligne(s) sans population (taux par habitant impossible pour elles)")
    hors_paris = df[df["code_insee"] != PARIS]["population"].sum()
    print(f"  population cumulée (hors commune « Paris » globale, pour ne pas la compter deux fois) : {int(hors_paris):,}".replace(",", " "))


if __name__ == "__main__":
    main()
