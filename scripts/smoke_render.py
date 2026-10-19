#!/usr/bin/env python3
"""Render a seven-day copy of the repository fixture, without network or secrets."""
import argparse
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import weekly
from build_week import day_heading


def smoke(out: Path) -> None:
    fixture = (weekly.ROOT / 'primer-sreda.txt').read_text(encoding='utf-8').split('\n', 1)[1]
    monday = date(2026, 10, 19)
    days = [monday + timedelta(days=i) for i in range(7)]
    original_run = weekly.run

    def run_with_fixture(output, stage, command, state, timeout=300):
        if stage != 'build-week':
            return original_run(output, stage, command, state, timeout)
        (output / 'nedelya.txt').write_text(''.join('# ' + day_heading(d) + '\n' + fixture for d in days),
                                            encoding='utf-8')
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
    print(json.dumps({'ok': True, 'fixture': 'primer-sreda.txt × 7',
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
