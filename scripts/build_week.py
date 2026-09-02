#!/usr/bin/env python3
"""Собрать nedelya.txt: Телеграф + Яндекс ТВ Ростов. Не выдумывает сетку.

Один прогон без участия модели: индекс Телеграфа → дни недели → параллельно
страницы каналов Яндекса → сверка → файл. Следующую неделю не сканирует по
Яндексу, если в индексе Телеграфа на неё нет ни одной страницы.
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MSK = ZoneInfo("Europe/Moscow")
TELEGRAF_INDEX = "https://prov-telegraf.ru/teleprogramma/"
TELEGRAF_BASE = TELEGRAF_INDEX

CHANNELS = [
    ("Первый канал", 16),
    ("Россия 1", 31),  # Россия 1-Дон; federal 867 ignore
    ("НТВ", 11),
    ("ТНТ", 33),
    ("СТС", 8),
    ("Пятый", 12),
    ("РЕН ТВ", 30),
    ("Матч ТВ", 49),
    ("ТВ Центр", 32),
    ("Домашний", 5),
    ("ТВ-3", 17),
    ("Звезда", 15),
    ("Россия К", 14),
    ("Мир", 54),
    ("ОТР", 51),
]

TELEGRAF_NAME = {
    "Первый канал": "Первый канал",
    "Россия 1": "Россия 1",
    "НТВ": "НТВ",
    "ТНТ": "ТНТ",
    "СТС": "СТС",
    "Пятый канал": "Пятый",
    "Пятый": "Пятый",
    "Рен ТВ": "РЕН ТВ",
    "РЕН ТВ": "РЕН ТВ",
    "Матч ТВ": "Матч ТВ",
    "ТВ Центр": "ТВ Центр",
    "Домашний": "Домашний",
    "ТВ3": "ТВ-3",
    "ТВ-3": "ТВ-3",
    "Звезда": "Звезда",
    "Россия К": "Россия К",
    "Мир": "Мир",
    "ОТР": "ОТР",
}

SKIP_TITLES = {"перерыв в вещании", "конец эфира", "профилактика"}
DAYS_RU = {
    0: "Понедельник", 1: "Вторник", 2: "Среда", 3: "Четверг",
    4: "Пятница", 5: "Суббота", 6: "Воскресенье",
}
MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}
MONTH_SLUG = {
    1: "yanvarya", 2: "fevralya", 3: "marta", 4: "aprelya", 5: "maya",
    6: "iyunya", 7: "iyulya", 8: "avgusta", 9: "sentyabrya", 10: "oktyabrya",
    11: "noyabrya", 12: "dekabrya",
}
MONTH_FROM_SLUG = {v: k for k, v in MONTH_SLUG.items()}
WEEKDAY_SLUG = {
    0: "ponedelnik", 1: "vtornik", 2: "sreda", 3: "chetverg",
    4: "pyatnicza", 5: "subbota", 6: "voskresene",
}

TIME_RE = re.compile(r"^((?:\d{1,2}\.\d{2})(?:\s*,\s*\d{1,2}\.\d{2})*)\s+(.+)$")
AGE_RE = re.compile(r"\((\d{1,2}\+)\)$")
PREFIX_RE = re.compile(r"^(Т/с|Х/ф|М/ф|Д/ф|М/с|Т/ш|Драмеди)\s+", re.I)
SLUG_RE = re.compile(
    r"teleprogramma-na-(\d{1,2})-([a-z]+)-(\d{4})-goda", re.I
)
BARE = re.compile(
    r"^(новости|вечерние новости|вести|вести\.?\s*дон|сегодня|известия|"
    r"известия\.?\s*итоговый выпуск|события|местное время|выборы-?\s*2026|"
    r"город новостей|события\.?\s*25-й час)(\b|$)",
    re.I,
)

MIN_TELEGRAF_DAYS = 1
YANDEX_GRID_MIN = 8


def slug_for(d: date) -> str:
    return (
        f"teleprogramma-na-{d.day}-{MONTH_SLUG[d.month]}-{d.year}-goda,"
        f"-{WEEKDAY_SLUG[d.weekday()]}"
    )


def parse_slug_date(slug: str) -> date | None:
    m = SLUG_RE.search(slug)
    if not m:
        return None
    month = MONTH_FROM_SLUG.get(m.group(2).lower())
    if not month:
        return None
    return date(int(m.group(3)), month, int(m.group(1)))


def weeks_for(today: date) -> tuple[list[date], list[date]]:
    """(next_week, current_week). Sunday run → next week starts tomorrow."""
    if today.weekday() == 6:
        nxt_mon = today + timedelta(days=1)
    else:
        nxt_mon = today + timedelta(days=(6 - today.weekday()) + 1)
    cur_mon = today - timedelta(days=today.weekday())
    nxt = [nxt_mon + timedelta(days=i) for i in range(7)]
    cur = [cur_mon + timedelta(days=i) for i in range(7)]
    return nxt, cur


def fetch(url: str, retries: int = 3) -> str | None:
    last: Exception | None = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept-Language": "ru"}
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status == 404:
                    return None
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
            time.sleep(0.4 * (i + 1))
        except Exception as e:
            last = e
            time.sleep(0.4 * (i + 1))
    if last:
        print(f"warn: {url} -> {last}", file=sys.stderr)
    return None


def cached_get(url: str, path: Path | None) -> str | None:
    if path and path.exists() and path.stat().st_size > 800:
        return path.read_text(encoding="utf-8", errors="replace")
    html = fetch(url)
    if html and path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    return html


def strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmllib.unescape(s)
    return " ".join(s.split())


def telegraf_index_dates(html: str) -> dict[date, str]:
    found: dict[date, str] = {}
    for href in re.findall(r'href=["\']([^"\']+)["\']', html):
        if "teleprogramma-na-" not in href:
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        d = parse_slug_date(slug)
        if d:
            found[d] = slug
    return found


def parse_telegraf(html: str) -> dict[str, list[tuple[str, str, str | None, str | None]]]:
    by: dict[str, list] = {}
    cur = None
    for p in re.findall(r"<p[^>]*>(.*?)</p>", html, re.S):
        t = strip_tags(p)
        if not t or t.startswith("Программа"):
            continue
        m = TIME_RE.match(t)
        if m and cur:
            times, rest = m.group(1), m.group(2).strip()
            age = None
            am = AGE_RE.search(rest)
            if am:
                age = am.group(1)
                rest = rest[: am.start()].rstrip()
            prefix = None
            pm = PREFIX_RE.match(rest)
            if pm:
                prefix = pm.group(1)
                rest = rest[pm.end() :].strip()
            if rest.count('"') >= 2:
                rest = rest.replace('"', "«", 1).replace('"', "»")
            rest = rest.replace("««", "«").replace("»»", "»")
            for tm in times.split(","):
                tm = tm.strip()
                if tm:
                    by.setdefault(cur, []).append((tm, rest, age, prefix))
            continue
        mapped = TELEGRAF_NAME.get(t)
        if mapped:
            cur = mapped
    return by


def norm_title(s: str) -> str:
    s = s.lower().replace("ё", "е")
    s = re.sub(r"\(с субтитрами\)", "", s)
    s = re.sub(r"^телеканал\s+", "", s)
    return re.sub(r"[^a-zа-я0-9+]+", "", s)


def clean_title(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s*\(с субтитрами\)\s*", "", s, flags=re.I)
    s = re.sub(r"^телеканал\s+", "", s, flags=re.I)
    s = s.replace("«", '"').replace("»", '"').replace("“", '"').replace("”", '"')
    while len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].strip()
    s = re.sub(r'"([^"]+)"', r"«\1»", s)
    return " ".join(s.replace('"', "").split())


def similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    if abs(len(a) - len(b)) > max(len(a), len(b)) * 0.4:
        return False
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio() >= 0.78


def parse_yandex(html: str, day: date) -> list[dict]:
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*", html)
    if not m:
        return []
    obj, _ = json.JSONDecoder().raw_decode(html, m.end())
    events = ((obj.get("channel") or {}).get("schedule") or {}).get("events") or []
    next_day = day + timedelta(days=1)
    out = []
    for e in events:
        start = e.get("start") or ""
        try:
            dt = datetime.fromisoformat(start)
            dt = dt.replace(tzinfo=MSK) if dt.tzinfo is None else dt.astimezone(MSK)
        except Exception:
            continue
        local_date, mins = dt.date(), dt.hour * 60 + dt.minute
        if local_date == day and mins >= 4 * 60 + 30:
            pass
        elif local_date == next_day and mins < 4 * 60 + 30:
            pass
        else:
            continue
        prog = e.get("program") or {}
        title = (prog.get("title") or e.get("programTitle") or e.get("title") or "").strip()
        title = clean_title(title)
        if not title or title.lower() in SKIP_TITLES:
            continue
        ptype = prog.get("type") or {}
        tname = (ptype.get("name") or "").lower()
        kind = None
        if ptype.get("isSerial"):
            kind = "Т/с"
        elif "мульт" in tname:
            kind = "М/ф"
        elif ptype.get("isFilm"):
            kind = "Х/ф"
        out.append({
            "dt": dt,
            "hhmm": f"{dt.hour:02d}.{dt.minute:02d}",
            "title": title,
            "kind": kind,
        })
    out.sort(key=lambda x: x["dt"])
    return out


def pick_age(ages: list[str | None]) -> str | None:
    vals = [a for a in ages if a]
    return max(set(vals), key=vals.count) if vals else None


def format_item(title: str, age: str | None, prefix: str | None, quoted: bool) -> str:
    title = clean_title(title)
    already = title.startswith("«")
    if prefix:
        if not already:
            title = f"«{title}»"
        title = f"{prefix} {title}"
    elif quoted and not already and not BARE.match(title):
        title = f"«{title}»"
    if age:
        title = f"{title} ({age})"
    return title


def attach_meta(y_items: list[dict], t_items: list[tuple[str, str, str | None, str | None]]):
    by_norm: dict[str, list] = defaultdict(list)
    by_time: dict[str, list] = defaultdict(list)
    for tm, title, age, prefix in t_items:
        hh, mm = tm.split(".")
        rec = {
            "title": clean_title(title),
            "age": age,
            "prefix": prefix,
            "norm": norm_title(title),
            "quoted": title.strip()[:1] in "«\"",
        }
        by_norm[rec["norm"]].append(rec)
        by_time[f"{int(hh):02d}.{mm}"].append(rec)
    for it in y_items:
        it["title"] = clean_title(it["title"])
        n = norm_title(it["title"])
        rec = (by_norm.get(n) or [None])[0]
        if rec is None:
            for k, lst in by_norm.items():
                if similar(n, k):
                    rec = lst[0]
                    break
        if rec is None:
            timed = [c for c in by_time.get(it["hhmm"], []) if similar(n, c["norm"])]
            rec = timed[0] if timed else None
        it["age"] = rec["age"] if rec else None
        it["prefix"] = rec["prefix"] if rec and rec["prefix"] else it.get("kind")
        it["quoted"] = bool(rec and rec["quoted"]) or it["title"].startswith("«")
        it["norm"] = n


def group_lines(items: list[dict]) -> list[str]:
    ordered: list[str] = []
    buckets: dict[str, dict] = {}
    for it in items:
        key = it.get("norm") or norm_title(it["title"])
        if key not in buckets:
            buckets[key] = {
                "times": [], "ages": [], "prefixes": [],
                "title": it["title"], "quoted": False,
            }
            ordered.append(key)
        b = buckets[key]
        if it["hhmm"] not in b["times"]:
            b["times"].append(it["hhmm"])
        b["ages"].append(it.get("age"))
        if it.get("prefix"):
            b["prefixes"].append(it["prefix"])
        b["quoted"] = b["quoted"] or bool(it.get("quoted"))
    out = []
    for key in ordered:
        b = buckets[key]
        prefix = b["prefixes"][0] if b["prefixes"] else None
        line = format_item(b["title"], pick_age(b["ages"]), prefix, b["quoted"])
        out.append(f"{', '.join(b['times'])} {line}")
    return out


def day_heading(d: date) -> str:
    return f"{DAYS_RU[d.weekday()]}, {d.day} {MONTHS_RU[d.month]} {d.year}"


def yandex_url(fid: int, d: date) -> str:
    return f"https://tv.yandex.ru/39/channel/{fid}?date={d.isoformat()}"


def load_week_sources(days: list[date], index_slugs: dict[date, str], cache: Path | None, workers: int):
    tele_html: dict[date, str] = {}
    yandex_items: dict[tuple[date, str], list[dict]] = {}

    jobs = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for d in days:
            slug = index_slugs.get(d) or slug_for(d)
            tpath = (cache / "telegraf" / f"{slug}.html") if cache else None
            jobs.append(("t", d, None, ex.submit(
                cached_get, TELEGRAF_BASE + slug, tpath
            )))
            for cname, fid in CHANNELS:
                ypath = (cache / "yandex" / f"{fid}_{d.isoformat()}.html") if cache else None
                jobs.append(("y", d, cname, ex.submit(
                    cached_get, yandex_url(fid, d), ypath
                )))
        for kind, d, cname, fut in jobs:
            html = fut.result()
            if kind == "t":
                if html and "<title>Новости, События, Аналитика</title>" not in html[:800]:
                    tele_html[d] = html
            else:
                yandex_items[(d, cname)] = parse_yandex(html, d) if html else []
    return tele_html, yandex_items


def week_is_usable(tele_html: dict[date, str], yandex_items: dict) -> bool:
    if len(tele_html) >= MIN_TELEGRAF_DAYS:
        return True
    substantial = sum(1 for items in yandex_items.values() if len(items) >= YANDEX_GRID_MIN)
    return substantial >= 10


def assemble(days: list[date], tele_html: dict[date, str], yandex_items: dict) -> tuple[str, dict]:
    report = {
        "missing_days": [],
        "telegraf_fallback": [],
        "both_empty": [],
        "yandex_days": 0,
        "telegraf_days": 0,
    }
    chunks = []
    for d in days:
        html = tele_html.get(d)
        tele = parse_telegraf(html) if html else {}
        if html:
            report["telegraf_days"] += 1
        day_ok = False
        body = [f"# {day_heading(d)}"]
        for cname, _fid in CHANNELS:
            yitems = yandex_items.get((d, cname)) or []
            titems = tele.get(cname) or []
            if yitems:
                attach_meta(yitems, titems)
                lines = group_lines(yitems)
                src = "yandex"
                report["yandex_days"] += 1
            elif titems:
                tmp = []
                for tm, title, age, prefix in titems:
                    hh, mm = tm.split(".")
                    tmp.append({
                        "hhmm": f"{int(hh):02d}.{mm}",
                        "title": title,
                        "age": age,
                        "prefix": prefix,
                        "quoted": title.strip()[:1] in "«\"",
                        "norm": norm_title(title),
                    })
                lines = group_lines(tmp)
                src = "telegraf"
                report["telegraf_fallback"].append(f"{d.isoformat()} {cname}")
            else:
                report["both_empty"].append(f"{d.isoformat()} {cname}")
                continue
            body.append(f"== {cname}")
            body.extend(lines)
            day_ok = True
            _ = src
        if day_ok:
            chunks.extend(body)
        else:
            report["missing_days"].append(d.isoformat())
    return "\n".join(chunks) + ("\n" if chunks else ""), report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Сборка nedelya.txt из Телеграфа и Яндекса")
    ap.add_argument("--out", default="nedelya.txt")
    ap.add_argument("--report", default="build-report.json")
    ap.add_argument("--today", default="", help="YYYY-MM-DD, иначе сегодня (МСК)")
    ap.add_argument("--week", choices=("auto", "next", "current"), default="auto")
    ap.add_argument("--cache-dir", default="", help="Кэш HTML; пусто = без кэша")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else datetime.now(MSK).date()
    next_week, cur_week = weeks_for(today)
    cache = Path(args.cache_dir) if args.cache_dir else None

    index_html = cached_get(
        TELEGRAF_INDEX,
        (cache / "telegraf" / "index.html") if cache else None,
    ) or ""
    index_slugs = telegraf_index_dates(index_html)

    def coverage(days: list[date]) -> int:
        return sum(1 for d in days if d in index_slugs)

    chosen = next_week
    kind = "next"
    reason = ""
    if args.week == "current":
        chosen, kind = cur_week, "current"
        reason = "forced current"
    elif args.week == "next":
        chosen, kind = next_week, "next"
        reason = "forced next"
    else:
        nxt_cov = coverage(next_week)
        if nxt_cov == 0:
            chosen, kind = cur_week, "current"
            reason = (
                f"next week {next_week[0]}…{next_week[-1]} missing on telegraf index "
                f"(0/7 days); not probing Yandex for it"
            )
        else:
            chosen, kind = next_week, "next"
            reason = f"telegraf index has {nxt_cov}/7 days of next week"

    tele_html, yandex_items = load_week_sources(
        chosen, index_slugs, cache, args.workers
    )
    if args.week == "auto" and kind == "next" and not week_is_usable(tele_html, yandex_items):
        reason += "; fetched next week is empty → current"
        chosen, kind = cur_week, "current"
        tele_html, yandex_items = load_week_sources(
            chosen, index_slugs, cache, args.workers
        )

    text, report = assemble(chosen, tele_html, yandex_items)
    if not text.strip():
        print("error: no schedule for any day; not inventing a grid", file=sys.stderr)
        Path(args.report).write_text(
            json.dumps({"ok": False, "kind": kind, "reason": reason,
                        "week": [d.isoformat() for d in chosen], **report},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 2

    Path(args.out).write_text(text, encoding="utf-8")
    summary = {
        "ok": True,
        "kind": kind,
        "reason": reason,
        "week": [d.isoformat() for d in chosen],
        "monday": chosen[0].isoformat(),
        "lines": text.count("\n"),
        "out": args.out,
        **report,
    }
    Path(args.report).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"week: {kind} {chosen[0]}…{chosen[-1]}\n"
        f"reason: {reason}\n"
        f"telegraf days: {report['telegraf_days']}/7  "
        f"yandex channel-days with data: {report['yandex_days']}\n"
        f"telegraf fallback: {len(report['telegraf_fallback'])}  "
        f"missing days: {report['missing_days'] or '—'}\n"
        f"wrote {args.out} ({summary['lines']} lines)  report {args.report}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
