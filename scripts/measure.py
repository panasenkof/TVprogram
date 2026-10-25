import json, os, re, sys
from fontTools.ttLib import TTFont

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
from grouping import (  # noqa: E402
    LINE_RE, is_single_time, merge_events, parse_time_token,
)

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
CELL_PAD_LEFT = 140                     # от вертикальной линейки / края колонки
CELL_PAD_RIGHT = 140
CELL_PAD = CELL_PAD_LEFT + CELL_PAD_RIGHT
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
            m = LINE_RE.match(line)
            if m:
                chan['items'].append((m.group(1), m.group(2)))
    return days

def rows_of(chan):
    events = []
    for times, title in chan['items']:
        for tok in re.split(r'\s*,\s*', times):
            p = parse_time_token(tok)
            if not p or not (FROM <= p['sort'] <= TO):
                continue
            events.append({**p, 'title': title})
    events.sort(key=lambda e: e['sort'])
    return [{'label': r['label'], 'sort': r['sort'], 'title': r['title']}
            for r in merge_events(events, sep=':')]

def wrap_lines(title, avail_pt):
    """Estimate wrapped lines including exceptionally long unspaced words.

    The previous estimator put an arbitrarily long first word on one line,
    undercounting DOCX height and occasionally causing an extra PDF page.
    """
    if not title.strip():
        return 0
    if avail_pt <= 0:
        raise ValueError('Нет места для текста в колонке')
    lines, cur = 1, ''
    for word in title.split():
        trial = (cur + ' ' + word) if cur else word
        if width_pt(trial, PT) <= avail_pt:
            cur = trial
            continue
        if cur:
            lines += 1
            cur = ''
        if width_pt(word, PT) <= avail_pt:
            cur = word
            continue
        # A long word must wrap by individual glyphs, not overflow as one line.
        for character in word:
            trial = cur + character
            if cur and width_pt(trial, PT) > avail_pt:
                lines += 1
                cur = character
            else:
                cur = trial
    return lines

def block_height(chan, col_w):
    rows = rows_of(chan)
    if not rows:
        return None, 0
    h = HEAD_H
    for r in rows:
        if is_single_time(r['label']):
            avail_pt = (col_w - CELL_PAD - TIME_INDENT) / 20
            n = wrap_lines(r['title'], avail_pt)
        else:
            avail_pt = (col_w - CELL_PAD) / 20
            n = wrap_lines(f"{r['label']} {r['title']}", avail_pt)
        h += n * LINE + AFTER
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
                 cell_pad_left=CELL_PAD_LEFT, cell_pad_right=CELL_PAD_RIGHT,
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
