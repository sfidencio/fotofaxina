"""Leitura e restauração da lixeira (padrão FreeDesktop: ~/.local/share/Trash e <HD>/.Trash-UID).

SÓ LÊ e RESTAURA: este módulo nunca apaga nada da lixeira. Cada item tem um arquivo em `files/` e um
`.trashinfo` em `info/` com o caminho original (relativo à raiz do HD, ou absoluto na lixeira da pasta
pessoal) e a data da exclusão.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote

MEDIA_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".bmp", ".tif", ".tiff",
             ".mp4", ".mov", ".3gp", ".avi", ".mkv", ".m4v"}


def supported() -> bool:
    return sys.platform.startswith("linux")


def _is_trash(d: Path) -> bool:
    return (d / "files").is_dir() and (d / "info").is_dir()


def find_trashes() -> list[dict]:
    """Lixeiras encontradas: a da pasta pessoal e a de cada HD montado. {dir, topdir, label}."""
    if not supported():
        return []
    found: list[dict] = []
    home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "Trash"
    if _is_trash(home):
        found.append({"dir": home, "topdir": None, "label": "Pasta pessoal"})
    try:
        import psutil

        mounts = [p.mountpoint for p in psutil.disk_partitions(all=True)]
    except Exception:
        mounts = []
    uid = os.getuid()
    seen = {str(home)}
    for mp in sorted(set(mounts)):
        if mp.startswith(("/proc", "/sys", "/dev", "/snap")) or mp == "/":
            continue
        top = Path(mp)
        for cand in (top / f".Trash-{uid}", top / ".Trash" / str(uid)):
            try:
                if str(cand) not in seen and _is_trash(cand):
                    seen.add(str(cand))
                    found.append({"dir": cand, "topdir": top, "label": top.name or str(top)})
            except OSError:
                continue
    return found


def _parse_info(path: str) -> tuple[str | None, str]:
    orig, date = None, ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("Path="):
                orig = unquote(line[5:].strip())
            elif line.startswith("DeletionDate="):
                date = line[13:].strip()
    return orig, date


def _read_one(args) -> dict | None:
    e_path, name, d, top = args
    try:
        orig, date = _parse_info(e_path)
    except OSError:
        return None
    if not orig:
        return None
    if not os.path.isabs(orig) and top is not None:
        orig = os.path.join(top, orig)
    src = d / "files" / name
    try:
        st = os.lstat(src)
    except OSError:
        return None  # o arquivo não está mais na lixeira
    is_dir = os.path.isdir(src) and not os.path.islink(src)
    return {"name": name, "orig": os.path.normpath(orig), "deleted": date,
            "size": 0 if is_dir else st.st_size, "is_dir": is_dir,
            "media": os.path.splitext(name)[1].lower() in MEDIA_EXT}


def list_items(tr: dict, progress=None, stop=None) -> list[dict]:
    """Itens da lixeira: {name, orig, deleted, size, is_dir, media}. Não altera nada.
    Lê em paralelo: em HD externo (NTFS/FUSE) cada arquivo pequeno custa uma ida ao disco."""
    from concurrent.futures import ThreadPoolExecutor

    d, top = Path(tr["dir"]), tr["topdir"]
    entries = [e for e in os.scandir(d / "info") if e.name.endswith(".trashinfo")]
    total = len(entries)
    jobs = [(e.path, e.name[: -len(".trashinfo")], d, top) for e in entries]
    items: list[dict] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        for i, it in enumerate(pool.map(_read_one, jobs, chunksize=64), 1):
            if stop is not None and stop():
                break
            if it:
                items.append(it)
            if progress and i % 1000 == 0:
                progress(i, total)
    if progress:
        progress(total, total)
    return items


def restore(tr: dict, items: list[dict], progress=None, stop=None) -> dict:
    """Devolve os itens ao caminho original. NUNCA sobrescreve (se o destino existe, pula) e só
    mexe dentro da raiz do HD da lixeira."""
    d, top = Path(tr["dir"]), tr["topdir"]
    out = {"restaurados": [], "existentes": [], "faltando": [], "falhas": [], "parado": False}
    for i, it in enumerate(items, 1):
        if stop is not None and stop():
            out["parado"] = True
            break
        if progress:
            progress(i, len(items), os.path.basename(it["orig"]))
        src, info = d / "files" / it["name"], d / "info" / (it["name"] + ".trashinfo")
        dest = it["orig"]
        if not os.path.lexists(src):
            out["faltando"].append(dest)
            continue
        if top is not None:
            root = os.path.realpath(top)
            if not os.path.realpath(os.path.dirname(dest)).startswith(root + os.sep) and \
                    os.path.realpath(os.path.dirname(dest)) != root:
                # "Path=" com ".." que sairia da raiz do HD: não mexe
                out["falhas"].append((dest, "fora da raiz do HD"))
                continue
            if not os.path.isdir(root):
                out["falhas"].append((dest, "HD não está montado"))
                continue
        if os.path.lexists(dest):
            out["existentes"].append(dest)
            continue
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(str(src), dest)
            try:
                os.remove(info)
            except OSError:
                pass
            out["restaurados"].append(it)
        except Exception as e:
            out["falhas"].append((dest, str(e)))
    return out
