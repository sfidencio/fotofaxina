"""Banco SQLite local: guarda o estado de cada arquivo para o processo ser retomável."""
from __future__ import annotations

import os
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
    pending_rename INTEGER DEFAULT 0,
    product_url    TEXT
);
"""


def connect() -> sqlite3.Connection:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Acrescenta colunas novas em bancos criados por versões anteriores."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(albums)")}
    if "product_url" not in cols:
        conn.execute("ALTER TABLE albums ADD COLUMN product_url TEXT")
        conn.commit()
    _merge_path_variants(conn)


def norm_path(path: str) -> str:
    """Caminho canônico: no Windows "C:/a/b" e "C:\\a\\b" (e maiúsculas/minúsculas) são o mesmo arquivo."""
    return os.path.normpath(os.path.abspath(path))


def path_key(path: str) -> str:
    return os.path.normcase(norm_path(path))


def _merge_path_variants(conn: sqlite3.Connection) -> None:
    """Versões antigas gravavam o mesmo arquivo com "/" e "\\" como dois registros. Junta-os,
    preservando o que já foi enviado."""
    rows = conn.execute("SELECT id, path, media_item_id FROM photos").fetchall()
    if all(r["path"] == norm_path(r["path"]) for r in rows):
        return
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(path_key(r["path"]), []).append(r)
    for members in groups.values():
        members.sort(key=lambda r: (0 if r["media_item_id"] else 1, r["id"]))
        keep, extra = members[0], members[1:]
        for r in extra:
            conn.execute("UPDATE photos SET duplicate_of=? WHERE duplicate_of=?", (keep["id"], r["id"]))
            conn.execute("DELETE FROM photos WHERE id=?", (r["id"],))
        conn.execute("UPDATE photos SET path=? WHERE id=?", (norm_path(keep["path"]), keep["id"]))
    conn.execute("UPDATE photos SET duplicate_of=NULL WHERE duplicate_of=id")
    conn.commit()


def forget(conn: sqlite3.Connection, ids: list[int]) -> int:
    """Remove registros do banco do FotoFaxina. NÃO apaga arquivos nem nada no Google Fotos:
    na próxima análise esses arquivos são tratados como novos (e podem ser enviados de novo)."""
    from .config import THUMBS_DIR

    n = 0
    for i in ids:
        # quem era cópia deste registro volta a ser avaliado do zero
        conn.execute("UPDATE photos SET duplicate_of=NULL, status='scanned' "
                     "WHERE duplicate_of=? AND media_item_id IS NULL", (i,))
        n += conn.execute("DELETE FROM photos WHERE id=?", (i,)).rowcount
        try:
            (THUMBS_DIR / f"{i}.jpg").unlink()  # miniatura fica na pasta de dados do app
        except OSError:
            pass
    # álbuns que já existem no Google ficam: um novo envio volta para o mesmo álbum
    conn.execute("DELETE FROM albums WHERE google_id IS NULL AND key NOT IN "
                 "(SELECT DISTINCT album_key FROM photos WHERE album_key IS NOT NULL)")
    conn.commit()
    return n


def ids_under(conn: sqlite3.Connection, folder: str) -> list[int]:
    prefix = os.path.join(path_key(folder), "")
    return [r["id"] for r in conn.execute("SELECT id, path FROM photos")
            if path_key(r["path"]).startswith(prefix)]


def forget_all(conn: sqlite3.Connection) -> int:
    from .config import THUMBS_DIR

    n = conn.execute("DELETE FROM photos").rowcount
    conn.execute("DELETE FROM albums")
    conn.commit()
    if THUMBS_DIR.exists():
        for f in THUMBS_DIR.glob("*.jpg"):
            try:
                f.unlink()
            except OSError:
                pass
    return n


def album_url(row) -> str | None:
    """Link do álbum no Google Fotos (o que a API devolveu ou o formato padrão)."""
    if row["product_url"]:
        return row["product_url"]
    if row["google_id"]:
        return f"https://photos.google.com/lr/album/{row['google_id']}"
    return None


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
