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
    error         TEXT,
    not_duplicate INTEGER DEFAULT 0, -- usuário disse "Não é duplicata": não comparar por semelhança
    album_pin     TEXT               -- álbum escolhido pelo usuário (vale mais que o agrupamento)
);
CREATE INDEX IF NOT EXISTS idx_photos_sha    ON photos(sha256);
CREATE INDEX IF NOT EXISTS idx_photos_phash  ON photos(phash);
CREATE INDEX IF NOT EXISTS idx_photos_status ON photos(status);
CREATE INDEX IF NOT EXISTS idx_photos_album  ON photos(album_key);
CREATE INDEX IF NOT EXISTS idx_photos_size   ON photos(size);

CREATE TABLE IF NOT EXISTS albums(
    key            TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    start          TEXT,
    end            TEXT,
    google_id      TEXT,
    custom_title   INTEGER DEFAULT 0,
    pending_rename INTEGER DEFAULT 0,
    product_url    TEXT,
    google_items   INTEGER           -- quantos itens o álbum tem no Google (última busca)
);

-- álbuns esvaziados ao juntar: a busca no Google não os traz de volta para a lista
CREATE TABLE IF NOT EXISTS ignored_albums(google_id TEXT PRIMARY KEY);
"""


SCHEMA_VERSION = 4  # suba ao mudar o esquema; a migração roda uma vez por banco
_ready: set[str] = set()


def connect() -> sqlite3.Connection:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL")
    key = str(DB_PATH)
    if key not in _ready:  # connect() é chamado a cada clique: o pesado só na primeira vez
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
            _migrate(conn)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.commit()
        _ready.add(key)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Acrescenta colunas novas em bancos criados por versões anteriores."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(albums)")}
    if "product_url" not in cols:
        conn.execute("ALTER TABLE albums ADD COLUMN product_url TEXT")
        conn.commit()
    pcols = {r["name"] for r in conn.execute("PRAGMA table_info(photos)")}
    if "not_duplicate" not in pcols:
        conn.execute("ALTER TABLE photos ADD COLUMN not_duplicate INTEGER DEFAULT 0")
    if "album_pin" not in pcols:
        conn.execute("ALTER TABLE photos ADD COLUMN album_pin TEXT")
    acols = {r["name"] for r in conn.execute("PRAGMA table_info(albums)")}
    if "google_items" not in acols:
        conn.execute("ALTER TABLE albums ADD COLUMN google_items INTEGER")
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

    params = [(i,) for i in ids]
    # quem era cópia destes registros volta a ser avaliado do zero
    conn.executemany("UPDATE photos SET duplicate_of=NULL, status='scanned' "
                     "WHERE duplicate_of=? AND media_item_id IS NULL", params)
    n = conn.executemany("DELETE FROM photos WHERE id=?", params).rowcount
    for i in ids:
        try:
            (THUMBS_DIR / f"{i}.jpg").unlink()  # miniatura fica na pasta de dados do app
        except OSError:
            pass
    # álbuns que já existem no Google ficam: um novo envio volta para o mesmo álbum
    conn.execute("DELETE FROM albums WHERE google_id IS NULL AND key NOT IN "
                 "(SELECT DISTINCT album_key FROM photos WHERE album_key IS NOT NULL)")
    conn.commit()
    return n


def mark_not_duplicate(conn: sqlite3.Connection, ids: list[int]) -> int:
    """O usuário diz que a foto não é cópia de outra (ex.: fotos em sequência quase iguais).
    Vale para sempre: a comparação por semelhança deixa de considerá-la."""
    n = 0
    for i in ids:
        n += conn.execute(
            "UPDATE photos SET not_duplicate=1, duplicate_of=NULL, "
            "status=CASE WHEN category IS NULL THEN 'scanned' ELSE 'classified' END "
            "WHERE id=? AND media_item_id IS NULL", (i,)
        ).rowcount
    conn.commit()
    return n


def rows_under(conn: sqlite3.Connection, folder: str, select: str = "SELECT * FROM photos p") -> list:
    """Registros dentro de uma pasta. O LIKE do SQLite filtra rápido (ignora maiúsculas em ASCII) e
    a conferência final usa a mesma regra de caminho do resto do app."""
    prefix = os.path.join(norm_path(folder), "")
    key = os.path.join(path_key(folder), "")
    pattern = prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
    rows = conn.execute(f"{select} WHERE p.path LIKE ? ESCAPE '!'", (pattern,)).fetchall()
    return [r for r in rows if path_key(r["path"]).startswith(key)]


def ids_under(conn: sqlite3.Connection, folder: str) -> list[int]:
    return [r["id"] for r in rows_under(conn, folder, "SELECT p.id, p.path FROM photos p")]


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
    """Contagens da tela inicial, agregadas pelo SQLite (rápido mesmo com muitas fotos)."""
    from .config import wants_upload

    groups = conn.execute(
        "SELECT duplicate_of IS NOT NULL AS dup, status, category, decision, source, "
        "media_item_id IS NOT NULL AS sent, COUNT(*) AS n FROM photos GROUP BY 1, 2, 3, 4, 5, 6"
    ).fetchall()
    out = {
        "total": 0, "duplicadas": 0, "enviadas": 0, "a_enviar": 0,
        "erros": 0, "pendentes": 0, "por_categoria": {},
    }
    for g in groups:
        n = g["n"]
        out["total"] += n
        if g["dup"]:
            out["duplicadas"] += n
            continue
        if g["status"] == "scanned":
            out["pendentes"] += n
        if g["category"]:
            out["por_categoria"][g["category"]] = out["por_categoria"].get(g["category"], 0) + n
        row = {"duplicate_of": None, "decision": g["decision"], "source": g["source"], "category": g["category"]}
        if g["sent"]:
            out["enviadas"] += n
        elif g["status"] == "error":
            out["erros"] += n
        elif g["status"] == "classified" and wants_upload(row, cfg):
            out["a_enviar"] += n
    return out
