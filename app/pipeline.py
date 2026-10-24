"""Orquestra as etapas. Todas são idempotentes: podem ser interrompidas e retomadas."""
from __future__ import annotations

import os

from . import classifier, db, grouper, scanner
from .config import Config, wants_upload
from .google_photos import BATCH_LIMIT, GooglePhotos, GooglePhotosError, QuotaExceeded
from .i18n import _


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
    res["pasta"] = folder_summary(conn, root, cfg)
    conn.close()
    return res


def folder_summary(conn, root: str, cfg: Config) -> dict:
    """O que aconteceu com os arquivos DESTA pasta (o resumo geral mistura todas as análises)."""
    prefix = os.path.join(db.path_key(root), "")
    rows = [r for r in conn.execute("SELECT * FROM photos").fetchall()
            if db.path_key(r["path"]).startswith(prefix)]
    by_id = {r["id"]: r for r in conn.execute("SELECT id, path, media_item_id FROM photos")}
    out = {"total": len(rows), "ja_no_google": 0, "repetidas": 0, "a_enviar": 0, "fora": 0}
    for r in rows:
        keeper = by_id.get(r["duplicate_of"]) if r["duplicate_of"] is not None else None
        if r["media_item_id"] or (keeper is not None and keeper["media_item_id"]):
            out["ja_no_google"] += 1
        elif keeper is not None:
            out["repetidas"] += 1
        elif r["status"] == "classified" and wants_upload(r, cfg):
            out["a_enviar"] += 1
        else:
            out["fora"] += 1
    return out


def reagrupar(cfg: Config, progress=_noop, log=_noop, stop=None) -> dict:
    grouper.group(cfg, log)
    conn = db.connect()
    res = db.summary(conn, cfg)
    conn.close()
    return res


def conectar_google(progress=_noop, log=_noop, stop=None) -> bool:
    GooglePhotos().connect(interactive=True)
    log(_("Conta Google conectada."))
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
            log(_("Álbum renomeado: {titulo}").format(titulo=a["title"]))
        except Exception as e:
            log(_("Não consegui renomear “{titulo}”: {erro}").format(titulo=a["title"], erro=e))
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
    log(_("{n} itens para enviar").format(n=total))
    enviados = erros = 0
    done = 0
    novos_albuns: list[str] = []

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
                    progress(_("Enviando"), done, total, os.path.basename(r["path"]))
                    if r["sha256"] in uploaded_hashes:
                        conn.execute("UPDATE photos SET status='uploaded' WHERE id=?", (r["id"],))
                        continue
                    if not os.path.exists(r["path"]):
                        conn.execute(
                            "UPDATE photos SET status='error', error=? WHERE id=?",
                            (_("Arquivo indisponível (HD desconectado?)"), r["id"]),
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
                    album_id, url = gp.create_album(album["title"])
                    conn.execute(
                        "UPDATE albums SET google_id=?, product_url=?, pending_rename=0 WHERE key=?",
                        (album_id, url, key),
                    )
                    novos_albuns.append(album["title"])
                    conn.commit()
                    log(_("Álbum criado: {titulo}").format(titulo=album["title"]))
                try:
                    results = gp.batch_create(album_id, pairs)
                except GooglePhotosError as e:
                    # álbum apagado no Google Fotos (ou de outra conta): cria de novo e tenta mais uma vez
                    if "album" not in str(e).lower():
                        raise
                    log(_("O álbum “{titulo}” não existe mais no Google Fotos; criando de novo.").format(
                        titulo=album["title"]))
                    album_id, url = gp.create_album(album["title"])
                    conn.execute("UPDATE albums SET google_id=?, product_url=? WHERE key=?", (album_id, url, key))
                    conn.commit()
                    results = gp.batch_create(album_id, pairs)
                for tok, photo_id in tokens.items():
                    ok, val = results.get(tok, (False, _("sem resposta do Google")))
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

    log(_("Envio concluído: {ok} enviados, {err} com erro").format(ok=enviados, err=erros))
    if novos_albuns:
        log(_("Álbuns novos: {lista}. Para compartilhar, use a aba Álbuns → "
              "“Abrir no Google Fotos para compartilhar”.").format(lista=", ".join(novos_albuns)))
    res = db.summary(conn, cfg)
    conn.close()
    res["enviados_agora"] = enviados
    res["erros_agora"] = erros
    res["albuns_novos"] = novos_albuns
    return res


def tentar_erros_novamente() -> int:
    conn = db.connect()
    n = conn.execute(
        "UPDATE photos SET status='classified', error=NULL WHERE status='error' AND media_item_id IS NULL"
    ).rowcount
    conn.commit()
    conn.close()
    return n
