"""Conferir com o Google Fotos: descobre quais fotos analisadas já estão no Google Fotos.

Serve, por exemplo, depois de limpar o histórico: o FotoFaxina não sabe mais o que foi enviado,
mas o Google sabe. A API mostra (só) o que o próprio app enviou, com nome do arquivo, dimensões e
data. A comparação usa nome + dimensões (+ data, para desempatar arquivos com o mesmo nome, como
IMG_0001.jpg de câmeras ou anos diferentes).
"""
from __future__ import annotations

import os
from datetime import datetime

from .i18n import _


def _google_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except ValueError:
        return None


def _hours(a: datetime | None, b: datetime | None) -> float:
    if a is None or b is None:
        return 10**6
    return abs((a - b).total_seconds()) / 3600


def reconcile(conn, gp, progress=None, log=None) -> dict:
    """Marca como enviadas as fotos que já estão no Google Fotos. Não envia nada."""
    from . import albums

    progress = progress or (lambda *a: None)
    log = log or (lambda *a: None)
    stage = _("Conferindo com o Google Fotos")
    progress(stage, 0, 0, "")
    remote = gp.list_media_items()
    log(_("{n} fotos/vídeos enviados pelo FotoFaxina encontrados no Google Fotos.").format(n=len(remote)))

    # em qual álbum cada item está (para fotos novas continuarem indo para os mesmos álbuns)
    in_album: dict[str, str] = {}
    try:
        albums.refresh(conn, gp, log)
        rows = conn.execute("SELECT key, google_id FROM albums WHERE google_id IS NOT NULL "
                            "ORDER BY key LIKE 'g-%'").fetchall()  # agrupamentos do app primeiro
        seen: set[str] = set()
        for i, a in enumerate(rows, 1):
            if a["google_id"] in seen:
                continue
            seen.add(a["google_id"])
            progress(stage, i, len(rows), a["key"])
            for mid in gp.album_items(a["google_id"]):
                in_album.setdefault(mid, a["key"])
    except Exception as e:  # sem os álbuns a conferência ainda funciona
        log(_("Não consegui ler os álbuns: {erro}").format(erro=e))

    by_name: dict[str, list[dict]] = {}
    for m in remote:
        m["dt"] = _google_time(m.get("creationTime"))
        by_name.setdefault(m["filename"].lower(), []).append(m)

    # quantas vezes cada nome aparece no HD (todas as análises): nome único dos dois lados = mesmo arquivo
    local_names: dict[str, int] = {}
    for (path,) in conn.execute("SELECT path FROM photos"):
        n = os.path.basename(path).lower()
        local_names[n] = local_names.get(n, 0) + 1
    already = {r[0] for r in conn.execute("SELECT media_item_id FROM photos WHERE media_item_id IS NOT NULL")}

    local = conn.execute(
        "SELECT id, path, width, height, taken_at, is_video FROM photos WHERE media_item_id IS NULL "
        "AND duplicate_of IS NULL"
    ).fetchall()
    found = 0
    for r in local:
        name = os.path.basename(r["path"]).lower()
        cands = [m for m in by_name.get(name, []) if m["id"] not in already]
        if not cands:
            continue
        dt = datetime.fromisoformat(r["taken_at"]) if r["taken_at"] else None
        if not r["is_video"] and r["width"] and r["height"]:
            dims = {(r["width"], r["height"]), (r["height"], r["width"])}  # pode estar girada
            cands = [m for m in cands if (m["width"], m["height"]) in dims or not m["width"]]
            if not cands:
                continue
        if len(cands) == 1 and local_names.get(name, 0) == 1:
            best = cands[0]  # nome único no HD e no Google: é o mesmo arquivo (vídeos inclusive)
        else:
            # nomes repetidos (ex.: IMG_0001 de câmeras diferentes): desempata pela data
            best = min(cands, key=lambda m: _hours(m["dt"], dt))
            if _hours(best["dt"], dt) > 48:
                continue  # nenhum com data próxima: não arrisca
        conn.execute(
            "UPDATE photos SET media_item_id=?, status='uploaded', error=NULL, "
            "album_key=COALESCE(?, album_key) WHERE id=?",
            (best["id"], in_album.get(best["id"]), r["id"]),
        )
        already.add(best["id"])
        found += 1
    conn.commit()
    log(_("{n} fotos da análise já estavam no Google Fotos e foram marcadas como enviadas.").format(n=found))
    return {"no_google": len(remote), "marcadas": found}

