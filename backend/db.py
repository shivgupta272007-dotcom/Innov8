"""
db.py  –  Database helper for Innov8
=====================================
This module:
  1. Locates (or creates) innov8.db in the backend/ folder.
  2. Runs schema.sql once to create tables.
  3. Runs seed.sql once to insert demo data (skips if data already exists).
  4. Provides get_db() – a function that returns a fresh SQLite connection
     with row_factory set so rows behave like dictionaries.

Why store money as paise?
  Floating-point numbers (like 3.14) cannot represent most decimal fractions
  exactly.  Storing ₹860 as the integer 86000 paise avoids rounding bugs.
"""

import sqlite3
import os

# ── Paths ───────────────────────────────────────────────────────
# __file__ is this script's absolute path.
# We put the .db file next to this script inside backend/.
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
SCHEMA_SQL = os.path.join(BASE_DIR, "schema.sql")
SEED_SQL   = os.path.join(BASE_DIR, "seed.sql")

if os.environ.get("VERCEL"):
    import shutil
    TMP_DB = "/tmp/innov8.db"
    SRC_DB = os.path.join(BASE_DIR, "innov8.db")
    if not os.path.exists(TMP_DB) and os.path.exists(SRC_DB):
        try:
            shutil.copyfile(SRC_DB, TMP_DB)
        except Exception:
            pass
    DB_PATH = TMP_DB
else:
    DB_PATH = os.path.join(BASE_DIR, "innov8.db")


def get_db() -> sqlite3.Connection:
    """
    Open and return a new SQLite connection to innov8.db.

    row_factory = sqlite3.Row  →  lets us access columns by name:
        row["name"]  instead of  row[0]

    check_same_thread = False  →  Flask may call this from different
        threads; SQLite is safe here because Flask handles one request
        at a time by default.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row      # dict-like rows
    conn.execute("PRAGMA foreign_keys = ON")  # enforce FK constraints
    return conn


def _read_sql(path: str) -> str:
    """Read a .sql file and return its contents as a string."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def init_db() -> None:
    """
    Create tables (schema.sql) and load seed data (seed.sql).

    We check whether any groups exist before running seed.sql so that
    calling init_db() a second time never duplicates data.
    """
    conn = get_db()

    # 1️⃣  Create tables from schema.sql
    schema_sql = _read_sql(SCHEMA_SQL)
    conn.executescript(schema_sql)      # executescript runs multiple statements
    conn.commit()
    print("[db] Tables created (or already exist).")

    # 2️⃣  Seed demo data only if the DB is empty
    cursor = conn.execute("SELECT COUNT(*) FROM groups")
    count  = cursor.fetchone()[0]

    if count == 0:
        seed_sql = _read_sql(SEED_SQL)
        conn.executescript(seed_sql)
        conn.commit()
        print("[db] Demo data seeded (Goa Trip group).")
    else:
        print(f"[db] DB already has {count} group(s); skipping seed.")

    conn.close()


# ── Run directly to initialize the database ─────────────────────
# Usage:  python db.py
if __name__ == "__main__":
    init_db()
    print(f"[db] Database ready at: {DB_PATH}")

    # Quick sanity check – print all groups
    conn = get_db()
    rows = conn.execute("SELECT id, name, created_at FROM groups").fetchall()
    print("\nGroups in DB:")
    for r in rows:
        print(f"  id={r['id']}  name={r['name']}  created={r['created_at']}")
    conn.close()
