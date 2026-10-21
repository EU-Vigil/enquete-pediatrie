#!/root/ema/bin/python3
import csv
import json
from pathlib import Path
from collections import Counter, defaultdict

BASE = Path("/root/ema/export")
OUT = BASE / "enquete_pediatrique/results"
SOURCE = OUT / "signaux_pediatriques_4_methodes.csv"

subs = json.loads(
    (BASE / "raw_stats_cache/_evt/subs.json").read_text(
        encoding="utf-8"
    )
)
names = dict(zip(map(str, subs["code"]), subs["name"]))

CATEGORIES = [
    "deces",
    "hospitalisation",
    "sequelles",
    "invalidite",
    "pronostic_vital",
    "anomalie_congenitale",
    "autre_importante",
]

METHODES = [
    "ror_signal",
    "prr_signal",
    "bcpnn_signal",
    "gps_signal",
]

def positif(value):
    return str(value).strip().lower() in ("1", "true")

def entier(value):
    return int(value or 0)

def nombre(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0

records = []
bilan = defaultdict(Counter)

with SOURCE.open(
    encoding="utf-8-sig", newline=""
) as f:
    for row in csv.DictReader(f):
        code = row["substance_code"]
        age = row["age_group"]

        row["vaccin"] = names.get(code, code)

        npositives = sum(
            positif(row[m]) for m in METHODES
        )
        row["methodes_positives_verifiees"] = npositives

        valide = row["statut"] == "calcule"
        concordant = valide and npositives == 4

        row["concordance_4"] = int(concordant)

        bilan[age]["total"] += 1

        if valide:
            bilan[age]["calcules"] += 1

        if concordant:
            bilan[age]["concordants"] += 1

        for cat in CATEGORIES:
            if entier(row[cat]) > 0:
                bilan[age][f"{cat}_tous"] += 1
                if concordant:
                    bilan[age][f"{cat}_4"] += 1

        records.append(row)

print("=== CONTROLE INITIAL ===")
print("Lignes :", len(records))
print(
    "Concordances 4/4 :",
    sum(int(r["concordance_4"]) for r in records)
)

assert len(records) == 76663
assert sum(
    int(r["concordance_4"]) for r in records
) == 5423

# 1. Tableau exhaustif annoté
master = OUT / "exploration_gravite_complete.csv"

fields = list(records[0].keys())

with master.open(
    "w", encoding="utf-8", newline=""
) as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(records)

# 2. Synthèse selon âge et critère
summary = OUT / "synthese_gravite_par_age.csv"

with summary.open(
    "w", encoding="utf-8", newline=""
) as f:
    w = csv.writer(f)
    w.writerow([
        "age", "critere",
        "combinaisons_avec_critere",
        "concordances_4"
    ])

    for age in sorted(bilan):
        for cat in CATEGORIES:
            w.writerow([
                age, cat,
                bilan[age][f"{cat}_tous"],
                bilan[age][f"{cat}_4"],
            ])

# 3. Top 20 par âge et critère
ranking = OUT / "top_effets_graves_4_methodes.csv"

ranking_fields = [
    "critere", "age_group", "rang",
    "substance_code", "vaccin",
    "reaction_pt", "a", "effectif_critere",
    "deces", "hospitalisation", "sequelles",
    "ror", "ror_lb", "ror_ub",
    "prr", "prr_lb", "prr_ub",
    "ic", "ic025", "gps_ebgm",
    "gps_eb05", "gps_eb95",
]

with ranking.open(
    "w", encoding="utf-8", newline=""
) as f:
    w = csv.DictWriter(
        f, fieldnames=ranking_fields
    )
    w.writeheader()

    for age in sorted(bilan):
        for cat in CATEGORIES:
            selected = [
                r for r in records
                if r["age_group"] == age
                and int(r["concordance_4"]) == 1
                and entier(r["a"]) >= 5
                and entier(r[cat]) > 0
            ]

            selected.sort(
                key=lambda r: (
                    entier(r[cat]),
                    entier(r["a"]),
                    nombre(r["gps_eb05"])
                ),
                reverse=True
            )

            for rank, r in enumerate(
                selected[:20], 1
            ):
                item = {
                    "critere": cat,
                    "age_group": age,
                    "rang": rank,
                    "effectif_critere": r[cat],
                }

                for key in ranking_fields:
                    if key in r:
                        item[key] = r[key]

                w.writerow(item)

print("\n=== SYNTHESE PAR AGE ===")

for age in sorted(bilan):
    b = bilan[age]
    print("\n", age)
    print("Combinaisons :", b["total"])
    print("Calculées :", b["calcules"])
    print("Concordances 4/4 :", b["concordants"])

    for cat in CATEGORIES:
        print(
            cat,
            "| avec critère :", b[f"{cat}_tous"],
            "| concordances 4/4 :", b[f"{cat}_4"]
        )

print("\n=== FICHIERS PRODUITS ===")
for p in (master, summary, ranking):
    print(p, "|", p.stat().st_size, "octets")

print("\n=== EXPLORATION TERMINEE ===")
