#!/root/ema/bin/python3
import sqlite3
import time
import fcntl
import sys
from collections import Counter
from pathlib import Path

BASE = Path("/root/ema/export")
OUT = BASE / "enquete_pediatrique/data"
SOURCE = BASE / "ema_clean.db"
DEST = OUT / "cohorte_pediatrique.sqlite"

AGES = {
    "0-1 Month",
    "2 Months - 2 Years",
    "3-11 Years",
    "12-17 Years",
}

BATCH = 50000

lock = open(OUT / ".cohorte.lock", "w")
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit("Extraction déjà en cours")

src = sqlite3.connect(
    f"file:{SOURCE}?mode=ro", uri=True
)
src.execute("PRAGMA query_only=ON")

dst = sqlite3.connect(DEST, timeout=120)
dst.execute("PRAGMA journal_mode=WAL")

dst.executescript("""
CREATE TABLE IF NOT EXISTS enfants (
    safety_report_id INTEGER PRIMARY KEY,
    age_group TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS progression (
    id INTEGER PRIMARY KEY CHECK(id=1),
    dernier_id INTEGER NOT NULL,
    parcourus INTEGER NOT NULL,
    retenus INTEGER NOT NULL
);

INSERT OR IGNORE INTO progression VALUES(1,0,0,0);
""")
dst.commit()

last, parcourus, retenus = dst.execute(
    "SELECT dernier_id,parcourus,retenus "
    "FROM progression WHERE id=1"
).fetchone()

if last == -1:
    print("Cohorte déjà terminée")
    sys.exit(0)

print("Reprise depuis :", last, flush=True)

debut = time.monotonic()

cur = src.execute("""
    SELECT safety_report_id,age_group,age_group_reported
    FROM ema_icsr
    WHERE safety_report_id>?
    ORDER BY safety_report_id
""", (last,))

while True:
    rows = cur.fetchmany(BATCH)
    if not rows:
        break

    enfants = [
        (rid, age)
        for rid, age, reported in rows
        if age in AGES
    ]

    dst.execute("BEGIN")

    dst.executemany(
        "INSERT OR IGNORE INTO enfants VALUES(?,?)",
        enfants
    )

    parcourus += len(rows)
    retenus += len(enfants)
    last = rows[-1][0]

    dst.execute(
        "UPDATE progression SET "
        "dernier_id=?,parcourus=?,retenus=? WHERE id=1",
        (last,parcourus,retenus)
    )
    dst.commit()

    if parcourus % 500000 < BATCH:
        print(
            f"Parcourus : {parcourus:,} | "
            f"0–17 ans : {retenus:,} | "
            f"Durée : {time.monotonic()-debut:.0f}s",
            flush=True
        )

dst.execute(
    "UPDATE progression SET dernier_id=-1 WHERE id=1"
)
dst.commit()

print("\n=== COHORTE PÉDIATRIQUE TERMINÉE ===")
print("Signalements parcourus :", parcourus)
print("Signalements 0–17 ans :", retenus)

print("\n=== PAR CLASSE D'ÂGE ===")
for age, n in dst.execute("""
    SELECT age_group,COUNT(*)
    FROM enfants
    GROUP BY age_group
    ORDER BY age_group
"""):
    print(age, f"{n:,}")

print("Base :", DEST)

src.close()
dst.close()
