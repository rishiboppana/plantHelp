import sqlite3, json
from pathlib import Path

DB = Path(__file__).parent / "plantlens.db"


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS plants(
          id INTEGER PRIMARY KEY, name TEXT, species TEXT, status TEXT DEFAULT 'green',
          profile TEXT DEFAULT '{}', created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS entries(
          id INTEGER PRIMARY KEY, plant_id INTEGER, kind TEXT, text TEXT, image TEXT,
          analysis TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS events(
          id INTEGER PRIMARY KEY, plant_id INTEGER, title TEXT, due TEXT, status TEXT DEFAULT 'planned',
          result TEXT DEFAULT '', created TEXT DEFAULT CURRENT_TIMESTAMP, done_at TEXT);
        CREATE TABLE IF NOT EXISTS conversations(
          id INTEGER PRIMARY KEY, plant_id INTEGER, title TEXT DEFAULT 'New chat', state TEXT DEFAULT '',
          created TEXT DEFAULT CURRENT_TIMESTAMP, updated TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS messages(
          id INTEGER PRIMARY KEY, conversation_id INTEGER, role TEXT, content TEXT, image TEXT, analysis TEXT,
          created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS traces(
          trace_id TEXT PRIMARY KEY, conversation_id INTEGER, plant_id INTEGER, data TEXT,
          created TEXT DEFAULT CURRENT_TIMESTAMP, updated TEXT DEFAULT CURRENT_TIMESTAMP);
        """)
        if "renamed" not in [r[1] for r in c.execute("PRAGMA table_info(conversations)")]:
            c.execute("ALTER TABLE conversations ADD COLUMN renamed INTEGER DEFAULT 0")  # user-set titles are never auto-overwritten
        ev_cols = [r[1] for r in c.execute("PRAGMA table_info(events)")]
        for col, ddl in (("kind", "TEXT DEFAULT 'care'"), ("source", "TEXT DEFAULT 'manual'")):   # scheduler: recheck|care, manual|checkup|plan
            if col not in ev_cols: c.execute(f"ALTER TABLE events ADD COLUMN {col} {ddl}")
        if not c.execute("SELECT 1 FROM plants").fetchone():
            c.execute("INSERT INTO plants(name,species) VALUES('My first plant','')")


def rows(sql, args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def run(sql, args=()):
    with conn() as c:
        return c.execute(sql, args).lastrowid
