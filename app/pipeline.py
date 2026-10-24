"""Orquestra as etapas. Todas são idempotentes: podem ser interrompidas e retomadas."""
from __future__ import annotations

import os

from . import classifier, db, grouper, scanner
from .config import Config, wants_upload
from .google_photos import BATCH_LIMIT, GooglePhotos, QuotaExceeded


def _noop(*a, **k):
    return None


def processar(root: str, cfg: Config, progress=_noop, log=_noop, stop=None) -> dict:
    """Varredura + classificação + agrupamento. Não envia nada."""
    scanner.scan(root, cfg, progress, log, stop)
    if stop is not None and stop.is_set():
        return {"parado": True}
    classifier.classify(cfg, progress, log, stop)
    if stop is not None and stop.is_set():
        return {"parado": True}
    grouper.group(cfg, log)
    conn = db.connect()
    res = db.summary(conn, cfg)
    conn.close()
    return res


def reagrupar(cfg: Config, progress=_noop, log=_noop, stop=None) -> dict:
    grouper.group(cfg, log)
    conn = db.connect()
    res = db.summary(conn, cfg)
    conn.close()
    return res


def conectar_google(progress=_noop, log=_noop, stop=None) -> bool:
    GooglePhotos().connect(interactive=True)
    log("Conta Google conectada.")
    return True


def enviar(cfg: Config, progress=_noop, log=_noop, stop=None) -> dict:
    grouper.group(cfg, log)
    gp = GooglePhotos()
    gp.connect(interactive=False)
    conn = db.connect()

    # renomeações feitas na aba Álbuns depois que o álbum já existia no Google
    for a in conn.execute("SELECT * FROM albums WHERE google_id IS NOT NULL AND pending_rename=1").fetchall():
        try:
            gp.rename_album(a["google_id"], a["title"])
            conn.execute("UPDATE albums SET pending_rename=0 WHERE key=?", (a["key"],))
            log(f"Álbum renomeado: {a['title']}")
        except Exception as e:
            log(f"Não consegui renomear '{a['title']}': {e}")
    conn.commit()

    rows = conn.execute(
        "SELECT * FROM photos WHERE status='classified' AND media_item_id IS NULL "
        "AND album_key IS NOT NULL ORDER BY album_key, taken_at"
    ).fetchall()
    rows = [r for r in rows if wants_upload(r, cfg)]
    uploaded_hashes = {
        r[0] for r in conn.execute("SELECT sha256 FROM photos WHERE media_item_id IS NOT NULL")
    }
    total = len(rows)
    log(f"{total} itens para enviar")
    enviados = erros = 0
    done = 0

    by_album: dict[str, list] = {}
    for r in rows:
        by_album.setdefault(r["album_key"], []).append(r)

    try:
        for key, items in by_album.items():
            if stop is not None and stop.is_set():
                break
            album = conn.execute("SELECT * FROM albums WHERE key=?", (key,)).fetchone()
            album_id = album["google_id"]
            for start in range(0, len(items), BATCH_LIMIT):
                if stop is not None and stop.is_set():
                    break
                chunk = items[start:start + BATCH_LIMIT]
                tokens: dict[str, int] = {}
                pairs = []
                for r in chunk:
                    done += 1
                    progress("Enviando", done, total, os.path.basename(r["path"]))
                    if r["sha256"] in uploaded_hashes:
                        conn.execute("UPDATE photos SET status='uploaded' WHERE id=?", (r["id"],))
                        continue
                    if not os.path.exists(r["path"]):
                        conn.execute(
                            "UPDATE photos SET status='error', error=? WHERE id=?",
                            ("Arquivo indisponível (HD desconectado?)", r["id"]),
                        )
                        erros += 1
                        continue
                    try:
                        tok = gp.upload_bytes(r["path"], r["mime"])
                    except QuotaExceeded:
                        raise
                    except Exception as e:
                        conn.execute("UPDATE photos SET status='error', error=? WHERE id=?", (str(e)[:500], r["id"]))
                        erros += 1
                        continue
                    tokens[tok] = r["id"]
                    pairs.append((tok, os.path.basename(r["path"])))
                if not pairs:
                    conn.commit()
                    continue
                if not album_id:
                    album_id = gp.create_album(album["title"])
                    conn.execute(
                        "UPDATE albums SET google_id=?, pending_rename=0 WHERE key=?", (album_id, key)
                    )
                    conn.commit()
                    log(f"Álbum criado: {album['title']}")
                results = gp.batch_create(album_id, pairs)
                for tok, photo_id in tokens.items():
                    ok, val = results.get(tok, (False, "sem resposta do Google"))
                    if ok:
                        conn.execute(
                            "UPDATE photos SET status='uploaded', media_item_id=?, error=NULL WHERE id=?",
                            (val, photo_id),
                        )
                        sha = conn.execute("SELECT sha256 FROM photos WHERE id=?", (photo_id,)).fetchone()[0]
                        uploaded_hashes.add(sha)
                        enviados += 1
                    else:
                        conn.execute("UPDATE photos SET status='error', error=? WHERE id=?", (val[:500], photo_id))
                        erros += 1
                conn.commit()
    except QuotaExceeded as e:
        conn.commit()
        log(str(e))
    finally:
        conn.commit()

    log(f"Envio concluído: {enviados} enviados, {erros} com erro")
    res = db.summary(conn, cfg)
    conn.close()
    res["enviados_agora"] = enviados
    res["erros_agora"] = erros
    return res


def tentar_erros_novamente() -> int:
    conn = db.connect()
    n = conn.execute(
        "UPDATE photos SET status='classified', error=NULL WHERE status='error' AND media_item_id IS NULL"
    ).rowcount
    conn.commit()
    conn.close()
    return n
