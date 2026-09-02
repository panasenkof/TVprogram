import json, os, re, sys
from fontTools.ttLib import TTFont

FONT_CANDIDATES = [
    (
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    ),
    (
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf',
    ),
    (
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    ),
    (
        r'C:\Windows\Fonts\arial.ttf',
        r'C:\Windows\Fonts\arialbd.ttf',
    ),
]


def find_fonts():
    for regular, bold in FONT_CANDIDATES:
        if os.path.isfile(regular) and os.path.isfile(bold):
            return regular, bold
    raise FileNotFoundError(
        'Не найдены Liberation Sans / Arial / DejaVu. '
        'Установите fonts-liberation.'
    )


REG = TTFont(find_fonts()[0])
BLD = TTFont(find_fonts()[1])

def metrics(f):
    upm = f['head'].unitsPerEm
    cmap = f.getBestCmap()
    hmtx = f['hmtx']
    return upm, cmap, hmtx

M_REG, M_BLD = metrics(REG), metrics(BLD)

def width_pt(text, pt, bold=False):
    upm, cmap, hmtx = M_BLD if bold else M_REG
    total = 0
    for c in text:
        g = cmap.get(ord(c))
        total += hmtx[g][0] if g else upm // 2
    return total / upm * pt

# ---------- геометрия страницы (в dxa, 20 dxa = 1 pt) ----------
A4_SHORT, A4_LONG = 11906, 16838
M_TOP, M_BOT, M_LEFT, M_RIGHT = 620, 900, 700, 620
TIME_INDENT = 1000                      # отступ под колонку времени
CELL_PAD = 220                          # внутренний зазор ячейки таблицы
AFTER = 20                              # интервал после абзаца (40 давало +1 лист: воскресный «хвост»)

def set_geom(landscape, pt):
    global PAGE_W, PAGE_H, USABLE_W, USABLE_H, PT, PT_CH, LINE, HEAD_H, TITLE_H, TIME_INDENT
    PAGE_W, PAGE_H = (A4_LONG, A4_SHORT) if landscape else (A4_SHORT, A4_LONG)
    USABLE_W = PAGE_W - M_LEFT - M_RIGHT
    USABLE_H = PAGE_H - M_TOP - M_BOT
    PT = pt
    PT_CH = round(pt * 1.35)
    LINE = round(pt * 1.25 * 20)
    TIME_INDENT = round(width_pt('00:00  ', pt, True) * 20)
    HEAD_H = 260 + round(PT_CH * 1.15 * 20) + 100 + 20
    TITLE_H = round(PT_CH * 1.15 * 20) + 240

set_geom(True, 16)

SKIP = {'Россия 24', 'Муз-ТВ', 'Карусель', 'Пятница!', 'Спас'}
CUTOFF = 4 * 60 + 30
FROM, TO = 6 * 60, 25 * 60

def parse(path):
    days, day, chan = [], None, None
    for raw in open(path, encoding='utf-8'):
        line = raw.strip()
        if not line:
            continue
        if line.startswith('# '):
            day = {'title': line[2:].strip(), 'channels': []}
            days.append(day); chan = None
        elif line.startswith('== '):
            chan = {'name': line[3:].strip(), 'items': []}
            day['channels'].append(chan)
        else:
            m = re.match(r'^((?:\d{1,2}[.:]\d{2})(?:\s*,\s*\d{1,2}[.:]\d{2})*)\s+(.+)$', line)
            if m:
                chan['items'].append((m.group(1), m.group(2)))
    return days

def rows_of(chan):
    out = []
    for times, title in chan['items']:
        for t in times.split(','):
            m = re.match(r'^(\d{1,2})[.:](\d{2})$', t.strip())
            if not m:
                continue
            a = int(m.group(1)) * 60 + int(m.group(2))
            s = a + 1440 if a < CUTOFF else a
            if not (FROM <= s <= TO):
                continue
            out.append({'label': f'{int(m.group(1)):02d}:{m.group(2)}', 'sort': s, 'title': title})
    out.sort(key=lambda r: r['sort'])
    return out

def wrap_lines(title, avail_pt):
    words, lines, cur = title.split(' '), 0, ''
    for w in words:
        trial = (cur + ' ' + w).strip()
        if width_pt(trial, PT) <= avail_pt or not cur:
            cur = trial
        else:
            lines += 1; cur = w
    return lines + (1 if cur else 0)

def block_height(chan, col_w):
    rows = rows_of(chan)
    if not rows:
        return None, 0
    avail_pt = (col_w - CELL_PAD - TIME_INDENT) / 20
    h = HEAD_H
    for r in rows:
        h += wrap_lines(r['title'], avail_pt) * LINE + AFTER
    return rows, h

def _bins_ffd(blocks, cap):
    bins = []
    for b in sorted(blocks, key=lambda x: -x['h']):
        for bn in bins:
            if bn['h'] + b['h'] <= cap:
                bn['items'].append(b)
                bn['h'] += b['h']
                break
        else:
            bins.append({'items': [b], 'h': b['h']})
    return bins


def _bins_bfd(blocks, cap):
    bins = []
    for b in sorted(blocks, key=lambda x: -x['h']):
        best, best_left = None, None
        for i, bn in enumerate(bins):
            left = cap - bn['h'] - b['h']
            if left >= 0 and (best_left is None or left < best_left):
                best, best_left = i, left
        if best is None:
            bins.append({'items': [b], 'h': b['h']})
        else:
            bins[best]['items'].append(b)
            bins[best]['h'] += b['h']
    return bins


def _refill(bins, cap):
    """Переложить хвост в более ранние колонки, если влезает."""
    bins = [bn for bn in bins if bn['items']]
    changed = True
    while changed and len(bins) > 1:
        changed = False
        last = bins[-1]
        keep = []
        for item in last['items']:
            best, best_left = None, None
            for i, bn in enumerate(bins[:-1]):
                left = cap - bn['h'] - item['h']
                if left >= 0 and (best_left is None or left < best_left):
                    best, best_left = i, left
            if best is None:
                keep.append(item)
            else:
                bins[best]['items'].append(item)
                bins[best]['h'] += item['h']
                changed = True
        if keep:
            last['items'] = keep
            last['h'] = sum(x['h'] for x in keep)
        else:
            bins.pop()
    return bins


def pack(blocks, cap, cols):
    """Блок целиком в одну колонку; из FFD/BFD берём меньше колонок."""
    if not blocks:
        return []
    cand = min(
        (_refill(_bins_ffd(blocks, cap), cap),
         _refill(_bins_bfd(blocks, cap), cap)),
        key=len,
    )
    for bn in cand:
        bn['items'].sort(key=lambda x: x['rank'])
    cand.sort(key=lambda bn: min(i['rank'] for i in bn['items']))
    return [cand[i:i + cols] for i in range(0, len(cand), cols)]

def layout(days, cols):
    col_w = USABLE_W // cols
    cap = int((USABLE_H - TITLE_H) * 0.97)
    out = []
    for day in days:
        blocks, over = [], []
        for rank, c in enumerate(day['channels']):
            if c['name'] in SKIP:
                continue
            rows, h = block_height(c, col_w)
            if not rows:
                continue
            if h > cap:
                over.append((c['name'], round(h / cap, 2)))
            blocks.append({'name': c['name'], 'rows': rows, 'h': h, 'rank': rank})
        out.append({'title': day['title'], 'pages': pack(blocks, cap, cols), 'over': over})
    return {'cols': cols, 'col_w': col_w, 'cap': cap, 'days': out}

if __name__ == '__main__':
    days = parse(sys.argv[1])
    if len(sys.argv) > 2:                      # measure.py файл pt cols land out.json
        pt, cols, land, out = int(sys.argv[2]), int(sys.argv[3]), sys.argv[4] == '1', sys.argv[5]
        set_geom(land, pt)
        L = layout(days, cols)
        L.update(pt=pt, pt_ch=PT_CH, line=LINE, after=AFTER, head_before=260, head_after=100,
                 time_indent=TIME_INDENT, landscape=land, usable_w=USABLE_W,
                 margins=dict(top=M_TOP, bottom=M_BOT, left=M_LEFT, right=M_RIGHT))
        for d in L['days']:
            d['pages'] = [[{'items': [{'name': b['name'], 'rows': b['rows']} for b in bn['items']]}
                           for bn in p] for p in d['pages']]
        json.dump(L, open(out, 'w'), ensure_ascii=False)
        print(f"{sum(len(d['pages']) for d in L['days'])} стр -> {out}")
        sys.exit()
    best = []
    for land in (True, False):
        for cols in (2, 3, 4):
            for pt in range(11, 17):
                set_geom(land, pt)
                L = layout(days, cols)
                over = [o for d in L['days'] for o in d['over']]
                if over:
                    continue
                pages = sum(len(d['pages']) for d in L['days'])
                fill = [bn['h'] / L['cap'] for d in L['days'] for p in d['pages'] for bn in p]
                best.append((pages, -pt, cols, land, sum(fill) / len(fill)))
    best.sort(key=lambda x: (x[0], x[1]))
    print('\nЕсли канал может перетечь в соседнюю колонку, но не на другой лист:')
    for pt in (16, 15, 14):
        for land in (False, True):
            for cols in (2, 3):
                set_geom(land, pt)
                col_w = USABLE_W // cols
                cap = (USABLE_H - TITLE_H) * cols
                tot = 0; bad = False
                for day in days:
                    hs = []
                    for c in day['channels']:
                        if c['name'] in SKIP: continue
                        rows, h = block_height(c, col_w)
                        if not rows: continue
                        if h > cap: bad = True
                        hs.append(h)
                    bins = []
                    for h in sorted(hs, reverse=True):
                        for i, b in enumerate(bins):
                            if b + h <= cap: bins[i] += h; break
                        else:
                            bins.append(h)
                    tot += len(bins)
                if not bad:
                    print(f'   {pt} pt, {cols} кол., {"альбом" if land else "книжн."}: {tot} стр/день')
