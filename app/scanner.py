"""Varre o HD/pasta, calcula hashes, lê EXIF e marca duplicatas."""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime

from PIL import Image, ImageOps

try:  # fotos HEIC de iPhone
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pass

from . import db
from .i18n import _
from .phash import phash

Image.MAX_IMAGE_PIXELS = None

PHOTO_EXT = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".heic": "image/heic",
    ".heif": "image/heif", ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
    ".tif": "image/tiff", ".tiff": "image/tiff",
}
VIDEO_EXT = {
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/x-m4v", ".3gp": "video/3gpp",
    ".avi": "video/x-msvideo", ".mkv": "video/x-matroska", ".mts": "video/mp2t", ".wmv": "video/x-ms-wmv",
}

WHATSAPP_RE = re.compile(r"^(IMG|VID|STK|PTT)-(\d{8})-WA\d+", re.I)
SCREENSHOT_RE = re.compile(r"(screenshot|screen[ _-]?shot|captura[ _-]de[ _-]tela|^print[ _-]?\d)", re.I)
DATE_PATTERNS = [
    # 20231224_153012, 20231224-153012, 2023-12-24 15.30.12
    re.compile(r"(?<!\d)((?:19|20)\d{2})[-_.]?(\d{2})[-_.]?(\d{2})[ _\-T]?(\d{2})[-_.:]?(\d{2})[-_.:]?(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)((?:19|20)\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)"),
]
BLANK_HASHES = {"0000000000000000", "ffffffffffffffff", "8000000000000000"}


def date_from_name(name: str) -> datetime | None:
    for pat in DATE_PATTERNS:
        for m in pat.finditer(name):
            try:
                dt = datetime(*[int(x) for x in m.groups()])
            except ValueError:
                continue
            if 1990 <= dt.year <= datetime.now().year + 1:
                return dt
    return None


def iter_media(root: str, ignore_dirs: list[str]):
    ignore = {d.lower() for d in ignore_dirs}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() not in ignore]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext in PHOTO_EXT or ext in VIDEO_EXT:
                yield os.path.join(dirpath, name)


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _exif_info(img: Image.Image) -> tuple[datetime | None, str | None]:
    try:
        exif = img.getexif()
    except Exception:
        return None, None
    if not exif:
        return None, None
    camera = exif.get(272)  # Model
    make = exif.get(271)
    if camera and make and not str(camera).lower().startswith(str(make).lower()):
        camera = f"{make} {camera}"
    raw = None
    try:
        raw = exif.get_ifd(0x8769).get(36867)  # DateTimeOriginal
    except Exception:
        pass
    raw = raw or exif.get(306)  # DateTime
    taken = None
    if raw:
        try:
            taken = datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S")
        except ValueError:
            taken = None
    return taken, (str(camera).strip("\x00 ").strip() or None) if camera else None


def analyze(path: str, st: os.stat_result) -> dict:
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    is_video = ext in VIDEO_EXT
    info = {
        "path": path, "size": st.st_size, "mtime": st.st_mtime, "sha256": sha256_of(path),
        "phash": None, "width": None, "height": None, "is_video": int(is_video),
        "mime": VIDEO_EXT.get(ext) or PHOTO_EXT.get(ext), "camera": None,
    }
    taken = None
    date_source = None
    if not is_video:
        try:
            with Image.open(path) as img:
                info["width"], info["height"] = img.size
                taken, info["camera"] = _exif_info(img)
                img.draft("RGB", (1024, 1024))  # JPEG: decodifica já reduzida (bem mais rápido)
                small = ImageOps.exif_transpose(img).convert("RGB")
                small.thumbnail((512, 512))
                info["phash"] = phash(small)
        except Exception:
            pass  # arquivo corrompido ou formato sem suporte: segue só com hash
    if taken:
        date_source = "exif"
    else:
        taken = date_from_name(name)
        date_source = "nome" if taken else None
    if not taken:
        taken = datetime.fromtimestamp(st.st_mtime)
        date_source = "arquivo"
    info["taken_at"] = taken.isoformat(timespec="seconds")
    info["date_source"] = date_source

    if WHATSAPP_RE.match(name) or "whatsapp" in path.lower():
        info["source"] = "whatsapp"
    elif SCREENSHOT_RE.search(name) or "screenshot" in path.lower():
        info["source"] = "print"
    elif info["camera"]:
        info["source"] = "camera"
    else:
        info["source"] = "desconhecida"
    return info


def scan(root: str, cfg, progress=None, log=None, stop=None) -> int:
    progress = progress or (lambda *a: None)
    log = log or (lambda *a: None)
    conn = db.connect()
    progress(_("Listando arquivos"), 0, 0, root)
    files = list(iter_media(root, cfg.ignore_dirs))
    total = len(files)
    log(_("{n} fotos/vídeos encontrados em {pasta}").format(n=total, pasta=root))
    novos = 0
    for i, path in enumerate(files, 1):
        if stop is not None and stop.is_set():
            break
        if i % 25 == 0 or i == total:
            progress(_("Lendo arquivos"), i, total, os.path.basename(path))
        try:
            st = os.stat(path)
        except OSError:
            continue
        row = conn.execute("SELECT id, size, mtime FROM photos WHERE path=?", (path,)).fetchone()
        if row and row["size"] == st.st_size and abs((row["mtime"] or 0) - st.st_mtime) < 2:
            continue
        try:
            info = analyze(path, st)
        except OSError as e:
            log(_("Não consegui ler {arquivo}: {erro}").format(arquivo=path, erro=e))
            continue

        if row is None:
            # mesmo arquivo já conhecido em outro caminho que não existe mais
            # (ex.: o HD montou com outra letra) -> só atualiza o caminho
            moved = conn.execute(
                "SELECT id, path FROM photos WHERE sha256=?", (info["sha256"],)
            ).fetchall()
            moved = [m for m in moved if not os.path.exists(m["path"])]
            if moved:
                conn.execute(
                    "UPDATE photos SET path=?, size=?, mtime=? WHERE id=?",
                    (path, info["size"], info["mtime"], moved[0]["id"]),
                )
                continue
            cols = ", ".join(info)
            marks = ", ".join("?" for _ in info)
            conn.execute(f"INSERT INTO photos({cols}) VALUES({marks})", tuple(info.values()))
            novos += 1
        else:
            sets = ", ".join(f"{k}=?" for k in info)
            conn.execute(
                f"UPDATE photos SET {sets}, status=CASE WHEN media_item_id IS NULL THEN 'scanned' ELSE status END "
                f"WHERE id=?",
                (*info.values(), row["id"]),
            )
        if i % 100 == 0:
            conn.commit()
    conn.commit()
    dups = mark_duplicates(conn)
    log(_("{novos} arquivos novos; {dup} duplicatas no total").format(novos=novos, dup=dups))
    conn.close()
    return novos


def _keeper_score(r) -> tuple:
    area = (r["width"] or 0) * (r["height"] or 0)
    return (
        1 if r["media_item_id"] else 0,
        1 if r["source"] == "camera" else 0,
        area,
        r["size"] or 0,
        -r["id"],
    )


def mark_duplicates(conn) -> int:
    """Duplicata exata (mesmo SHA-256) ou quase-duplicata (mesmo hash perceptual)."""
    conn.execute("UPDATE photos SET duplicate_of=NULL WHERE media_item_id IS NULL")
    rows = conn.execute(
        "SELECT id, sha256, phash, width, height, size, source, media_item_id, is_video FROM photos"
    ).fetchall()

    def resolve(groups):
        n = 0
        for members in groups.values():
            if len(members) < 2:
                continue
            members.sort(key=_keeper_score, reverse=True)
            keeper = members[0]["id"]
            for m in members[1:]:
                if m["media_item_id"]:
                    continue
                conn.execute("UPDATE photos SET duplicate_of=? WHERE id=?", (keeper, m["id"]))
                dup_ids.add(m["id"])
                n += 1
        return n

    dup_ids: set[int] = set()
    by_sha: dict[str, list] = {}
    for r in rows:
        by_sha.setdefault(r["sha256"], []).append(r)
    total = resolve(by_sha)

    by_phash: dict[str, list] = {}
    for r in rows:
        if r["is_video"] or not r["phash"] or r["phash"] in BLANK_HASHES or r["id"] in dup_ids:
            continue
        by_phash.setdefault(r["phash"], []).append(r)
    total += resolve(by_phash)
    conn.commit()
    return total
