"""Agrupa as fotos que serão enviadas em álbuns: por evento, por mês ou por ano."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta

from . import db
from .config import wants_upload

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def event_title(start: datetime, end: datetime) -> str:
    if start.date() == end.date():
        period = f"{start:%d/%m/%Y}"
    elif (start.year, start.month) == (end.year, end.month):
        period = f"{start:%d} a {end:%d/%m/%Y}"
    elif start.year == end.year:
        period = f"{start:%d/%m} a {end:%d/%m/%Y}"
    else:
        period = f"{start:%d/%m/%Y} a {end:%d/%m/%Y}"
    return f"Evento {period}"


def month_title(dt: datetime) -> str:
    return f"{MESES[dt.month - 1]} de {dt.year}"


YEAR_DIR_RE = re.compile(r"^((?:19|20)\d{2})(?!\d)")


def year_from_folder(path: str) -> int | None:
    """Ano pelo nome da pasta mais próxima do arquivo: '2021', '2021 - Viagem', '2021_celular'..."""
    max_year = datetime.now().year + 1
    for part in reversed(os.path.normpath(os.path.dirname(path)).split(os.sep)):
        m = YEAR_DIR_RE.match(part.strip())
        if m and 1990 <= int(m.group(1)) <= max_year:
            return int(m.group(1))
    return None


def plan_years(items: list[tuple[int, datetime, str, str]], title_tpl: str):
    """Um álbum por ano. A data da foto (EXIF/nome) manda; sem ela, vale o ano da pasta;
    sem nenhum dos dois, a foto vai para 'sem data' (a data do arquivo costuma ser a da cópia)."""
    albums: dict[str, list] = {}
    for pid, dt, date_source, path in items:
        year = dt.year if date_source != "arquivo" else year_from_folder(path)
        if year is None:
            key, title = "ano-sem-data", title_tpl.replace("{ano}", "sem data")
            start = end = dt
        else:
            key, title = f"ano-{year}", title_tpl.replace("{ano}", str(year))
            start, end = datetime(year, 1, 1), datetime(year, 12, 31, 23, 59)
        a = albums.setdefault(key, [title, start, end, []])
        a[1], a[2] = min(a[1], start), max(a[2], end)
        a[3].append(pid)
    return {k: tuple(v) for k, v in albums.items()}


def plan_albums(items: list[tuple[int, datetime, str]], gap_hours: float, min_size: int):
    """items: (id, data, origem_da_data). Retorna {album_key: (titulo, inicio, fim, [ids])}."""
    albums: dict[str, list] = {}

    def add(key, title, ids, start, end):
        a = albums.setdefault(key, [title, start, end, []])
        a[1], a[2] = min(a[1], start), max(a[2], end)
        a[3].extend(ids)

    reliable = sorted((i for i in items if i[2] != "arquivo"), key=lambda x: x[1])
    unreliable = [i for i in items if i[2] == "arquivo"]

    events: list[list] = []
    gap = timedelta(hours=gap_hours)
    for it in reliable:
        if events and it[1] - events[-1][-1][1] <= gap:
            events[-1].append(it)
        else:
            events.append([it])

    for ev in events:
        start, end = ev[0][1], ev[-1][1]
        if len(ev) >= min_size:
            add(f"evt-{start:%Y%m%d-%H%M}", event_title(start, end), [i[0] for i in ev], start, end)
        else:
            for it in ev:
                add(f"mes-{it[1]:%Y-%m}", month_title(it[1]), [it[0]], it[1], it[1])

    # data só do arquivo (pode ser a data da cópia): nunca vira evento
    for it in unreliable:
        add(f"mes-{it[1]:%Y-%m}", month_title(it[1]), [it[0]], it[1], it[1])
    return {k: tuple(v) for k, v in albums.items()}


def group(cfg, log=None) -> int:
    log = log or (lambda *a: None)
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM photos WHERE status='classified' AND media_item_id IS NULL"
    ).fetchall()
    items = []
    clear = []
    for r in rows:
        if wants_upload(r, cfg):
            items.append((r["id"], datetime.fromisoformat(r["taken_at"]), r["date_source"], r["path"]))
        else:
            clear.append(r["id"])
    conn.executemany("UPDATE photos SET album_key=NULL WHERE id=?", [(i,) for i in clear])

    if cfg.album_mode == "ano":
        plan = plan_years(items, cfg.year_album_title)
    elif cfg.album_mode == "mes":
        plan = plan_albums([i[:3] for i in items], gap_hours=0, min_size=10**9)
    else:
        plan = plan_albums([i[:3] for i in items], cfg.event_gap_hours, cfg.min_event_size)
    for key, (title, start, end, ids) in plan.items():
        existing = conn.execute("SELECT * FROM albums WHERE key=?", (key,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO albums(key, title, start, end) VALUES(?,?,?,?)",
                (key, title, start.isoformat(), end.isoformat()),
            )
        else:
            new_title = existing["title"] if (existing["custom_title"] or existing["google_id"]) else title
            conn.execute(
                "UPDATE albums SET title=?, start=MIN(COALESCE(start, ?), ?), end=MAX(COALESCE(end, ?), ?) WHERE key=?",
                (new_title, start.isoformat(), start.isoformat(), end.isoformat(), end.isoformat(), key),
            )
        conn.executemany("UPDATE photos SET album_key=? WHERE id=?", [(key, i) for i in ids])

    # álbuns que ficaram vazios e ainda não existem no Google
    conn.execute(
        "DELETE FROM albums WHERE google_id IS NULL AND key NOT IN "
        "(SELECT DISTINCT album_key FROM photos WHERE album_key IS NOT NULL)"
    )
    conn.commit()
    conn.close()
    log(f"{len(items)} itens organizados em {len(plan)} álbuns")
    return len(plan)
