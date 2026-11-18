"""Limpeza do HD: o usuário marca o que quer excluir (qualquer categoria) e o app manda só o que foi
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
from .scanner import is_better
from .config import APP_DIR, CATEGORIES
from .i18n import _

PERSONAL = ("foto", "paisagem", "video")  # qualquer categoria pode ser marcada; estas pedem aviso extra
REPORT_PATH = APP_DIR / "apagar-no-google.txt"


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
    """Marca (ou desmarca) para excluir. Qualquer categoria; nada é apagado até "Excluir marcadas".
    Retorna quantos itens mudaram."""
    n = 0
    for i in ids:
        if flag:  # qualquer categoria; o original de uma cópia é protegido na hora de excluir
            n += conn.execute("UPDATE photos SET delete_mark=1 WHERE id=?", (i,)).rowcount
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
    return conn.execute(
        "SELECT p.*, a.title AS album_title, k.path AS keeper_path, COALESCE(k.delete_mark, 0) AS keeper_marked, "
        "k.width AS k_width, k.height AS k_height, k.size AS k_size "
        "FROM photos p LEFT JOIN albums a ON a.key = p.album_key LEFT JOIN photos k ON k.id = p.duplicate_of "
        "WHERE p.delete_mark=1 ORDER BY p.id").fetchall()


def preview(conn) -> dict:
    rows = _marked(conn)
    return {"n": len(rows), "bytes": sum(r["size"] or 0 for r in rows),
            "no_google": sum(1 for r in rows if r["media_item_id"]),
            "pessoais": sum(1 for r in rows if r["category"] in PERSONAL and r["duplicate_of"] is None)}


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
        if r["duplicate_of"] is not None and is_better(
                r, {"width": r["k_width"], "height": r["k_height"], "size": r["k_size"]}):
            # a "cópia" tem qualidade bem melhor que o original mantido: excluí-la perderia o melhor arquivo
            out["falhas"].append((path, _("esta cópia tem qualidade melhor que o original mantido")))
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


def worse_sent(conn) -> list:
    """Versões PIORES já no Google Fotos cuja versão melhor também já foi enviada: podem ser apagadas lá."""
    return conn.execute(
        "SELECT k.id AS id, k.path AS path, k.taken_at, k.width, k.height, k.category, a.title AS album_title, "
        "m.path AS better_path, m.width AS better_w, m.height AS better_h "
        "FROM photos m JOIN photos k ON k.id = m.supersedes LEFT JOIN albums a ON a.key = k.album_key "
        "WHERE m.media_item_id IS NOT NULL AND k.media_item_id IS NOT NULL "
        "ORDER BY a.title, k.taken_at, k.path").fetchall()


def clear_google_pending(conn) -> int:
    """O usuário já apagou tudo da lista no Google Fotos: limpa a lista e esquece as versões piores."""
    worse = [r["id"] for r in worse_sent(conn)]
    n = conn.execute("DELETE FROM google_cleanup").rowcount + len(worse)
    conn.executemany("UPDATE photos SET supersedes=NULL WHERE supersedes=?", [(i,) for i in worse])
    conn.commit()
    if worse:
        db.forget(conn, worse)  # a próxima análise as trata como cópias da versão melhor
    return n


def _group_lines(rows, key, line) -> list[str]:
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["album_title"] or _("(sem álbum)"), []).append(r)
    out = []
    for title in sorted(groups):
        out.append(_("Álbum: {album} — {n} item(ns)").format(album=title, n=len(groups[title])))
        out += ["  - " + line(r) for r in groups[title]]
        out.append("")
    return out


def report_text(rows: list, worse: list | None = None) -> str:
    """Lista para apagar no Google Fotos, agrupada por álbum (dá para abrir o álbum e apagar em lote)."""
    lines = [_("O Google não deixa aplicativos apagarem fotos: apague os itens abaixo você, em photos.google.com."),
             _("Dica: abra o álbum, selecione os itens da lista (pela data) e use a lixeira."), ""]
    if rows:
        lines += [_("== Excluídos do HD, mas ainda no Google Fotos =="), ""]

        def line(r):
            dims = f"{r['width']}x{r['height']}" if r["width"] and r["height"] else ""
            cat = _(CATEGORIES[r["category"]]) if r["category"] in CATEGORIES else ""
            return "  ".join(x for x in (r["name"], (r["taken_at"] or "")[:19], dims, cat) if x)

        lines += _group_lines(rows, "album_title", line)
    if worse:
        lines += [_("== Versões de qualidade PIOR no Google (a melhor já foi enviada) =="), ""]

        def wline(r):
            dims = f"{r['width']}x{r['height']}" if r["width"] and r["height"] else ""
            best = f"{os.path.basename(r['better_path'])} {r['better_w']}x{r['better_h']}"
            return "  ".join(x for x in (os.path.basename(r["path"]), (r["taken_at"] or "")[:19], dims) if x) + \
                "  ->  " + _("manter: {melhor}").format(melhor=best)

        lines += _group_lines(worse, "album_title", wline)
    return "\n".join(lines)


def write_report(conn, path: Path | None = None) -> Path | None:
    rows, worse = google_pending(conn), worse_sent(conn)
    if not rows and not worse:
        return None
    path = path or REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_text(rows, worse), encoding="utf-8")
    return path
