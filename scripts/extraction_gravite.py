#!/root/ema/bin/python3
import sqlite3
from pathlib import Path
from collections import defaultdict

BASE = Path("/root/ema/export")
DATA = BASE / "enquete_pediatrique/data"
OUT = DATA / "gravite_pediatrique.sqlite"
BATCH = 500

src = sqlite3.connect(
    f"file:{BASE / 'ema_clean.db'}?mode=ro", uri=True
)
src.execute("PRAGMA query_only=ON")

vacc = sqlite3.connect(
    f"file:{DATA / 'vaccins_pediatriques.sqlite'}?mode=ro",
    uri=True
)

dst = sqlite3.connect(OUT)
dst.executescript("""
CREATE TABLE IF NOT EXISTS progression (
    id INTEGER PRIMARY KEY CHECK(id=1),
    dernier_id INTEGER NOT NULL,
    traites INTEGER NOT NULL
);
INSERT OR IGNORE INTO progression VALUES(1,0,0);

CREATE TABLE IF NOT EXISTS effets (
    substance_code INTEGER NOT NULL,
    reaction_pt TEXT NOT NULL,
    age_group TEXT NOT NULL,
    signalements INTEGER NOT NULL DEFAULT 0,
    deces INTEGER NOT NULL DEFAULT 0,
    hospitalisation INTEGER NOT NULL DEFAULT 0,
    sequelles INTEGER NOT NULL DEFAULT 0,
    invalidite INTEGER NOT NULL DEFAULT 0,
    pronostic_vital INTEGER NOT NULL DEFAULT 0,
    anomalie_congenitale INTEGER NOT NULL DEFAULT 0,
    autre_importante INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(substance_code,reaction_pt,age_group)
);
""")
dst.commit()

last, done = dst.execute("""
    SELECT dernier_id,traites
    FROM progression WHERE id=1
""").fetchone()

def flags(details):
    s = str(details or "").upper()
    return (
        int("RESULTS IN DEATH" in s or " - FATAL" in s),
        int("CAUSED/PROLONGED HOSPITALISATION" in s),
        int("RECOVERED/RESOLVED WITH SEQUELAE" in s),
        int("DISABLING" in s),
        int("LIFE THREATENING" in s),
        int("CONGENITAL ANOMALY" in s),
        int("OTHER MEDICALLY IMPORTANT CONDITION" in s)
    )

sql = """
INSERT INTO effets VALUES(?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(substance_code,reaction_pt,age_group)
DO UPDATE SET
 signalements=signalements+excluded.signalements,
 deces=deces+excluded.deces,
 hospitalisation=hospitalisation+excluded.hospitalisation,
 sequelles=sequelles+excluded.sequelles,
 invalidite=invalidite+excluded.invalidite,
 pronostic_vital=pronostic_vital+excluded.pronostic_vital,
 anomalie_congenitale=anomalie_congenitale+excluded.anomalie_congenitale,
 autre_importante=autre_importante+excluded.autre_importante
"""

cur = vacc.execute("""
 SELECT safety_report_id, substance_code, age_group
 FROM associations
 WHERE safety_report_id>?
 ORDER BY safety_report_id,substance_code
""", (last,))

pending = []
current = None

def process(batch):
    global last, done

    reports = defaultdict(list)
    for rid, code, age in batch:
        reports[rid].append((code,age))

    ids = list(reports)
    q = ",".join("?" for _ in ids)

    react = defaultdict(dict)

    for rid, pt, details in src.execute(f"""
        SELECT safety_report_id,reaction_pt,reaction_details
        FROM ema_icsr_reaction
        WHERE safety_report_id IN ({q})
    """, ids):
        if not pt:
            continue
        old = react[rid].get(pt, (0,)*7)
        new = flags(details)
        react[rid][pt] = tuple(
            int(a or b) for a,b in zip(old,new)
        )

    counts = defaultdict(lambda:[0]*8)

    for rid, products in reports.items():
        for pt, f in react.get(rid, {}).items():
            for code, age in products:
                v = counts[(code,pt,age)]
                v[0] += 1
                for j, flag in enumerate(f,1):
                    v[j] += flag

    dst.execute("BEGIN")
    dst.executemany(sql, (
        (code,pt,age,*values)
        for (code,pt,age),values in counts.items()
    ))

    last = max(ids)
    done += len(ids)

    dst.execute("""
        UPDATE progression
        SET dernier_id=?,traites=? WHERE id=1
    """, (last,done))
    dst.commit()

for rid, code, age in cur:
    if current is not None and rid != current and len(pending) >= BATCH:
        process(pending)
        pending.clear()

    current = rid
    pending.append((rid,code,age))

    if done and done % 10000 == 0 and len(pending) == 1:
        print("Signalements traités :",done,flush=True)

if pending:
    process(pending)

print("=== EXTRACTION TERMINÉE ===",flush=True)
print("Signalements vaccinaux traités :",done,flush=True)
print("Lignes vaccin-effet-âge :",dst.execute(
    "SELECT COUNT(*) FROM effets"
).fetchone()[0],flush=True)
print("Base :",OUT,flush=True)

src.close()
vacc.close()
dst.close()
