#!/usr/bin/env python3
"""CI entry points: build -> upload -> report -> (archive) -> notify."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from check_pdf import check_layout, check_pdf
from upload_yadisk import DiskClient, FOLDER

ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(out: Path, stage: str, command: list[str], state: dict, timeout: int = 300) -> None:
    state['stage'] = stage
    write_json(out / 'run-state.json', state)
    with (out / f'{stage}.log').open('w', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'Этап {stage}: код {result.returncode}; см. {stage}.log в артефакте')


def build_week_command(out: Path, run_date: date | None = None,
                       scheduled: bool | None = None) -> list[str]:
    """Anchor delayed Saturday cron runs to their Saturday, not a week later."""
    command = [sys.executable, 'scripts/build_week.py',
               '--out', str(out / 'nedelya.txt'),
               '--report', str(out / 'build-report.json')]
    if scheduled is None:
        scheduled = os.environ.get('TV_SCHEDULED_RUN') == 'true'
    if scheduled:
        today = run_date or datetime.now(ZoneInfo('Europe/Moscow')).date()
        last_saturday = today - timedelta(days=(today.weekday() - 5) % 7)
        command += ['--today', last_saturday.isoformat()]
    week = os.environ.get('TV_WEEK', 'auto')
    if week in ('current', 'next'):
        command += ['--week', week]
    return command


def build(out: Path) -> None:
    state = {'build_ok': False, 'uploaded': [], 'files': [], 'stage': 'build-week'}
    write_json(out / 'run-state.json', state)
    # A retry in the same working tree must not publish leftovers from a failed build.
    for pattern in ('programma*.docx', 'programma*.pdf', 'build-report.json', 'layout.json',
                    'pdf-check.json', 'nedelya.txt', 'report.txt'):
        for path in out.glob(pattern):
            path.unlink()
    try:
        run(out, 'build-week', build_week_command(out), state, 1500)
        report = read_json(out / 'build-report.json')
        monday = date.fromisoformat(report['monday'])
        if not report.get('ok') or monday.weekday() != 0:
            raise ValueError('В build-report.json нет корректной собранной недели')
        run(out, 'measure', [sys.executable, 'scripts/measure.py', str(out / 'nedelya.txt'),
                             '12', '2', '0', str(out / 'layout.json')], state)
        layout = read_json(out / 'layout.json')
        check_layout(layout)
        name = 'programma-' + monday.isoformat()
        docx, pdf = out / (name + '.docx'), out / (name + '.pdf')
        run(out, 'render', ['node', 'scripts/render.js', str(out / 'layout.json'), str(docx)], state)
        office = shutil.which('soffice') or shutil.which('libreoffice')
        if not office:
            raise RuntimeError('Не найден LibreOffice (soffice)')
        run(out, 'pdf', [office, '-env:UserInstallation=' + (out / 'lo-profile').as_uri(),
                         '--headless', '--convert-to', 'pdf', '--outdir', str(out), str(docx)], state)
        if not pdf.is_file() or not pdf.stat().st_size:
            raise RuntimeError('LibreOffice не создал PDF; см. pdf.log')
        state['stage'] = 'check-pdf'
        write_json(out / 'run-state.json', state)
        try:
            checked = check_pdf(pdf, layout, out / 'previews')
        except Exception as exc:
            write_json(out / 'pdf-check.json', {'ok': False, 'error': safe_error(exc)})
            raise
        write_json(out / 'pdf-check.json', checked)
        state.update(build_ok=True, stage='built', pages=checked['pages'], files=[docx.name, pdf.name])
    except Exception as exc:
        state['error'] = safe_error(exc)
        raise
    finally:
        write_json(out / 'run-state.json', state)
        shutil.rmtree(out / 'lo-profile', ignore_errors=True)


def check_publication_readiness(report: dict) -> None:
    """Fail closed: never silently overwrite Disk files with stale/incomplete listings."""
    monday_str = report.get('monday', '')
    try:
        monday = date.fromisoformat(monday_str)
    except (TypeError, ValueError):
        raise ValueError('Нет проверенной даты понедельника; загрузка отменена') from None
    expected = [(monday + timedelta(days=i)).isoformat() for i in range(7)]
    if monday.weekday() != 0 or report.get('week') != expected:
        raise ValueError('В отчёте неполная или некорректная неделя; загрузка отменена')
    explicit_current = (report.get('kind') == 'current'
                        and os.environ.get('TV_WEEK') == 'current')
    if report.get('kind') != 'next' and not explicit_current:
        raise ValueError('Собрана текущая, а не следующая неделя; загрузка на Диск отменена')
    missing = report.get('missing_days') or []
    if missing:
        raise ValueError('В телепрограмме отсутствуют дни: ' + ', '.join(missing))
    # 15 channels * 7 days, with an allowed tolerance for occasional missing
    # individual channels. Missing an entire day or >=11 channel-days blocks.
    missing_channels = report.get('both_empty')
    if not isinstance(missing_channels, list):
        raise ValueError('Нет списка проверенных каналов; загрузка отменена')
    from collections import Counter
    per_day = Counter(item.split(' ', 1)[0] for item in missing_channels)
    if len(missing_channels) > 10 or any(count > 3 for count in per_day.values()):
        raise ValueError(
            f'Слишком неполная сетка: отсутствуют {len(missing_channels)} из 105 '
            'канал-дней (лимит 10, не более 3 в один день); загрузка отменена'
        )


def upload(out: Path) -> None:
    state = read_json(out / 'run-state.json')
    if not state.get('build_ok'):
        raise RuntimeError('Документы не прошли проверку, загрузка отменена')
    try:
        state['stage'] = 'preflight'
        write_json(out / 'run-state.json', state)
        check_publication_readiness(read_json(out / 'build-report.json'))
        state['stage'] = 'upload'
        disk = DiskClient(os.environ.get('YADISK_TOKEN', ''))
        disk.ensure_folder()
        for name in state['files']:
            remote = FOLDER + '/' + name
            disk.upload(out / name, remote)
            state.setdefault('uploaded', []).append(remote)
            write_json(out / 'run-state.json', state)
        state['stage'] = 'uploaded'
    except Exception as exc:
        state['error'] = safe_error(exc)
        raise
    finally:
        write_json(out / 'run-state.json', state)


def safe_error(exc: Exception) -> str:
    # Also redact locally: errors saved as artifacts must not contain secrets.
    text = str(exc)
    for name in ('YADISK_TOKEN', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
        value = os.environ.get(name, '').strip()
        if value:
            text = text.replace(value, '[скрыто]')
    return text[:700]


def report_text(state: dict, report: dict, dry_run: bool, job_status: str) -> str:
    errors = [state['error']] if state.get('error') else []
    if job_status != 'success' and not errors:
        errors.append('Сбой подготовки среды или выполнения; см. журнал GitHub Actions')
    uploaded = state.get('uploaded', [])
    if not state.get('build_ok') and not errors:
        errors.append('Сборка документов не завершена')
    if state.get('build_ok') and not dry_run and len(uploaded) != 2 and not errors:
        errors.append('Не все файлы загружены на Яндекс Диск')
    partial = bool(report.get('missing_days') or report.get('both_empty') or
                   report.get('telegraf_fallback') or report.get('source_errors') or
                   report.get('kind') == 'current')
    status = 'ошибка' if errors else ('частично' if partial else 'успех')
    lines = ['Телепрограмма — ' + status + (' (пробный запуск)' if dry_run else '')]
    monday = report.get('monday') or (report.get('week') or [None])[0]
    if monday:
        start = date.fromisoformat(monday)
        lines.append(f"Неделя: {start:%d.%m.%Y}–{start + timedelta(days=6):%d.%m.%Y}")
    else:
        lines.append('Неделя: не определена (сборка прервана)')
    lines.append('PDF: ' + (str(state['pages']) + ' стр.' if state.get('pages') else 'не создан/не проверен'))
    lines.append('Яндекс Диск: ' + ('пропущен в пробном запуске' if dry_run else FOLDER + '/'))
    lines += ['Загружен и проверен: ' + p.rsplit('/', 1)[-1] for p in uploaded]
    if not uploaded and not dry_run:
        lines.append('Файлы на Диск не загружены')
    lines.append('Пропущенные дни: ' + (', '.join(report.get('missing_days', [])) or 'нет'))
    empty = report.get('both_empty', [])
    if empty:
        lines.append(f'Нет сетки каналов: {len(empty)}; ' + '; '.join(empty[:5]) +
                     ('; полный список в build-report.json' if len(empty) > 5 else ''))
    fallback = report.get('telegraf_fallback', [])
    lines.append(f'Источники: Телеграф {report.get("telegraf_days", 0)}/7 дней; '
                 f'Яндекс {report.get("yandex_days", 0)} канал-дней; '
                 f'подстановка Телеграфа {len(fallback)}')
    source_errors = report.get('source_errors', [])
    if source_errors:
        lines.append(f'Ошибки источников: {len(source_errors)}; ' + '; '.join(source_errors[:3]) +
                     ('; полный список в build-report.json' if len(source_errors) > 3 else ''))
    if report.get('kind') == 'current':
        lines.append('Взята текущая неделя: ' + report.get('reason', 'следующая недоступна'))
    if errors:
        lines += ['Ошибка: ' + e for e in errors]
    ready = bool(os.environ.get('TELEGRAM_BOT_TOKEN', '').strip() and
                 os.environ.get('TELEGRAM_CHAT_ID', '').strip())
    lines.append('Telegram: ' + ('пропущен в пробном запуске' if dry_run else
                                ('настроен' if ready else 'пропущен — не заданы оба секрета')))
    server, repo, run_id = (os.environ.get(k, '') for k in ('GITHUB_SERVER_URL', 'GITHUB_REPOSITORY', 'GITHUB_RUN_ID'))
    if server and repo and run_id:
        lines.append(f'Запуск и артефакты: {server}/{repo}/actions/runs/{run_id}')
    return '\n'.join(lines) + '\n'


def write_report(out: Path) -> None:
    state, report = {}, {}
    for name, target in (('run-state.json', state), ('build-report.json', report)):
        try:
            target.update(read_json(out / name))
        except (OSError, ValueError, TypeError):
            state['error'] = f'Не удалось прочитать {name}; см. журналы сборки'
    text = report_text(state, report,
                       os.environ.get('TV_DRY_RUN') == 'true', os.environ.get('TV_JOB_STATUS', 'success'))
    (out / 'report.txt').write_text(text, encoding='utf-8')
    print(text, end='')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with Path(summary).open('a', encoding='utf-8') as stream:
            stream.write('```text\n' + text + '```\n')


def notify(out: Path) -> None:
    if not (out / 'report.txt').exists():
        write_report(out)
    if os.environ.get('TV_ARTIFACT_STATUS') == 'failure':
        print('::warning::Не удалось сохранить артефакты; документы могли остаться на Диске')
        state = read_json(out / 'run-state.json')
        state['error'] = (state.get('error', '') + '; не удалось сохранить артефакты GitHub').lstrip('; ')
        write_json(out / 'run-state.json', state)
        write_report(out)
    if not (os.environ.get('TELEGRAM_BOT_TOKEN', '').strip() and
            os.environ.get('TELEGRAM_CHAT_ID', '').strip()):
        print('Telegram пропущен: задайте TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID')
        return
    try:
        with (out / 'report.txt').open(encoding='utf-8') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/notify-telegram.py')],
                                    stdin=stream, timeout=120)
        sent = result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        sent = False
    if not sent:
        print('::warning::Telegram не принял отчёт; отчёт сохранён в Summary и артефакте')
        summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            with Path(summary).open('a', encoding='utf-8') as stream:
                stream.write('\nTelegram не принял отчёт (сборка файлов сохранена).\n')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'upload', 'report', 'notify'))
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'output')
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    try:
        {'build': build, 'upload': upload, 'report': write_report, 'notify': notify}[args.action](out)
        return 0
    except Exception as exc:
        print('error: ' + safe_error(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
