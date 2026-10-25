#!/usr/bin/env python3
"""Render varied seven-day TV fixtures through actual DOCX/PDF validation."""
import argparse
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import weekly
from build_week import CHANNELS, day_heading


def fixture_week(days: list[date]) -> str:
    """A deterministic week with 15 channels/day, nightly slots and long names.

    Exercise the real 25 Oct regression (film «2+1») as well as distinct daily
    channel lengths. Never call external sources or publish files.
    """
    times = ['06.00', '07.00', '08.00', '09.00', '10.00', '11.00',
             '12.00', '14.00', '16.00', '18.00', '20.00', '22.00', '00.30']
    result = []
    for day_index, d in enumerate(days):
        result.append('# ' + day_heading(d))
        for channel_index, (channel, _) in enumerate(CHANNELS):
            result.append('== ' + channel)
            count = 8 + (day_index + channel_index) % 5
            for slot, time in enumerate(times[:count]):
                if slot in (1, 2) and channel_index % 3 == 0:
                    title = 'Новости и события'
                elif slot == 4 and channel_index % 4 == 0:
                    title = ('Документальный фильм «Очень длинное название '
                             'о путешествии по огромному миру и его открытиях»')
                elif day_index == 0 and channel_index == 0 and slot == 5:
                    title = 'Сверхдлинноесловобезразделителей' * 5
                else:
                    title = f'Передача {day_index + 1}-{channel_index + 1}-{slot + 1}'
                result.append(time + ' ' + title)
            if channel == 'ТНТ' and day_index == 3:
                result.append('22.35 Х/ф «2+1»')
            if channel_index == 0 and day_index in (0, 6):
                result.append('00.30 Ночная программа')
    return '\n'.join(result) + '\n'


def smoke(out: Path) -> None:
    monday = date(2026, 10, 26)
    days = [monday + timedelta(days=i) for i in range(7)]
    original_run = weekly.run

    def run_with_fixture(output, stage, command, state, timeout=300):
        if stage != 'build-week':
            return original_run(output, stage, command, state, timeout)
        (output / 'nedelya.txt').write_text(fixture_week(days), encoding='utf-8')
        weekly.write_json(output / 'build-report.json', {
            'ok': True, 'monday': monday.isoformat(), 'week': [d.isoformat() for d in days],
            'kind': 'next', 'missing_days': [], 'both_empty': [], 'telegraf_fallback': [],
            'telegraf_days': 7, 'yandex_days': 105,
        })

    out.mkdir(parents=True, exist_ok=True)
    with patch.object(weekly, 'run', side_effect=run_with_fixture):
        weekly.build(out)
    state = weekly.read_json(out / 'run-state.json')
    assert state['build_ok'] and state['pages'] >= 7, state
    print(json.dumps({'ok': True, 'fixture': 'varied synthetic week / 15 channels',
                      'pages': state['pages'], 'output': str(out)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    if args.output_dir:
        smoke(args.output_dir.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix='tv-smoke-') as temporary:
            smoke(Path(temporary))
