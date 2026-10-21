#!/root/ema/bin/python3
import sqlite3
import csv
import time
from pathlib import Path

BASE = Path("/root/ema/export")
DATA = BASE / "enquete_pediatrique/data"
RESULTS = BASE / "enquete_pediatrique/results"
RESULTS.mkdir(exist_ok=True)

source = sqlite3.connect(
    f"file:{BASE / 'ema_clean.db'}?mode=ro", uri=True
)
source.execute(
    "ATTACH DATABASE ? AS pedi",
    (f"file:{DATA / 'cohorte_pediatrique.sqlite'}?mode=ro",)
)

vaccins = source.execute("""
    SELECT substance_code, substance_name, atc_code
    FROM ema_substances
    WHERE UPPER(TRIM(atc_code)) LIKE 'J07%'
      AND UPPER(TRIM(atc_code)) NOT LIKE 'J07BN%'
    ORDER BY substance_code
""").fetchall()

out = sqlite3.connect(DATA / "vaccins_pediatriques.sqlite")
out.executescript("""
CREATE TABLE IF NOT EXISTS associations (
  safety_report_id INTEGER NOT NULL,
  substance_code INTEGER NOT NULL,
  age_group TEXT NOT NULL,
  PRIMARY KEY(safety_report_id, substance_code)
);
CREATE TABLE IF NOT EXISTS progression (
  substance_code INTEGER PRIMARY KEY,
  nombre INTEGER NOT NULL
);
""")
out.commit()

debut = time.monotonic()

for i, (code, nom, atc) in enumerate(vaccins, 1):
    deja = out.execute(
        "SELECT nombre FROM progression WHERE substance_code=?",
        (code,)
    ).fetchone()

    if deja:
        print(f"[{i}/{len(vaccins)}] Déjà traité : {nom}",
              flush=True)
        continue

    cur = source.execute("""
        SELECT s.safety_report_id, e.age_group
        FROM ema_icsr_substance AS s
             INDEXED BY ema_icsr_substance_code_idx
        JOIN pedi.enfants AS e
          ON e.safety_report_id=s.safety_report_id
        WHERE s.substance_code=?
    """, (code,))

    total = 0
    out.execute("BEGIN")

    while True:
        rows = cur.fetchmany(10000)
        if not rows:
            break

        out.executemany(
            "INSERT OR IGNORE INTO associations VALUES(?,?,?)",
            ((rid, code, age) for rid, age in rows)
        )
        total += len(rows)

    n = out.execute(
        "SELECT COUNT(*) FROM associations WHERE substance_code=?",
        (code,)
    ).fetchone()[0]

    out.execute(
        "INSERT INTO progression VALUES(?,?)",
        (code, n)
    )
    out.commit()

    print(
        f"[{i}/{len(vaccins)}] {nom[:65]} : {n:,} "
        f"| durée {time.monotonic()-debut:.0f}s",
        flush=True
    )

# Export des effectifs par vaccin et classe d'âge.
csvpath = RESULTS / "vaccins_identifies.csv"

with csvpath.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
        "substance_code", "substance_name", "atc_code",
        "signalements", "0-1 Month", "2 Months - 2 Years",
        "3-11 Years", "12-17 Years"
    ])

    for code, nom, atc in vaccins:
        counts = dict(out.execute("""
            SELECT age_group, COUNT(*)
            FROM associations
            WHERE substance_code=?
            GROUP BY age_group
        """, (code,)))

        writer.writerow([
            code, nom, atc,
            sum(counts.values()),
            *(counts.get(age, 0) for age in (
                "0-1 Month", "2 Months - 2 Years",
                "3-11 Years", "12-17 Years"
            ))
        ])

unique = out.execute("""
    SELECT COUNT(DISTINCT safety_report_id)
    FROM associations
""").fetchone()[0]

print("\n=== IDENTIFICATION TERMINÉE ===")
print("Substances analysées :", len(vaccins))
print("Signalements vaccinaux distincts :", unique)
print("CSV :", csvpath)
print("Base :", DATA / "vaccins_pediatriques.sqlite")

source.close()
out.close()
