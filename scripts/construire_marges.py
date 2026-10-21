#!/root/ema/bin/python3
import sqlite3
import time
from pathlib import Path
from collections import Counter

BASE = Path("/root/ema/export")
DATA = BASE / "enquete_pediatrique/data"
SOURCE = BASE / "ema_clean.db"
COHORTE = DATA / "cohorte_pediatrique.sqlite"
DEST = DATA / "marges_pediatriques.sqlite"
BATCH = 500

def ouvrir_ro(path):
    c = sqlite3.connect(
        f"file:{path.resolve()}?mode=ro",
        uri=True,
        timeout=60
    )
    c.execute("PRAGMA query_only=ON")
    return c

src = ouvrir_ro(SOURCE)
coh = ouvrir_ro(COHORTE)

# Vérifier l'existence d'un index commençant
# par safety_report_id.
indexes = src.execute(
    "PRAGMA index_list('ema_icsr_reaction')"
).fetchall()

indexed = False
for idx in indexes:
    columns = src.execute(
        'PRAGMA index_info("' + idx[1] + '")'
    ).fetchall()
    if columns and columns[0][2] == "safety_report_id":
        indexed = True
        print("Index utilisable :", idx[1])

if not indexed:
    raise SystemExit(
        "ARRÊT : aucun index adapté sur safety_report_id."
    )

dst = sqlite3.connect(DEST, timeout=120)
dst.execute("PRAGMA journal_mode=WAL")
dst.execute("PRAGMA synchronous=FULL")

dst.executescript("""
CREATE TABLE IF NOT EXISTS marges (
    reaction_pt TEXT NOT NULL,
    age_group TEXT NOT NULL,
    signalements INTEGER NOT NULL,
    PRIMARY KEY (reaction_pt, age_group)
);

CREATE TABLE IF NOT EXISTS progression (
    id INTEGER PRIMARY KEY CHECK(id=1),
    dernier_id INTEGER NOT NULL,
    traites INTEGER NOT NULL
);

INSERT OR IGNORE INTO progression VALUES (1,0,0);
""")
dst.commit()

last, done = dst.execute(
    "SELECT dernier_id, traites "
    "FROM progression WHERE id=1"
).fetchone()

total = coh.execute(
    "SELECT COUNT(*) FROM enfants"
).fetchone()[0]

print("=== EXTRACTION DES MARGES ===", flush=True)
print("Population pédiatrique :", total, flush=True)
print("Déjà traités :", done, flush=True)

start = time.monotonic()

while True:
    rows = coh.execute("""
        SELECT safety_report_id, age_group
        FROM enfants
        WHERE safety_report_id > ?
        ORDER BY safety_report_id
        LIMIT ?
    """, (last, BATCH)).fetchall()

    if not rows:
        break

    ages = {rid: age for rid, age in rows}
    ids = list(ages)

    placeholders = ",".join("?" for _ in ids)

    reactions = src.execute(f"""
        SELECT DISTINCT safety_report_id, reaction_pt
        FROM ema_icsr_reaction
        WHERE safety_report_id IN ({placeholders})
          AND reaction_pt IS NOT NULL
          AND TRIM(reaction_pt) <> ''
    """, ids)

    counts = Counter()

    for rid, pt in reactions:
        counts[(pt, ages[rid])] += 1

    dst.execute("BEGIN")

    dst.executemany("""
        INSERT INTO marges
            (reaction_pt, age_group, signalements)
        VALUES (?, ?, ?)
        ON CONFLICT(reaction_pt, age_group)
        DO UPDATE SET
            signalements =
                marges.signalements +
                excluded.signalements
    """, [
        (pt, age, n)
        for (pt, age), n in counts.items()
    ])

    last = rows[-1][0]
    done += len(rows)

    dst.execute("""
        UPDATE progression
        SET dernier_id=?, traites=?
        WHERE id=1
    """, (last, done))

    dst.commit()

    if done % 25000 < BATCH or done == total:
        print(
            f"Traités : {done:,}/{total:,} "
            f"| durée : {time.monotonic()-start:.0f}s",
            flush=True
        )

print("\n=== EXTRACTION TERMINÉE ===")

print("Signalements parcourus :", done)

for age, pts, mentions in dst.execute("""
    SELECT age_group,
           COUNT(*),
           SUM(signalements)
    FROM marges
    GROUP BY age_group
    ORDER BY age_group
"""):
    print(
        age,
        "| PT distincts :", pts,
        "| mentions dédoublonnées :", mentions
    )

print("Destination :", DEST)

src.close()
coh.close()
dst.close()
