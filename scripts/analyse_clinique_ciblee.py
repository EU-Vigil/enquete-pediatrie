#!/root/ema/bin/python3
import csv
import re
from pathlib import Path
from collections import defaultdict, Counter

BASE = Path("/root/ema/export/enquete_pediatrique/results")
SOURCE = BASE / "exploration_gravite_complete.csv"
OUT = BASE / "analyses_cliniques"
OUT.mkdir(parents=True, exist_ok=True)

AGES = [
    "0-1 Month",
    "2 Months - 2 Years",
    "3-11 Years",
    "12-17 Years"
]

# Reperage exploratoire des termes MedDRA PT.
# Ces listes ne remplacent pas une classification SMQ MedDRA.
GROUPS = {
    "invagination_intestinale": [
        r"\bintussusception\b",
    ],
    "neurologique": [
        r"\bseizure\b",
        r"\bconvulsion\b",
        r"\bepilep",
        r"\bencephal",
        r"\bmeningoencephal",
        r"\bguillain.barr",
        r"\bdemyelin",
        r"\bmyelitis\b",
        r"\bneuropathy\b",
        r"\bparalysis\b",
        r"\bparesis\b",
        r"\bataxia\b",
        r"\bhypotonic.hyporesponsive\b",
        r"\bhyporesponsive to stimuli\b",
        r"\bloss of consciousness\b",
        r"\bconsciousness decreased\b",
        r"\bsyncope\b",
        r"\bcoma\b",
        r"\bstatus epilepticus\b",
    ],
    "mort_subite_nourrisson": [
        r"^sudden infant death syndrome$",
    ]
}

PATTERNS = {
    group: [re.compile(x, re.I) for x in patterns]
    for group, patterns in GROUPS.items()
}

FLAGS = [
    "deces",
    "hospitalisation",
    "sequelles",
    "invalidite",
    "pronostic_vital",
    "anomalie_congenitale",
    "autre_importante"
]
METHODS = [
    "ror_signal",
    "prr_signal",
    "bcpnn_signal",
    "gps_signal"
]

def as_int(v):
    return int(v or 0)

def positive(v):
    return str(v).strip().lower() in ("1", "true")

def select_group(pt, group):
    return any(p.search(pt) for p in PATTERNS[group])

with SOURCE.open(encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)
    columns = reader.fieldnames
    assert columns is not None
    rows = list(reader)

assert len(rows) == 76663, len(rows)

summary = []
priorities = []
all_selected = set()

for group in GROUPS:
    selected = [
        r for r in rows
        if select_group(r["reaction_pt"], group)
    ]

    # On conserve les lignes non calculables,
    # sans inventer de valeur statistique.
    path = OUT / f"{group}_complet.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(selected)

    for row in selected:
        all_selected.add((
            row["substance_code"],
            row["reaction_pt"],
            row["age_group"]
        ))

    for age in AGES:
        subset = [
            r for r in selected
            if r["age_group"] == age
        ]

        calculated = [
            r for r in subset
            if r["statut"] == "calcule"
        ]
        concordant = [
            r for r in calculated
            if all(positive(r[m]) for m in METHODS)
        ]

        item = {
            "groupe": group,
            "age": age,
            "combinaisons": len(subset),
            "calculables": len(calculated),
            "concordances_4": len(concordant),
            "termes_PT_distincts": len({
                r["reaction_pt"] for r in subset
            }),
            "vaccins_distincts": len({
                r["substance_code"] for r in subset
            })
        }
        for flag in FLAGS:
            item[f"combinaisons_avec_{flag}"] = sum(
                as_int(r[flag]) > 0 for r in subset
            )
            item[f"concordances_avec_{flag}"] = sum(
                as_int(r[flag]) > 0 for r in concordant
            )

        summary.append(item)

        # Classement exploratoire selon les mentions
        # de gravite et l'effectif de la combinaison.
        concordant.sort(
            key=lambda r: (
                -as_int(r["deces"]),
                -as_int(r["pronostic_vital"]),
                -as_int(r["hospitalisation"]),
                -as_int(r["a"]),
            )
        )

        for rank, r in enumerate(concordant[:30], 1):
            priorities.append({
                "groupe": group,
                "rang": rank,
                **r
            })

summary_path = OUT / "synthese_clinique.csv"
with summary_path.open("w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(
        f, fieldnames=list(summary[0])
    )
    writer.writeheader()
    writer.writerows(summary)

priority_path = OUT / "priorites_cliniques.csv"
with priority_path.open("w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=["groupe", "rang"] + columns
    )
    writer.writeheader()
    writer.writerows(priorities)

print("=== BILAN DES DOSSIERS CLINIQUES ===")

for group in GROUPS:
    print("\nDOSSIER :", group)
    for s in summary:
        if s["groupe"] != group:
            continue
        print(
            s["age"],
            "| associations :", s["combinaisons"],
            "| calculables :", s["calculables"],
            "| concordances 4/4 :", s["concordances_4"],
            "| PT distincts :", s["termes_PT_distincts"]
        )

print("\nAssociations uniques couvertes :", len(all_selected))
print("\n=== FICHIERS ===")
for p in sorted(OUT.glob("*.csv")):
    print(p, "|", p.stat().st_size, "octets")

print("\n=== ANALYSE TERMINEE ===")
