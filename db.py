"""Shared SQLite helpers (connection per request + schema creation / migration)."""
import os
import sqlite3

from flask import g

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE, "analyzer.db"))


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_e=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    """Create tables; upgrade databases from the original (no-login) version."""
    db = sqlite3.connect(DB_PATH)
    db.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT, job_title TEXT,
        score INTEGER, quality INTEGER, created_at TEXT, result_json TEXT, user_id INTEGER)""")
    cols = [r[1] for r in db.execute("PRAGMA table_info(analyses)")]
    if "user_id" not in cols:                       # migrate old database
        db.execute("ALTER TABLE analyses ADD COLUMN user_id INTEGER")
    db.execute("CREATE INDEX IF NOT EXISTS idx_analyses_user ON analyses(user_id)")
    db.commit()
    db.close()
