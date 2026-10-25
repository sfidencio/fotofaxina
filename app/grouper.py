"""Agrupa as fotos que serão enviadas em álbuns: por evento, por mês ou por ano."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta

from . import db
from .config import wants_upload
from .i18n import _, language

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def _event_period_en(start: datetime, end: datetime) -> str:
    def d(x):
        return f"{MONTHS[x.month - 1][:3]} {x.day}"
    if start.date() == end.date():
        return f"{d(start)}, {start.year}"
    if start.year == end.year:
        return f"{d(start)} – {d(end)}, {end.year}"
    return f"{d(start)}, {start.year} – {d(end)}, {end.year}"


def event_title(start: datetime, end: datetime) -> str:
    if language() == "en":
        return f"Event {_event_period_en(start, end)}"
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
    if language() == "en":
        return f"{MONTHS[dt.month - 1]} {dt.year}"
    return f"{MESES[dt.month - 1]} de {dt.year}"


def year_title(template: str, year: int | None) -> str:
    """Modelo do nome do álbum anual: aceita {ano} ou {year}."""
    tpl = template or _("Fotos {ano}")
    value = str(year) if year is not None else _("sem data")
    return tpl.replace("{ano}", value).replace("{year}", value)


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
            key, title = "ano-sem-data", year_title(title_tpl, None)
            start = end = dt
        else:
            key, title = f"ano-{year}", year_title(title_tpl, year)
            start, end = datetime(year, 1, 1), datetime(year, 12, 31, 23, 59)
        a = albums.setdefault(key, [title, start, end, []])
        a[1], a[2] = min(a[1], start), max(a[2], end)
        a[3].append(pid)
    return {k: tuple(v) for k, v in albums.items()}


def plan_albums(items: list[tuple[int, datetime, str]], gap_hours: float, min_size: int,
                anchors: list[tuple[datetime, str]] = (), previous: dict[int, str] | None = None):
    """items: (id, data, origem_da_data). Retorna {album_key: (titulo, inicio, fim, [ids])}.

    anchors: (data, album_key) das fotos JÁ ENVIADAS para álbuns de evento. Uma foto nova do mesmo
    evento (ex.: do celular da esposa, analisado depois) vai para o mesmo álbum, em vez de virar
    outro álbum no Google Fotos.
    previous: {id: album_key} atual. Um evento ainda não enviado que cresceu mantém a chave — e o
    nome que o usuário deu na aba Álbuns."""
    albums: dict[str, list] = {}
    previous = previous or {}

    def add(key, title, ids, start, end):
        a = albums.setdefault(key, [title, start, end, []])
        a[1], a[2] = min(a[1], start), max(a[2], end)
        a[3].extend(ids)

    reliable = [i for i in items if i[2] != "arquivo"]
    unreliable = [i for i in items if i[2] == "arquivo"]

    # linha do tempo com as fotos novas e as já enviadas: (data, é_âncora, id ou chave)
    timeline = sorted([(i[1], 0, i[0]) for i in reliable] + [(dt, 1, key) for dt, key in anchors],
                      key=lambda x: (x[0], x[1]))
    events: list[list] = []
    gap = timedelta(hours=gap_hours)
    for t in timeline:
        if events and t[0] - events[-1][-1][0] <= gap:
            events[-1].append(t)
        else:
            events.append([t])

    used: set[str] = set()
    for ev in events:
        pend = [(dt, pid) for dt, anchor, pid in ev if not anchor]
        anc = [(dt, key) for dt, anchor, key in ev if anchor]
        if not pend:
            continue
        if anc:
            # evento que já tem álbum no Google: cada foto nova vai para o álbum da foto enviada
            # mais próxima no tempo
            for dt, pid in pend:
                key = min(anc, key=lambda a: abs(a[0] - dt))[1]
                add(key, event_title(dt, dt), [pid], dt, dt)
        elif len(pend) >= min_size:
            start, end = pend[0][0], pend[-1][0]
            olds = [previous[pid] for _, pid in pend if (previous.get(pid) or "").startswith("evt-")]
            olds = [k for k in olds if k not in used]
            key = max(set(olds), key=olds.count) if olds else f"evt-{start:%Y%m%d-%H%M}"
            used.add(key)
            add(key, event_title(start, end), [pid for _, pid in pend], start, end)
        else:
            for dt, pid in pend:
                add(f"mes-{dt:%Y-%m}", month_title(dt), [pid], dt, dt)

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
        anchors = [
            (datetime.fromisoformat(r["taken_at"]), r["album_key"]) for r in conn.execute(
                "SELECT taken_at, album_key FROM photos WHERE media_item_id IS NOT NULL "
                "AND album_key LIKE 'evt-%' AND date_source != 'arquivo' AND taken_at IS NOT NULL")
        ]
        previous = {r["id"]: r["album_key"] for r in rows}
        plan = plan_albums([i[:3] for i in items], cfg.event_gap_hours, cfg.min_event_size,
                           anchors=anchors, previous=previous)
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
    log(_("{n} itens organizados em {albuns} álbuns").format(n=len(items), albuns=len(plan)))
    return len(plan)
