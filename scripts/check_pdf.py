#!/usr/bin/env python3
"""Check the rendered PDF against every page/column/row in layout.json."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def normalized(text: str) -> str:
    return ''.join(c for c in text.casefold() if c.isalnum())


def reading_order(words: list) -> str:
    # Poppler may emit the entire time column before all titles. Reconstruct
    # visual lines from coordinates instead of trusting PDF drawing order.
    lines = []
    for word in sorted(words, key=lambda w: float(w.attrib['yMin'])):
        y = float(word.attrib['yMin'])
        if not lines or abs(y - lines[-1][0]) > 2:
            lines.append((y, [word]))
        else:
            lines[-1][1].append(word)
    return ' '.join(''.join(w.itertext()) for _, line in lines
                    for w in sorted(line, key=lambda w: float(w.attrib['xMin'])))


def check_layout(layout: dict) -> None:
    if not layout.get('days') or not any(d['pages'] for d in layout['days']):
        raise ValueError('Раскладка пуста')
    for day in layout['days']:
        if day.get('over'):
            raise ValueError(f"Блок не влезает в колонку: {day['title']}: {day['over']}")
        if not day['pages']:
            raise ValueError(f"Нет страниц: {day['title']}")


def check_pdf(pdf: Path, layout: dict, previews: Path | None = None) -> dict:
    check_layout(layout)
    result = subprocess.run(['pdftotext', '-bbox', str(pdf), '-'],
                            capture_output=True, check=True)
    root = ET.fromstring(result.stdout)
    ns = {'h': 'http://www.w3.org/1999/xhtml'}
    actual = root.findall('.//h:page', ns)
    expected = [(day, page) for day in layout['days'] for page in day['pages']]
    if previews and actual:
        previews.mkdir(parents=True, exist_ok=True)
        for number in sorted({1, (len(actual) + 1) // 2, len(actual)}):
            subprocess.run(['pdftoppm', '-f', str(number), '-l', str(number),
                            '-singlefile', '-jpeg', '-r', '80', str(pdf),
                            str(previews / f'page-{number:02}')], check=True,
                           stdout=subprocess.DEVNULL)
    if len(actual) != len(expected):
        raise ValueError(f'PDF: {len(actual)} страниц вместо {len(expected)} в раскладке '
                         '(возможен разрыв блока или пустой лист)')
    for number, (page, (day, planned)) in enumerate(zip(actual, expected), 1):
        width = float(page.attrib['width'])
        left = layout['margins']['left'] / 20
        col_width = layout['usable_w'] / layout['cols'] / 20
        columns = [[] for _ in range(layout['cols'])]
        for word in page.findall('.//h:word', ns):
            x = (float(word.attrib['xMin']) + float(word.attrib['xMax'])) / 2
            # Footer is page numbering; it must not make an otherwise empty page pass.
            if float(word.attrib['yMin']) >= float(page.attrib['height']) - layout['margins']['bottom'] / 20:
                continue
            col = min(layout['cols'] - 1, max(0, int((x - left) / col_width)))
            columns[col].append(word)
            if float(word.attrib['xMin']) < left - 3 or float(word.attrib['xMax']) > width - layout['margins']['right'] / 20 + 3:
                raise ValueError(f'PDF: текст выходит за поля на странице {number}')
        for col, blocks in enumerate(planned):
            text = normalized(reading_order(columns[col]))
            for block in blocks['items']:
                wanted = [block['name']] + [r['label'] + ' ' + r['title'] for r in block['rows']]
                for item in wanted:
                    if normalized(item) not in text:
                        raise ValueError(f"PDF, страница {number}, колонка {col + 1}: "
                                         f"не найден полный текст блока «{block['name']}»")
                    if re.search(r'\b\d{1,2}\+', item):
                        raise ValueError('В телепрограмме остался возрастной ценз')
    return {'pages': len(actual), 'expected_pages': len(expected),
            'checked_columns': True, 'checked_all_rows': True, 'ok': True}


if __name__ == '__main__':
    print(json.dumps(check_pdf(Path(sys.argv[1]),
                               json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')),
                               Path(sys.argv[3]) if len(sys.argv) > 3 else None),
                     ensure_ascii=False))
