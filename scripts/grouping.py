"""Объединение одинаковых передач: времена через запятую, подряд — диапазон."""
from __future__ import annotations

import re

CUTOFF = 4 * 60 + 30  # раньше 04:30 — предыдущие вещательные сутки

# 09.00 | 09:00 | 06.00–08.30 | 06:00-08:30
TIME_TOKEN = r'\d{1,2}[.:]\d{2}(?:\s*[–—-]\s*\d{1,2}[.:]\d{2})?'
LINE_RE = re.compile(
    rf'^((?:{TIME_TOKEN})(?:\s*,\s*{TIME_TOKEN})*)\s+(.+)$'
)
_TOKEN_RE = re.compile(
    r'^(\d{1,2})[.:](\d{2})(?:\s*[–—-]\s*(\d{1,2})[.:](\d{2}))?$'
)


def to_sort(hh: int, mm: int) -> int:
    a = hh * 60 + mm
    return a + 1440 if a < CUTOFF else a


def format_time(sort: int, sep: str = ':') -> str:
    m = sort % 1440
    return f'{m // 60:02d}{sep}{m % 60:02d}'


def title_key(title: str) -> str:
    s = (title or '').lower().replace('ё', 'е')
    return re.sub(r'[^a-zа-я0-9+]+', '', s)


def parse_time_token(tok: str) -> dict | None:
    m = _TOKEN_RE.match(tok.strip())
    if not m:
        return None
    sort = to_sort(int(m.group(1)), int(m.group(2)))
    if m.group(3) is not None:
        return {'sort': sort, 'end_sort': to_sort(int(m.group(3)), int(m.group(4)))}
    return {'sort': sort}


def is_single_time(label: str) -> bool:
    return bool(re.fullmatch(r'\d{2}[:.]\d{2}', label or ''))


def event_key(ev: dict) -> str:
    return ev.get('key') or title_key(ev['title'])


def merge_events(events: list[dict], *, sep: str = ':') -> list[dict]:
    """Склеить одинаковые названия.

    events — по времени, у каждого ``sort``, ``title``; у готового диапазона
    ещё ``end_sort``. Необязательный ``key`` — ключ склейки (иначе от title).
    Подряд (соседние слоты) → «06:00–07:00», иначе список начал через запятую.
    Конец диапазона — время следующей *другой* передачи.
    Если следующей нет, начала перечисляются через запятую.

    Возвращает ``{label, title, sort, first, key}``.
    """
    if not events:
        return []

    runs: list[dict] = []
    i, n = 0, len(events)
    while i < n:
        ev = events[i]
        key = event_key(ev)
        first = ev.get('first', ev)
        if ev.get('end_sort') is not None:
            runs.append({
                'key': key, 'title': ev['title'], 'first': first,
                'start': ev['sort'], 'end': ev['end_sort'],
                'starts': None, 'ready_range': True,
            })
            i += 1
            continue
        starts = [ev['sort']]
        j = i + 1
        while (
            j < n
            and events[j].get('end_sort') is None
            and event_key(events[j]) == key
        ):
            st = events[j]['sort']
            if st != starts[-1]:
                starts.append(st)
            j += 1
        runs.append({
            'key': key, 'title': ev['title'], 'first': first,
            'start': starts[0], 'end': events[j]['sort'] if j < n else None,
            'starts': starts, 'ready_range': False,
        })
        i = j

    ordered: list[str] = []
    buckets: dict[str, dict] = {}
    for run in runs:
        k = run['key']
        if k not in buckets:
            buckets[k] = {
                'title': run['title'], 'first': run['first'],
                'parts': [], 'sort': run['start'],
            }
            ordered.append(k)
        if run['ready_range']:
            buckets[k]['parts'].append(
                f"{format_time(run['start'], sep)}–{format_time(run['end'], sep)}"
            )
        elif len(run['starts']) >= 2 and run['end'] is not None:
            buckets[k]['parts'].append(
                f"{format_time(run['start'], sep)}–{format_time(run['end'], sep)}"
            )
        else:
            buckets[k]['parts'].extend(
                format_time(s, sep) for s in run['starts']
            )

    return [
        {
            'label': ', '.join(buckets[k]['parts']),
            'title': buckets[k]['title'],
            'sort': buckets[k]['sort'],
            'first': buckets[k]['first'],
            'key': k,
        }
        for k in ordered
    ]


def _ev(hhmm: str, title: str) -> dict:
    hh, mm = hhmm.replace(':', '.').split('.')
    return {'sort': to_sort(int(hh), int(mm)), 'title': title}


if __name__ == '__main__':
    def labels(items):
        return [(r['label'], r['title']) for r in merge_events(items)]

    assert labels([
        _ev('06.00', 'A'), _ev('09.00', 'B'), _ev('12.00', 'A'),
    ]) == [('06:00, 12:00', 'A'), ('09:00', 'B')]

    assert labels([
        _ev('06.00', 'A'), _ev('06.15', 'A'), _ev('06.30', 'A'), _ev('07.00', 'B'),
    ]) == [('06:00–07:00', 'A'), ('07:00', 'B')]

    assert labels([
        _ev('06.00', 'A'), _ev('06.15', 'A'), _ev('07.00', 'B'), _ev('21.00', 'A'),
    ]) == [('06:00–07:00, 21:00', 'A'), ('07:00', 'B')]

    assert labels([
        _ev('00.30', 'A'), _ev('00.45', 'A'),
    ]) == [('00:30, 00:45', 'A')]

    assert labels([
        _ev('09.00', 'Новости'), _ev('09.25', 'Модный приговор'),
        _ev('12.00', 'Новости'),
    ]) == [('09:00, 12:00', 'Новости'), ('09:25', 'Модный приговор')]

    mixed = merge_events([
        {**_ev('06.00', 'Мульт'), 'end_sort': to_sort(8, 30)},
        _ev('21.00', 'Мульт'),
    ])
    assert [(r['label'], r['title']) for r in mixed] == [('06:00–08:30, 21:00', 'Мульт')]

    print('grouping ok')
