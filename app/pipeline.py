"""Orquestra as etapas. Todas são idempotentes: podem ser interrompidas e retomadas."""
from __future__ import annotations

import os

from . import classifier, db, grouper, scanner
from .config import Config, wants_upload
from .google_photos import BATCH_LIMIT, GooglePhotos, GooglePhotosError, NotConnected, QuotaExceeded
from .i18n import _

# mensagem que versões antigas gravavam para arquivo de HD desconectado (português e inglês)
MISSING_ERRORS = ("Arquivo indisponível (HD desconectado?)", "File unavailable (drive disconnected?)")


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
    rows = db.rows_under(conn, root, "SELECT p.*, k.media_item_id AS keeper_media FROM photos p "
                                     "LEFT JOIN photos k ON k.id = p.duplicate_of")
    out = {"total": len(rows), "ja_no_google": 0, "repetidas": 0, "a_enviar": 0, "fora": 0}
    for r in rows:
        if r["media_item_id"] or r["keeper_media"]:
            out["ja_no_google"] += 1
        elif r["duplicate_of"] is not None:
            out["repetidas"] += 1
        elif r["status"] == "classified" and wants_upload(r, cfg):
            out["a_enviar"] += 1
        else:
            out["fora"] += 1
    return out


def _summary(cfg: Config) -> dict:
    conn = db.connect()
    res = db.summary(conn, cfg)
    conn.close()
    return res


def reagrupar(cfg: Config, progress=_noop, log=_noop, stop=None) -> dict:
    grouper.group(cfg, log)
    return _summary(cfg)


def conectar_google(progress=_noop, log=_noop, stop=None) -> bool:
    GooglePhotos().connect(interactive=True)
    log(_("Conta Google conectada."))
    return True


def enviar(cfg: Config, progress=_noop, log=_noop, stop=None) -> dict:
    # itens que ficaram pendentes (ex.: marcados como "Não é duplicata" na Revisão)
    classifier.classify(cfg, progress, log, stop)
    if stop is not None and stop.is_set():
        return {**_summary(cfg), "enviados_agora": 0, "erros_agora": 0, "albuns_novos": []}
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

    # versões antigas marcavam como erro o que estava num HD desconectado: volta para a fila
    conn.execute("UPDATE photos SET status='classified', error=NULL WHERE status='error' "
                 "AND media_item_id IS NULL AND error IN (?, ?)", MISSING_ERRORS)
    rows = conn.execute(
        "SELECT * FROM photos WHERE status='classified' AND media_item_id IS NULL "
        "AND album_key IS NOT NULL ORDER BY album_key, taken_at"
    ).fetchall()
    rows = [r for r in rows if wants_upload(r, cfg)]
    uploaded_hashes = {
        r[0] for r in conn.execute("SELECT sha256 FROM photos WHERE media_item_id IS NOT NULL "
                                   "UNION SELECT sha256 FROM uploaded")
    }
    total = len(rows)
    log(_("{n} itens para enviar").format(n=total))
    enviados = erros = ausentes = 0
    done = 0
    novos_albuns: list[str] = []
    quota: str | None = None

    by_album: dict[str, list] = {}
    for r in rows:
        by_album.setdefault(r["album_key"], []).append(r)

    def fail(ids, msg):
        conn.executemany("UPDATE photos SET status='error', error=? WHERE id=?", [(msg[:500], i) for i in ids])

    try:
        for key, items in by_album.items():
            if stop is not None and stop.is_set() or quota:
                break
            album = conn.execute("SELECT * FROM albums WHERE key=?", (key,)).fetchone()
            if album is None:  # histórico limpo enquanto o envio rodava
                continue
            album_id = album["google_id"]
            for start in range(0, len(items), BATCH_LIMIT):
                if stop is not None and stop.is_set() or quota:
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
                        # HD de outra análise que não está plugado agora: fica na fila, sem erro
                        ausentes += 1
                        continue
                    try:
                        tok = gp.upload_bytes(r["path"], r["mime"])
                    except QuotaExceeded as e:
                        quota = str(e)  # cria no Google o que já subiu neste lote e para
                        break
                    except NotConnected:
                        raise  # login expirou: não adianta tentar os outros
                    except Exception as e:
                        fail([r["id"]], str(e))
                        erros += 1
                        continue
                    tokens[tok] = r["id"]
                    pairs.append((tok, os.path.basename(r["path"])))
                if not pairs:
                    conn.commit()
                    continue
                try:
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
                    except QuotaExceeded:
                        raise
                    except GooglePhotosError as e:
                        # álbum apagado no Google Fotos (ou de outra conta): cria de novo e tenta mais uma vez
                        if "album" not in str(e).lower():
                            raise
                        log(_("O álbum “{titulo}” não existe mais no Google Fotos; criando de novo.").format(
                            titulo=album["title"]))
                        album_id, url = gp.create_album(album["title"])
                        conn.execute("UPDATE albums SET google_id=?, product_url=? WHERE key=?",
                                     (album_id, url, key))
                        conn.commit()
                        results = gp.batch_create(album_id, pairs)
                except QuotaExceeded as e:
                    quota = str(e)  # os itens deste lote continuam na fila para amanhã
                    break
                except NotConnected:
                    raise
                except Exception as e:
                    # falha de rede ou do Google neste lote: marca o lote e segue com os outros
                    log(_("Falha ao criar {n} itens no Google Fotos: {erro}").format(n=len(tokens), erro=e))
                    fail(list(tokens.values()), str(e))
                    erros += len(tokens)
                    conn.commit()
                    continue
                for tok, photo_id in tokens.items():
                    ok, val = results.get(tok, (False, _("sem resposta do Google")))
                    if ok:
                        conn.execute(
                            "UPDATE photos SET status='uploaded', media_item_id=?, error=NULL WHERE id=?",
                            (val, photo_id),
                        )
                        sha = conn.execute("SELECT sha256 FROM photos WHERE id=?", (photo_id,)).fetchone()[0]
                        db.remember_upload(conn, sha, val, key)
                        uploaded_hashes.add(sha)
                        enviados += 1
                    else:
                        fail([photo_id], val)
                        erros += 1
                conn.commit()
    finally:
        conn.commit()

    if quota:
        log(quota)
    if ausentes:
        log(_("{n} itens são de um HD ou pasta que não está conectado agora; serão enviados quando "
              "estiver.").format(n=ausentes))
    log(_("Envio concluído: {ok} enviados, {err} com erro").format(ok=enviados, err=erros))
    if novos_albuns:
        log(_("Álbuns novos: {lista}. Para compartilhar, use a aba Álbuns → "
              "“Abrir no Google Fotos para compartilhar”.").format(lista=", ".join(novos_albuns)))
    res = db.summary(conn, cfg)
    conn.close()
    res["enviados_agora"] = enviados
    res["erros_agora"] = erros
    res["ausentes_agora"] = ausentes
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
