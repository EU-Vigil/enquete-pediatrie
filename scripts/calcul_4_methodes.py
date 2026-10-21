#!/root/ema/bin/python3
import csv
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

BASE = Path("/root/ema/export")
DATA = BASE / "enquete_pediatrique/data"
RESULTS = BASE / "enquete_pediatrique/results"
ENGINE = BASE / "EU-VIGIL-COVID19-Pharmacovigilance/code"

sys.path.insert(0, str(BASE))
sys.path.insert(0, str(ENGINE))
from signal_methods import all_methods

RESULTS.mkdir(parents=True, exist_ok=True)

meta = json.loads(
    (BASE / "raw_stats_cache/_evt/meta.json").read_text()
)
priors = meta["gps"]["priors"]

db = sqlite3.connect(":memory:")

for alias, filename in [
    ("g", "gravite_pediatrique.sqlite"),
    ("m", "marges_pediatriques.sqlite"),
    ("v", "vaccins_pediatriques.sqlite"),
    ("c", "cohorte_pediatrique.sqlite"),
]:
    path = (DATA / filename).resolve()
    db.execute(
        f"ATTACH DATABASE ? AS {alias}",
        (f"file:{path}?mode=ro",)
    )

query = """
WITH pop AS (
    SELECT age_group, COUNT(*) AS N
    FROM c.enfants
    GROUP BY age_group
),
vacc AS (
    SELECT substance_code,age_group,COUNT(*) AS nv
    FROM v.associations
    GROUP BY substance_code,age_group
)
SELECT
    g.substance_code,
    g.reaction_pt,
    g.age_group,
    p.N,
    v.nv,
    m.signalements,
    g.signalements,
    g.deces,
    g.hospitalisation,
    g.sequelles,
    g.invalidite,
    g.pronostic_vital,
    g.anomalie_congenitale,
    g.autre_importante
FROM g.effets g
JOIN pop p ON p.age_group=g.age_group
JOIN vacc v
  ON v.substance_code=g.substance_code
 AND v.age_group=g.age_group
JOIN m.marges m
  ON m.reaction_pt=g.reaction_pt
 AND m.age_group=g.age_group
WHERE
    g.deces>0 OR g.hospitalisation>0
    OR g.sequelles>0 OR g.invalidite>0
    OR g.pronostic_vital>0
    OR g.anomalie_congenitale>0
    OR g.autre_importante>0
ORDER BY g.substance_code,g.age_group,g.reaction_pt
"""

rows = db.execute(query).fetchall()

print("=== ANALYSE PEDIATRIQUE ===", flush=True)
print("Combinaisons avec gravité :", len(rows), flush=True)
print("GPS : paramètres existants conservés", flush=True)

cols = [
    "substance_code","reaction_pt","age_group",
    "N_age","n_vaccin","n_effet",
    "a","b","c","d",
    "deces","hospitalisation","sequelles",
    "invalidite","pronostic_vital",
    "anomalie_congenitale","autre_importante",
    "ror","ror_lb","ror_ub","ror_signal",
    "prr","prr_lb","prr_ub","prr_signal",
    "bcpnn","ic","ic025","bcpnn_signal",
    "gps_ebgm","gps_eb05","gps_eb95","gps_signal",
    "statut"
]

output = RESULTS / "signaux_pediatriques_4_methodes.csv"
tmp = output.with_suffix(".csv.tmp")

computed = 0
nulls = 0

def scalar(x):
    v = float(np.asarray(x).reshape(-1)[0])
    return v if np.isfinite(v) else ""

with tmp.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=cols)
    writer.writeheader()

    for k, row in enumerate(rows, 1):
        (code, pt, age, N, nv, ne, a,
         deces, hosp, seq, inv, vital,
         congen, autre) = row

        a, N, nv, ne = map(int, (a, N, nv, ne))

        b = nv - a
        c = ne - a
        d = N - nv - ne + a

        if min(a,b,c,d) < 0:
            raise RuntimeError(
                f"Tableau invalide : {code}, {pt}, {age}"
            )

        result = dict(zip(cols[:17], [
            code,pt,age,N,nv,ne,a,b,c,d,
            deces,hosp,seq,inv,vital,congen,autre
        ]))

        if min(a,b,c,d) == 0:
            result["statut"] = "cellule_nulle"
            nulls += 1
        else:
            metrics = all_methods(
                np.array([a], dtype=float),
                np.array([nv], dtype=float),
                np.array([ne], dtype=float),
                N,
                priors
            )

            ro = metrics["ror"]
            pr = metrics["prr"]
            bc = metrics["bcpnn"]
            gp = metrics["gps"]

            values = {
                "ror": scalar(ro["value"]),
                "ror_lb": scalar(ro["lb"]),
                "ror_ub": scalar(ro["ub"]),
                "ror_signal": int(bool(ro["signal"][0])),
                "prr": scalar(pr["value"]),
                "prr_lb": scalar(pr["lb"]),
                "prr_ub": scalar(pr["ub"]),
                "prr_signal": int(bool(pr["signal"][0])),
                "bcpnn": scalar(bc["value"]),
                "ic": scalar(bc["ic"]),
                "ic025": scalar(bc["ic025"]),
                "bcpnn_signal": int(bool(bc["signal"][0])),
                "gps_ebgm": scalar(gp["value"]),
                "gps_eb05": scalar(gp["lb"]),
                "gps_eb95": scalar(gp["ub"]),
                "gps_signal": int(bool(gp["signal"][0])),
            }

            result.update(values)
            result["statut"] = (
                "calcule"
                if all(
                    isinstance(values[x], float)
                    for x in (
                        "ror","prr","bcpnn",
                        "gps_ebgm","gps_eb05"
                    )
                )
                else "resultat_non_fini"
            )
            computed += 1

        writer.writerow(result)

        if k % 5000 == 0:
            print(f"Analysés : {k:,}/{len(rows):,}", flush=True)

tmp.replace(output)
db.close()

print("\n=== CALCUL TERMINE ===")
print("Combinaisons :", len(rows))
print("Méthodes appliquées :", computed)
print("Cellules nulles :", nulls)
print("Fichier :", output)
