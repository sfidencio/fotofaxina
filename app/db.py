"""Banco SQLite local: guarda o estado de cada arquivo para o processo ser retomável."""
from __future__ import annotations

import sqlite3

from .config import APP_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos(
    id            INTEGER PRIMARY KEY,
    path          TEXT UNIQUE NOT NULL,
    size          INTEGER,
    mtime         REAL,
    sha256        TEXT,
    phash         TEXT,
    width         INTEGER,
    height        INTEGER,
    is_video      INTEGER DEFAULT 0,
    mime          TEXT,
    taken_at      TEXT,              -- ISO 8601
    date_source   TEXT,              -- exif | nome | arquivo
    camera        TEXT,
    source        TEXT,              -- camera | whatsapp | print | desconhecida
    category      TEXT,
    confidence    REAL,
    category_by   TEXT,              -- regra | ia | manual
    duplicate_of  INTEGER,
    album_key     TEXT,
    decision      TEXT,              -- upload | skip | NULL (automático)
    status        TEXT DEFAULT 'scanned',   -- scanned | classified | uploaded | error
    media_item_id TEXT,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_photos_sha    ON photos(sha256);
CREATE INDEX IF NOT EXISTS idx_photos_phash  ON photos(phash);
CREATE INDEX IF NOT EXISTS idx_photos_status ON photos(status);
CREATE INDEX IF NOT EXISTS idx_photos_album  ON photos(album_key);

CREATE TABLE IF NOT EXISTS albums(
    key            TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    start          TEXT,
    end            TEXT,
    google_id      TEXT,
    custom_title   INTEGER DEFAULT 0,
    pending_rename INTEGER DEFAULT 0
);
"""


def connect() -> sqlite3.Connection:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def summary(conn: sqlite3.Connection, cfg) -> dict:
    from .config import wants_upload

    rows = conn.execute("SELECT * FROM photos").fetchall()
    out = {
        "total": len(rows), "duplicadas": 0, "enviadas": 0, "a_enviar": 0,
        "erros": 0, "pendentes": 0, "por_categoria": {},
    }
    for r in rows:
        if r["duplicate_of"] is not None:
            out["duplicadas"] += 1
            continue
        if r["status"] == "scanned":
            out["pendentes"] += 1
        if r["category"]:
            out["por_categoria"][r["category"]] = out["por_categoria"].get(r["category"], 0) + 1
        if r["media_item_id"]:
            out["enviadas"] += 1
        elif r["status"] == "error":
            out["erros"] += 1
        elif r["status"] == "classified" and wants_upload(r, cfg):
            out["a_enviar"] += 1
    return out
