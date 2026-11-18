"""Limpeza do HD: o usuário marca memes, prints, figurinhas e documentos e o app manda só o que foi
marcado para a LIXEIRA do sistema (dá para restaurar de lá). Nada é apagado de vez.

O que já foi enviado ao Google Fotos NÃO pode ser apagado pelo app: a API do Google não tem essa
função. Esses itens vão para uma lista (`google_cleanup`) que o usuário usa para apagar lá.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import db
from .config import APP_DIR, CATEGORIES
from .i18n import _

DELETABLE = ("meme", "print", "documento")  # nunca fotos pessoais, paisagens, vídeos ou "outro"
REPORT_PATH = APP_DIR / "apagar-no-google.txt"
_MARKS = ",".join("?" * len(DELETABLE))


def _gio() -> str | None:
    return shutil.which("gio") if sys.platform.startswith("linux") else None


def _trash(path: str) -> None:
    try:
        from send2trash import send2trash
    except ImportError:
        gio = _gio()  # Linux sem o módulo: usa a lixeira do sistema (GNOME/KDE/XFCE) pelo "gio trash"
        if not gio:
            raise
        r = subprocess.run([gio, "trash", "--", path], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise OSError((r.stderr or r.stdout or "gio trash falhou").strip())
        return
    send2trash(path)


def trash_error() -> str | None:
    """None se a lixeira do sistema pode ser usada; senão, o motivo (ex.: módulo não instalado)."""
    try:
        import send2trash  # noqa: F401
    except ImportError:
        if _gio():
            return None
        return _("O módulo send2trash não está instalado. Instale com: pip install send2trash "
                 "(ou: pip install -r requirements.txt) e abra o FotoFaxina de novo.")
    return None


def mark(conn, ids: list[int], flag: bool = True) -> int:
    """Marca (ou desmarca) para excluir. Só aceita as categorias de DELETABLE.
    Retorna quantos itens mudaram."""
    n = 0
    for i in ids:
        if flag:  # cópias (duplicatas) também podem; o original é protegido na hora de excluir
            n += conn.execute(f"UPDATE photos SET delete_mark=1 WHERE id=? AND "
                              f"(category IN ({_MARKS}) OR duplicate_of IS NOT NULL)",
                              (i, *DELETABLE)).rowcount
        else:
            n += conn.execute("UPDATE photos SET delete_mark=0 WHERE id=? AND delete_mark=1", (i,)).rowcount
    conn.commit()
    return n


def mark_identical_duplicates(conn) -> int:
    """Marca todas as cópias IDÊNTICAS (mesmo SHA-256 do original) cujo original não está marcado."""
    n = conn.execute(
        "UPDATE photos SET delete_mark=1 WHERE duplicate_of IS NOT NULL AND COALESCE(delete_mark,0)=0 "
        "AND sha256 IS NOT NULL AND duplicate_of IN (SELECT k.id FROM photos k "
        "WHERE k.sha256 = photos.sha256 AND COALESCE(k.delete_mark,0)=0)").rowcount
    conn.commit()
    return n


def _marked(conn) -> list:
    # a categoria é conferida de novo aqui: mudar a categoria depois de marcar não pode apagar uma foto
    return conn.execute(
        f"SELECT p.*, a.title AS album_title, k.path AS keeper_path, CASE WHEN k.delete_mark=1 AND (k.category IN ({_MARKS}) OR k.duplicate_of IS NOT NULL) "
        "THEN 1 ELSE 0 END AS keeper_marked "
        "FROM photos p LEFT JOIN albums a ON a.key = p.album_key LEFT JOIN photos k ON k.id = p.duplicate_of "
        f"WHERE p.delete_mark=1 AND (p.category IN ({_MARKS}) OR p.duplicate_of IS NOT NULL) "
        "ORDER BY p.id", (*DELETABLE, *DELETABLE)).fetchall()


def preview(conn) -> dict:
    rows = _marked(conn)
    return {"n": len(rows), "bytes": sum(r["size"] or 0 for r in rows),
            "no_google": sum(1 for r in rows if r["media_item_id"])}


def trash_marked(conn, progress=None, stop=None, trasher=None) -> dict:
    """Manda os itens marcados para a lixeira. Só tira do banco o que realmente foi para a lixeira
    (ou já não existia). Retorna contagens e as falhas."""
    if trasher is None:
        trasher = _trash
        erro = trash_error()
        if erro:  # sem a lixeira, não adianta tentar arquivo por arquivo
            return {"lixeira": 0, "bytes": 0, "no_google": 0, "ausentes": 0, "falhas": [],
                    "nao_encontrados": [], "parado": False, "erro": erro}
    progress = progress or (lambda *a: None)
    rows = _marked(conn)
    out = {"lixeira": 0, "bytes": 0, "no_google": 0, "ausentes": 0, "falhas": [], "nao_encontrados": [],
           "parado": False}
    gone: list = []
    for i, r in enumerate(rows, 1):
        if stop is not None and stop():
            out["parado"] = True
            break
        progress(i, len(rows), os.path.basename(r["path"]))
        path = r["path"]
        if r["duplicate_of"] is not None and not r["keeper_path"]:
            out["falhas"].append((path, _("o original desta cópia não está no histórico")))
            continue
        if r["duplicate_of"] is not None and (r["keeper_marked"] or not os.path.exists(r["keeper_path"])):
            # sempre sobra um exemplar: o original também está marcado ou não existe mais no disco
            out["falhas"].append((path, _("o original desta cópia está marcado para excluir ou não foi encontrado")))
            continue
        if not os.path.exists(path):
            if os.path.isdir(os.path.dirname(path)):
                out["ausentes"] += 1  # a pasta existe e o arquivo sumiu: alguém já o apagou
                gone.append(r)
            else:
                out["nao_encontrados"].append(path)  # pasta/HD fora do ar: não mexe no registro
            continue
        try:
            if r["size"] is not None and os.path.getsize(path) != r["size"]:
                out["falhas"].append((path, _("o arquivo mudou depois da análise")))
                continue
            trasher(path)
        except Exception as e:  # HD sem lixeira, somente leitura, em uso...
            out["falhas"].append((path, str(e)))
            continue
        out["lixeira"] += 1
        out["bytes"] += r["size"] or 0
        gone.append(r)
    now = datetime.now().isoformat(timespec="seconds")
    for r in gone:
        if r["media_item_id"]:
            out["no_google"] += 1
            conn.execute(
                "INSERT INTO google_cleanup(name, taken_at, width, height, category, album_title, "
                "media_item_id, trashed_at) VALUES(?,?,?,?,?,?,?,?)",
                (os.path.basename(r["path"]), r["taken_at"], r["width"], r["height"], r["category"],
                 r["album_title"], r["media_item_id"], now))
    conn.commit()
    if gone:
        db.forget(conn, [r["id"] for r in gone])
    return out


def google_pending(conn) -> list:
    return conn.execute("SELECT * FROM google_cleanup ORDER BY album_title, taken_at, name").fetchall()


def clear_google_pending(conn) -> int:
    n = conn.execute("DELETE FROM google_cleanup").rowcount
    conn.commit()
    return n


def report_text(rows: list) -> str:
    """Lista para apagar no Google Fotos, agrupada por álbum (dá para abrir o álbum e apagar em lote)."""
    lines = [_("Itens que o FotoFaxina excluiu do HD mas que continuam no Google Fotos."),
             _("O Google não deixa aplicativos apagarem fotos: apague-os você, em photos.google.com."),
             _("Dica: abra o álbum, selecione os itens da lista (pela data) e use a lixeira."), ""]
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["album_title"] or _("(sem álbum)"), []).append(r)
    for title in sorted(groups):
        items = groups[title]
        lines.append(_("Álbum: {album} — {n} item(ns)").format(album=title, n=len(items)))
        for r in items:
            dims = f"{r['width']}x{r['height']}" if r["width"] and r["height"] else ""
            cat = _(CATEGORIES[r["category"]]) if r["category"] in CATEGORIES else ""
            lines.append("  - " + "  ".join(x for x in (r["name"], (r["taken_at"] or "")[:19], dims, cat) if x))
        lines.append("")
    return "\n".join(lines)


def write_report(conn, path: Path | None = None) -> Path | None:
    rows = google_pending(conn)
    if not rows:
        return None
    path = path or REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_text(rows), encoding="utf-8")
    return path
