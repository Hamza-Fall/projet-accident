import glob
import os
import sys

import pandas as pd

DOSSIER = "data/raw"
SORTIE = "inspection.txt"


def lire_echantillon(chemin):
    for enc in ("utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(chemin, sep=None, engine="python", encoding=enc, dtype=str, nrows=2000)
            return df, enc
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Encodage illisible : {chemin}")


fichiers = sorted(glob.glob(os.path.join(DOSSIER, "**", "*.csv"), recursive=True))
console = sys.stdout
sys.stdout = open(SORTIE, "w", encoding="utf-8")        # tout ce qui est affiché va dans inspection.txt

print(len(fichiers), "fichier(s) CSV trouvé(s)")
for chemin in fichiers:
    df, enc = lire_echantillon(chemin)
    with open(chemin, encoding=enc, errors="ignore") as f:
        nb = sum(1 for _ in f) - 1
    print("=" * 80)
    print(chemin, "|", nb, "lignes |", enc)
    print("colonnes :", list(df.columns))
    print(df.head(2).to_string())

sys.stdout.close()
sys.stdout = console
print(f"{len(fichiers)} fichier(s) analysé(s). Résultat écrit dans {SORTIE}")