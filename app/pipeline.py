"""Orquestra as etapas. Todas são idempotentes: podem ser interrompidas e retomadas."""
from __future__ import annotations

import os

from . import albums, classifier, db, grouper, reconcile, scanner
from .config import Config, wants_upload
from .google_photos import (BATCH_LIMIT, GooglePhotos, GooglePhotosError, NeedsReconnect, NotConnected,
                            QuotaExceeded)
from .i18n import _

# mensagem que versões antigas gravavam para arquivo de HD desconectado (português e inglês)
# limite do Google: um álbum aceita até 20.000 itens. Ao encher, o envio continua num álbum novo
# com o mesmo nome e um número: "Fotos 2023 (2)", "Fotos 2023 (3)"...
ALBUM_LIMIT = 20000

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


def enviar(cfg: Config, progress=_noop, log=_noop, stop=None, keys: list | None = None,
           folder: str | None = None) -> dict:
    """Envia o que está pendente. keys: só estes álbuns (ex.: ["ano-2023"]; inclui as continuações
    "Título (2)"...). folder: só os arquivos desta pasta. Sem filtro: tudo."""
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

    # álbuns que o FotoFaxina já criou no Google: reaproveita o de mesmo nome (ex.: depois de limpar o
    # histórico) e move fotos já enviadas que o usuário mandou para outro álbum
    try:
        albums.refresh(conn, gp, log)
        if cfg.reuse_same_name:
            albums.link_same_name(conn, log)
    except NeedsReconnect as e:
        log(str(e))
    except NotConnected:
        raise
    except Exception as e:  # a lista é um extra: sem ela, o envio segue normalmente
        log(_("Não consegui buscar a lista de álbuns do Google Fotos: {erro}").format(erro=e))
    albums.move_pinned_uploaded(conn, gp, log)

    # versões antigas marcavam como erro o que estava num HD desconectado: volta para a fila
    conn.execute("UPDATE photos SET status='classified', error=NULL WHERE status='error' "
                 "AND media_item_id IS NULL AND error IN (?, ?)", MISSING_ERRORS)
    rows = conn.execute(
        "SELECT * FROM photos WHERE status='classified' AND media_item_id IS NULL "
        "AND album_key IS NOT NULL ORDER BY album_key, taken_at"
    ).fetchall()
    rows = [r for r in rows if wants_upload(r, cfg)]
    if keys:
        wanted = set(keys)
        rows = [r for r in rows if r["album_key"] in wanted or r["album_key"].split("#")[0] in wanted]
    if folder:
        under = set(db.ids_under(conn, folder))
        rows = [r for r in rows if r["id"] in under]
    uploaded_hashes = {
        r[0] for r in conn.execute("SELECT sha256 FROM photos WHERE media_item_id IS NOT NULL")
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
    segments = []
    for key, items in by_album.items():
        segments.extend(_segments(conn, key, items, log))
    conn.commit()

    def fail(ids, msg):
        conn.executemany("UPDATE photos SET status='error', error=? WHERE id=?", [(msg[:500], i) for i in ids])
        for i in ids:  # o nome de cada arquivo fica no fotofaxina.log, mesmo se o histórico for limpo
            got = conn.execute("SELECT path FROM photos WHERE id=?", (i,)).fetchone()
            if got is not None:
                log(_("Não enviada: {arquivo} — {erro}").format(arquivo=got[0], erro=msg[:200]))

    try:
        for key, items in segments:
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
                        got = conn.execute("SELECT sha256 FROM photos WHERE id=?", (photo_id,)).fetchone()
                        if got is not None:  # o histórico pode ter sido limpo durante o envio
                            uploaded_hashes.add(got[0])
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


def _album_count(conn, key: str, row) -> int:
    local = conn.execute("SELECT COUNT(*) FROM photos WHERE album_key=? AND media_item_id IS NOT NULL",
                         (key,)).fetchone()[0]
    return max(local, (row["google_items"] or 0) if row is not None else 0)


def _segments(conn, key: str, items: list, log=_noop) -> list[tuple[str, list]]:
    """Divide os itens de um álbum para não passar do limite do Google: o que não cabe vai para
    "Título (2)", "Título (3)"... (criados no Google quando a primeira foto for enviada)."""
    base = conn.execute("SELECT * FROM albums WHERE key=?", (key,)).fetchone()
    if base is None:
        return [(key, items)]
    out, rest, n = [], list(items), 1
    while rest:
        k = key if n == 1 else f"{key}#{n}"
        row = base if n == 1 else conn.execute("SELECT * FROM albums WHERE key=?", (k,)).fetchone()
        if row is None:
            title = f"{base['title']} ({n})"
            conn.execute("INSERT INTO albums(key, title, start, end, custom_title) VALUES(?, ?, ?, ?, 1)",
                         (k, title, base["start"], base["end"]))
            log(_("O álbum “{titulo}” chegou ao limite de {limite} itens do Google; continuando em “{novo}”.")
                .format(titulo=base["title"], limite=f"{ALBUM_LIMIT:,}".replace(",", "."), novo=title))
            room = ALBUM_LIMIT
        else:
            room = ALBUM_LIMIT - _album_count(conn, k, row)
        if room > 0:
            take, rest = rest[:room], rest[room:]
            if k != key:
                conn.executemany("UPDATE photos SET album_key=? WHERE id=?", [(k, r["id"]) for r in take])
            out.append((k, take))
        n += 1
    return out


def _gp() -> GooglePhotos:
    gp = GooglePhotos()
    gp.connect(interactive=False)
    return gp


def buscar_albuns(progress=_noop, log=_noop, stop=None) -> int:
    """Traz a lista de álbuns que o FotoFaxina criou no Google Fotos."""
    gp = _gp()
    conn = db.connect()
    try:
        n = albums.refresh(conn, gp, log)
    finally:
        conn.close()
    log(_("{n} álbuns criados pelo FotoFaxina no Google Fotos.").format(n=n))
    return n


def criar_album(title: str) -> str:
    """Cria um álbum novo no Google Fotos e o coloca na lista. Retorna a chave local."""
    gp = _gp()
    conn = db.connect()
    try:
        return albums.create(conn, gp, title.strip()[:500])
    finally:
        conn.close()


def juntar_albuns(target_key: str, source_keys: list[str], progress=_noop, log=_noop, stop=None) -> dict:
    gp = _gp()
    conn = db.connect()
    try:
        return albums.merge(conn, gp, target_key, source_keys, progress, log, stop)
    finally:
        conn.close()


def conferir(root: str | None, cfg: Config, progress=_noop, log=_noop, stop=None) -> dict:
    """Conferir com o Google Fotos: analisa a pasta (se escolhida) e marca como enviado o que já
    está no Google Fotos. O que sobrar é o que falta enviar."""
    if root:
        res = processar(root, cfg, progress, log, stop)
        if res.get("parado"):
            return res
    gp = _gp()
    conn = db.connect()
    try:
        out = reconcile.reconcile(conn, gp, progress, log)
    finally:
        conn.close()
    grouper.group(cfg, log)
    conn = db.connect()
    out.update(db.summary(conn, cfg))
    if root:
        out["pasta"] = folder_summary(conn, root, cfg)
    conn.close()
    return out


def contar_erros() -> int:
    conn = db.connect()
    n = conn.execute("SELECT COUNT(*) FROM photos WHERE status='error' AND media_item_id IS NULL").fetchone()[0]
    conn.close()
    return n


def tentar_erros_novamente() -> int:
    conn = db.connect()
    n = conn.execute(
        "UPDATE photos SET status='classified', error=NULL WHERE status='error' AND media_item_id IS NULL"
    ).rowcount
    conn.commit()
    conn.close()
    return n
