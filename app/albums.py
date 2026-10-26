"""Álbuns do Google Fotos criados pelo FotoFaxina: buscar, criar, escolher destino e juntar.

Desde 2025 a API do Google só deixa um app ver e mexer nos álbuns (e fotos) que ele mesmo criou.
Álbuns feitos à mão no Google Fotos não aparecem aqui.

Na tabela local `albums`, um álbum trazido do Google que não corresponde a nenhum agrupamento
do app (evento/mês/ano) recebe a chave "g-<id do Google>".
"""
from __future__ import annotations

from .i18n import _


def google_key(google_id: str) -> str:
    return f"g-{google_id}"


def refresh(conn, gp, log=None) -> int:
    """Traz do Google a lista de álbuns criados pelo app e atualiza a tabela local.
    Pode levantar NeedsReconnect (login antigo, sem a permissão de leitura)."""
    log = log or (lambda *a: None)
    remote = gp.list_albums()
    ignored = {r[0] for r in conn.execute("SELECT google_id FROM ignored_albums")}
    linked = {r[0] for r in conn.execute("SELECT google_id FROM albums WHERE google_id IS NOT NULL")}
    novos = 0
    for a in remote:
        if a["id"] in ignored:
            continue
        if a["id"] in linked:
            # o nome pode ter sido mudado no próprio Google Fotos
            conn.execute(
                "UPDATE albums SET google_items=?, product_url=COALESCE(?, product_url), "
                "title=CASE WHEN pending_rename=1 THEN title ELSE ? END WHERE google_id=?",
                (a["mediaItemsCount"], a["productUrl"], a["title"] or "—", a["id"]),
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO albums(key, title, google_id, product_url, custom_title, google_items) "
                "VALUES(?, ?, ?, ?, 1, ?)",
                (google_key(a["id"]), a["title"] or "—", a["id"], a["productUrl"], a["mediaItemsCount"]),
            )
            novos += 1
    conn.commit()
    if novos:
        log(_("{n} álbuns do Google Fotos adicionados à lista.").format(n=novos))
    return len(remote)


def _absorb(conn, key: str, other_key: str) -> None:
    """Junta, no banco local, o álbum other_key (trazido do Google) dentro de key."""
    conn.execute("UPDATE photos SET album_key=? WHERE album_key=?", (key, other_key))
    conn.execute("UPDATE photos SET album_pin=? WHERE album_pin=?", (key, other_key))
    if other_key.startswith("g-"):
        conn.execute("DELETE FROM albums WHERE key=?", (other_key,))


def link_same_name(conn, log=None) -> int:
    """Álbum ainda não enviado (ex.: "Fotos 2023" depois de limpar o histórico) com o mesmo nome de
    um álbum que o FotoFaxina já criou no Google: usa o que já existe, em vez de criar outro."""
    log = log or (lambda *a: None)
    n = 0
    for a in conn.execute("SELECT key, title FROM albums WHERE google_id IS NULL").fetchall():
        match = conn.execute(
            "SELECT key, google_id, product_url, google_items FROM albums WHERE google_id IS NOT NULL "
            "AND lower(trim(title)) = lower(trim(?)) AND google_id NOT IN (SELECT google_id FROM ignored_albums) "
            "ORDER BY COALESCE(google_items, 0) DESC LIMIT 1",
            (a["title"],),
        ).fetchone()
        if match is None:
            continue
        conn.execute("UPDATE albums SET google_id=?, product_url=?, google_items=?, pending_rename=0 WHERE key=?",
                     (match["google_id"], match["product_url"], match["google_items"], a["key"]))
        _absorb(conn, a["key"], match["key"])
        log(_("Usando o álbum “{titulo}” que já existe no Google Fotos.").format(titulo=a["title"]))
        n += 1
    conn.commit()
    return n


def create(conn, gp, title: str) -> str:
    """Cria o álbum no Google Fotos agora e já o coloca na lista. Retorna a chave local."""
    gid, url = gp.create_album(title)
    key = google_key(gid)
    conn.execute(
        "INSERT OR REPLACE INTO albums(key, title, google_id, product_url, custom_title, google_items) "
        "VALUES(?, ?, ?, ?, 1, 0)", (key, title, gid, url))
    conn.commit()
    return key


def google_albums(conn) -> list:
    """Álbuns que existem no Google (para escolher destino), um por álbum do Google."""
    rows = conn.execute(
        "SELECT a.key, a.title, a.google_id, a.product_url, a.google_items, COUNT(p.id) AS local "
        "FROM albums a LEFT JOIN photos p ON p.album_key = a.key "
        "WHERE a.google_id IS NOT NULL GROUP BY a.key ORDER BY lower(a.title)"
    ).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["google_id"] not in seen:
            seen.add(r["google_id"])
            out.append(r)
    return out


def pin(conn, ids: list[int], key: str) -> tuple[int, int]:
    """Fixa o álbum de destino das fotos escolhidas. As ainda não enviadas vão para ele no próximo
    envio; as já enviadas são MOVIDAS para ele no próximo envio. Retorna (a_enviar, a_mover)."""
    a_enviar = a_mover = 0
    for i in ids:
        r = conn.execute("SELECT media_item_id, duplicate_of FROM photos WHERE id=?", (i,)).fetchone()
        if r is None or r["duplicate_of"] is not None:
            continue
        if r["media_item_id"]:
            conn.execute("UPDATE photos SET album_pin=? WHERE id=?", (key, i))
            a_mover += 1
        else:
            conn.execute("UPDATE photos SET album_pin=?, album_key=?, decision='upload' WHERE id=?", (key, key, i))
            a_enviar += 1
    conn.commit()
    return a_enviar, a_mover


def unpin(conn, ids: list[int]) -> None:
    conn.executemany("UPDATE photos SET album_pin=NULL WHERE id=?", [(i,) for i in ids])
    conn.commit()


def move_pinned_uploaded(conn, gp, log=None) -> int:
    """Fotos já enviadas que o usuário mandou para outro álbum: adiciona no novo e tira do antigo."""
    log = log or (lambda *a: None)
    rows = conn.execute(
        "SELECT p.id, p.media_item_id, p.album_key, p.album_pin, n.google_id AS new_gid, o.google_id AS old_gid "
        "FROM photos p JOIN albums n ON n.key = p.album_pin LEFT JOIN albums o ON o.key = p.album_key "
        "WHERE p.media_item_id IS NOT NULL AND p.album_pin IS NOT NULL "
        "AND p.album_pin != COALESCE(p.album_key, '') AND n.google_id IS NOT NULL"
    ).fetchall()
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((r["album_pin"], r["new_gid"], r["old_gid"]), []).append(r)
    moved = 0
    for (pin_key, new_gid, old_gid), items in groups.items():
        media = [r["media_item_id"] for r in items]
        try:
            gp.add_to_album(new_gid, media)
        except Exception as e:
            log(_("Não consegui colocar {n} fotos no álbum escolhido: {erro}").format(n=len(media), erro=e))
            continue
        if old_gid and old_gid != new_gid:
            try:
                gp.remove_from_album(old_gid, media)
            except Exception as e:  # ficam nos dois álbuns: não é grave
                log(_("As fotos foram para o novo álbum, mas não consegui tirá-las do antigo: {erro}").format(erro=e))
        conn.executemany("UPDATE photos SET album_key=? WHERE id=?", [(pin_key, r["id"]) for r in items])
        conn.commit()
        moved += len(items)
    if moved:
        log(_("{n} fotos já enviadas foram movidas para o álbum escolhido.").format(n=moved))
    return moved


def merge(conn, gp, target_key: str, source_keys: list[str], progress=None, log=None, stop=None) -> dict:
    """Junta álbuns criados pelo FotoFaxina: as fotos dos outros vão para o álbum de destino e os
    outros ficam vazios (a API não permite apagar álbuns: isso é feito à mão no Google Fotos)."""
    progress = progress or (lambda *a: None)
    log = log or (lambda *a: None)
    target = conn.execute("SELECT * FROM albums WHERE key=?", (target_key,)).fetchone()
    if target is None or not target["google_id"]:
        raise ValueError(_("O álbum de destino ainda não existe no Google Fotos."))
    tgid = target["google_id"]
    already = set(gp.album_items(tgid))
    out = {"movidas": 0, "falhas": 0, "vazios": [], "nao_vazios": []}
    stage = _("Juntando álbuns")
    for n, key in enumerate(source_keys, 1):
        if stop is not None and stop.is_set():
            break
        src = conn.execute("SELECT * FROM albums WHERE key=?", (key,)).fetchone()
        if src is None or not src["google_id"] or src["google_id"] == tgid:
            continue
        progress(stage, n, len(source_keys), src["title"])
        items = gp.album_items(src["google_id"])
        new = [m for m in items if m not in already]
        ok: list[str] = []
        for i in range(0, len(new), 50):
            chunk = new[i:i + 50]
            try:
                gp.add_to_album(tgid, chunk)
                ok.extend(chunk)
            except Exception:  # um item que o app não criou derruba o lote: tenta um por um
                for m in chunk:
                    try:
                        gp.add_to_album(tgid, [m])
                        ok.append(m)
                    except Exception:
                        out["falhas"] += 1
        already.update(ok)
        movable = [m for m in items if m in already]
        if movable:
            try:
                gp.remove_from_album(src["google_id"], movable)
            except Exception as e:
                log(_("Não consegui esvaziar “{titulo}”: {erro}").format(titulo=src["title"], erro=e))
        out["movidas"] += len(ok)
        conn.execute("UPDATE photos SET album_key=? WHERE album_key=?", (target_key, key))
        conn.execute("UPDATE photos SET album_pin=? WHERE album_pin=?", (target_key, key))
        if len(movable) == len(items):
            conn.execute("INSERT OR IGNORE INTO ignored_albums(google_id) VALUES(?)", (src["google_id"],))
            conn.execute("DELETE FROM albums WHERE key=?", (key,))
            from .db import album_url

            out["vazios"].append((src["title"], album_url(src)))
        else:
            out["nao_vazios"].append(src["title"])
        conn.commit()
        log(_("“{origem}” → “{destino}”: {n} itens.").format(origem=src["title"], destino=target["title"], n=len(ok)))
    conn.execute("UPDATE albums SET google_items=? WHERE key=?", (len(already), target_key))
    conn.commit()
    return out
