import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_week
import check_pdf
import upload_yadisk
import weekly


def response(payload):
    result = Mock()
    result.read.return_value = json.dumps(payload).encode()
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


class WeekTests(unittest.TestCase):
    def test_sunday_and_monday_target_weeks(self):
        self.assertEqual(build_week.weeks_for(date(2026, 10, 18))[0][0], date(2026, 10, 19))
        self.assertEqual(build_week.weeks_for(date(2026, 10, 19))[0][0], date(2026, 10, 26))
        self.assertEqual(build_week.weeks_for(date(2026, 12, 27))[0][-1], date(2027, 1, 3))

    def test_current_week_fallback_and_missing_days(self):
        tele = {'Первый канал': [('09.00', 'Новости', None)]}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(build_week, 'cached_get', return_value=''), \
                patch.object(build_week, 'load_week_sources', side_effect=[
                    ({}, {}), ({date(2026, 10, 19): 'fixture'}, {}),
                ]) as sources, \
                patch.object(build_week, 'parse_telegraf', return_value=tele), \
                contextlib.redirect_stdout(io.StringIO()):
            out, report = Path(folder) / 'week.txt', Path(folder) / 'report.json'
            code = build_week.main(['--today', '2026-10-19', '--out', str(out), '--report', str(report)])
            data = weekly.read_json(report)
            self.assertEqual(code, 0)
            self.assertEqual(data['monday'], '2026-10-19')
            self.assertEqual(data['kind'], 'current')
            self.assertEqual(sources.call_count, 2)  # Check next week's Yandex before fallback.
            self.assertEqual(len(data['missing_days']), 6)
            self.assertEqual(out.read_text().count('# '), 1)

    def test_next_week_yandex_can_work_without_telegraf_index(self):
        today = date(2026, 11, 1)
        monday = date(2026, 11, 2)
        yandex = {(monday, name): [
            {'hhmm': f'{h:02d}.00', 'title': f'Передача {h}'}
            for h in range(8, 16)
        ] for name, _ in build_week.CHANNELS[:10]}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(build_week, 'cached_get', return_value=''), \
                patch.object(build_week, 'load_week_sources', return_value=({}, yandex)) as sources, \
                contextlib.redirect_stdout(io.StringIO()):
            out, report = Path(folder) / 'week.txt', Path(folder) / 'report.json'
            code = build_week.main(['--today', today.isoformat(), '--out', str(out),
                                    '--report', str(report)])
            data = weekly.read_json(report)
        self.assertEqual(code, 0)
        self.assertEqual(data['monday'], monday.isoformat())
        self.assertEqual(data['kind'], 'next')
        self.assertEqual(sources.call_count, 1)
        self.assertEqual(data['yandex_days'], 10)

    def test_no_grid_is_failure_not_fabricated_schedule(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(build_week, 'cached_get', return_value=''), \
                patch.object(build_week, 'load_week_sources', return_value=({}, {})), \
                contextlib.redirect_stderr(io.StringIO()):
            out, report = Path(folder) / 'week.txt', Path(folder) / 'report.json'
            self.assertEqual(build_week.main(['--today', '2026-10-18', '--out', str(out),
                                              '--report', str(report)]), 2)
            self.assertFalse(out.exists())
            self.assertFalse(weekly.read_json(report)['ok'])

    def test_bad_yandex_channel_does_not_abort_other_channels(self):
        day = date(2026, 10, 26)
        valid = ('window.__INITIAL_STATE__ = ' + json.dumps({
            'channel': {'schedule': {'events': [{
                'start': '2026-10-26T09:00:00+03:00',
                'program': {'title': 'Новости'},
            }]}}}, ensure_ascii=False))
        def get(url, path):
            if 'tv.yandex.ru' in url:
                return 'window.__INITIAL_STATE__ = {broken' if '/16?' in url else valid
            return None

        problems = []
        with patch.object(build_week, 'CHANNELS', [('Первый канал', 16), ('Россия 1', 31)]), \
                patch.object(build_week, 'cached_get', side_effect=get), \
                contextlib.redirect_stderr(io.StringIO()):
            tele, yandex = build_week.load_week_sources(
                [day], {}, None, workers=2, source_errors=problems)
        self.assertEqual(tele, {})
        self.assertEqual(yandex[(day, 'Первый канал')], [])
        self.assertEqual(yandex[(day, 'Россия 1')][0]['title'], 'Новости')
        self.assertEqual(len(problems), 1)
        self.assertIn('Первый канал', problems[0])
        self.assertIn(day.isoformat(), problems[0])

    def test_failed_source_future_is_isolated(self):
        day = date(2026, 10, 26)
        def get(url, path):
            raise RuntimeError('fixture simulated connection failure')
        problems = []
        with patch.object(build_week, 'CHANNELS', [('НТВ', 11)]), \
                patch.object(build_week, 'cached_get', side_effect=get), \
                contextlib.redirect_stderr(io.StringIO()):
            tele, yandex = build_week.load_week_sources(
                [day], {}, None, workers=2, source_errors=problems)
        self.assertFalse(tele)
        self.assertEqual(yandex[(day, 'НТВ')], [])
        self.assertEqual(len(problems), 2)

    def test_yandex_wins_and_russia_one_is_don(self):
        day = date(2026, 10, 19)
        yandex = {(day, 'Первый канал'): [{
            'hhmm': '09.00', 'title': 'Название из Яндекса',
            'dt': datetime(2026, 10, 19, 9, 0, tzinfo=build_week.MSK)}]}
        with patch.object(build_week, 'parse_telegraf', return_value={
                'Первый канал': [('09.00', 'Старое название', None)]}):
            text, _ = build_week.assemble([day], {day: 'fixture'}, yandex)
        self.assertIn('Название из Яндекса', text)
        self.assertNotIn('Старое название', text)
        self.assertEqual(dict(build_week.CHANNELS)['Россия 1'], 31)

    def test_remove_both_forms_of_trailing_age_rating(self):
        for title in ('Фильм (12+)', 'Фильм 16+', 'Фильм (0+)  ',
                      'Фильм(18+)', 'Фильм 6+'):
            self.assertEqual(build_week.clean_title(title), 'Фильм')

    def test_plus_signs_inside_program_names_are_not_age_ratings(self):
        # Regression for the 2026-10-25 weekly run: «2+1» is a film.
        for title in ('Х/ф «2+1»', 'Фильм «16+1»', 'Фильм «18+2»', 'Игра 6+1',
                      'Урок 12+3', 'Семья 24+', 'Фильм «6+»', '16+'):
            with self.subTest(title=title):
                self.assertEqual(build_week.clean_title(title), title)


class DiskTests(unittest.TestCase):
    def test_missing_token(self):
        with self.assertRaisesRegex(upload_yadisk.DiskError, 'YADISK_TOKEN'):
            upload_yadisk.DiskClient(' ')

    def test_unicode_destination_overwrite_and_content_verification(self):
        disk = upload_yadisk.DiskClient('SECRET_TOKEN')
        content = b'real document bytes'
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'programma-2026-10-19.pdf'
            file.write_bytes(content)
            with patch.object(disk, 'api', side_effect=[
                {'href': 'https://uploader.disk.yandex.net/upload?signed=secret'},
                {'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()},
            ]) as api, patch('urllib.request.urlopen', return_value=response({})) as request:
                remote = upload_yadisk.FOLDER + '/' + file.name
                disk.upload(file, remote)
                self.assertEqual(api.call_args_list[0].kwargs, {'path': remote, 'overwrite': 'true'})
                self.assertEqual(api.call_args_list[1].kwargs['fields'], 'size,sha256')
                req = request.call_args.args[0]
                self.assertEqual(req.data, content)
                self.assertIsNone(req.get_header('Authorization'))

    def test_hash_mismatch_is_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'file.pdf'
            file.write_bytes(b'PDF')
            disk = upload_yadisk.DiskClient('secret')
            def api(method, endpoint='/resources', **kwargs):
                return ({'href': 'https://uploader.disk.yandex.net/upload'}
                        if endpoint.endswith('/upload') else {'size': 3, 'sha256': 'wrong'})
            with patch.object(disk, 'api', side_effect=api), \
                    patch('urllib.request.urlopen', return_value=response({})), \
                    patch('time.sleep'), self.assertRaisesRegex(upload_yadisk.DiskError, 'SHA-256'):
                disk.upload(file, '/file.pdf')

    def test_existing_folder_must_be_a_directory(self):
        disk = upload_yadisk.DiskClient('secret')
        conflict = urllib.error.HTTPError('https://cloud-api.yandex.net', 409, 'conflict', {}, None)
        with patch('urllib.request.urlopen', side_effect=[conflict, response({'type': 'dir'})]):
            disk.api('PUT', path='/Панасенко')
        with patch('urllib.request.urlopen', side_effect=[conflict, response({'type': 'file'})]), \
                self.assertRaisesRegex(upload_yadisk.DiskError, '409'):
            disk.api('PUT', path='/Панасенко')

    def test_api_errors_never_expose_token(self):
        disk = upload_yadisk.DiskClient('SUPER_SECRET')
        error = urllib.error.HTTPError('https://example/SUPER_SECRET', 401, 'SUPER_SECRET', {}, None)
        with patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaises(upload_yadisk.DiskError) as caught:
                disk.api('GET', path='/')
            self.assertNotIn('SUPER_SECRET', str(caught.exception))


class ReportingTests(unittest.TestCase):
    def test_current_week_and_gaps_are_explicit(self):
        state = {'build_ok': True, 'pages': 23, 'uploaded': ['/a.docx', '/a.pdf']}
        report = {'monday': '2026-10-19', 'kind': 'current', 'missing_days': ['2026-10-25'],
                  'both_empty': ['2026-10-25 НТВ'], 'reason': 'next week absent'}
        text = weekly.report_text(state, report, False, 'success')
        for value in ('частично', '19.10.2026–25.10.2026', '23 стр.', '2026-10-25',
                      'Взята текущая неделя', 'a.pdf'):
            self.assertIn(value, text)

    def test_scheduled_build_uses_last_sunday_even_on_monday(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            sunday = weekly.build_week_command(out, date(2026, 11, 1), scheduled=True)
            monday = weekly.build_week_command(out, date(2026, 11, 2), scheduled=True)
            thursday = weekly.build_week_command(out, date(2026, 11, 5), scheduled=True)
            self.assertEqual(sunday[-2:], ['--today', '2026-11-01'])
            self.assertEqual(monday[-2:], ['--today', '2026-11-01'])
            self.assertEqual(thursday[-2:], ['--today', '2026-11-01'])
            # Deliberate manual dispatch on Monday keeps the normal future-week logic.
            self.assertNotIn('--today', weekly.build_week_command(
                out, date(2026, 11, 2), scheduled=False))

    def test_environment_failure_and_no_build_report(self):
        text = weekly.report_text({}, {}, False, 'failure')
        self.assertIn('ошибка', text)
        self.assertIn('Сбой подготовки среды', text)
        self.assertIn('не определена', text)

    def test_interrupted_json_write_still_produces_failure_report(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stdout(io.StringIO()):
            out = Path(folder)
            (out / 'build-report.json').write_text('{"ok":', encoding='utf-8')
            weekly.write_report(out)
            text = (out / 'report.txt').read_text(encoding='utf-8')
            self.assertIn('ошибка', text)
            self.assertIn('build-report.json', text)

    def test_partial_upload_and_failure_are_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            for name in ('a.docx', 'a.pdf'):
                (out / name).write_bytes(b'document')
            weekly.write_json(out / 'run-state.json', {
                'build_ok': True, 'files': ['a.docx', 'a.pdf'], 'uploaded': []})
            monday = date(2026, 11, 2)
            weekly.write_json(out / 'build-report.json', {
                'monday': monday.isoformat(), 'kind': 'next',
                'week': [(monday + build_week.timedelta(days=i)).isoformat()
                         for i in range(7)],
                'missing_days': [], 'both_empty': [],
            })
            disk = Mock()
            disk.upload.side_effect = [None, upload_yadisk.DiskError('second file failed')]
            with patch.object(weekly, 'DiskClient', return_value=disk), self.assertRaises(upload_yadisk.DiskError):
                weekly.upload(out)
            state = weekly.read_json(out / 'run-state.json')
            self.assertEqual(state['uploaded'], [upload_yadisk.FOLDER + '/a.docx'])
            self.assertIn('second file failed', state['error'])

    def test_upload_preflight_rejects_stale_or_incomplete_before_disk_access(self):
        monday = date(2026, 11, 2)
        full = {
            'monday': monday.isoformat(),
            'week': [(monday + build_week.timedelta(days=i)).isoformat()
                     for i in range(7)],
            'kind': 'next', 'missing_days': [], 'both_empty': [],
        }
        invalid = [
            {'kind': 'current'},
            {'missing_days': ['2026-11-04']},
            {'both_empty': ['2026-11-02 НТВ', '2026-11-02 ТНТ',
                            '2026-11-02 СТС', '2026-11-02 Россия 1']},
            {'both_empty': [f'2026-11-02 канал-{i}' for i in range(11)]},
            {'week': full['week'][:6]},
        ]
        for change in invalid:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder, \
                    patch.object(weekly, 'DiskClient') as disk:
                out = Path(folder)
                weekly.write_json(out / 'run-state.json', {
                    'build_ok': True, 'files': ['test.docx', 'test.pdf'], 'uploaded': [],
                })
                weekly.write_json(out / 'build-report.json', {**full, **change})
                with self.assertRaisesRegex(ValueError, 'загрузк|неполная|неполная|отсутствуют'):
                    weekly.upload(out)
                self.assertEqual(weekly.read_json(out / 'run-state.json')['uploaded'], [])
                disk.assert_not_called()

    def test_upload_preflight_accepts_complete_next_week(self):
        monday = date(2026, 11, 2)
        report = {
            'monday': monday.isoformat(),
            'week': [(monday + build_week.timedelta(days=i)).isoformat()
                     for i in range(7)],
            'kind': 'next', 'missing_days': [],
            'both_empty': ['2026-11-02 НТВ', '2026-11-02 СТС'],
        }
        weekly.check_publication_readiness(report)

    def test_empty_yandex_group_uses_telegraf_or_counts_missing(self):
        day = date(2026, 11, 2)
        yandex = {(day, 'Первый канал'): [{'hhmm': 'bad', 'title': 'Новости'}]}
        with patch.object(build_week, 'parse_telegraf', return_value={
                'Первый канал': [('09.00', 'Новости', None)]}):
            text, report = build_week.assemble([day], {day: 'fixture'}, yandex)
        self.assertIn('Новости', text)
        self.assertEqual(report['yandex_days'], 0)
        self.assertEqual(report['telegraf_fallback'], [f'{day.isoformat()} Первый канал'])
        self.assertIn(f'{day.isoformat()} НТВ', report['both_empty'])

    def test_telegram_uses_identical_report_over_stdin_and_failure_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_CHAT_ID': '123'}, clear=True):
            out = Path(folder)
            text = 'Телепрограмма — ошибка\nПолный итоговый отчёт\n'
            (out / 'report.txt').write_text(text, encoding='utf-8')
            seen = []
            def send(*args, **kwargs):
                seen.append(kwargs['stdin'].read())
                return subprocess.CompletedProcess(args[0], 1)
            with patch.object(weekly.subprocess, 'run', side_effect=send), \
                    contextlib.redirect_stdout(io.StringIO()):
                weekly.notify(out)
            self.assertEqual(seen, [text])

    def test_missing_telegram_secrets_do_not_fail_or_send(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True), \
                patch.object(weekly.subprocess, 'run') as send, contextlib.redirect_stdout(io.StringIO()):
            weekly.notify(Path(folder))
            send.assert_not_called()

    def test_telegram_timeout_does_not_fail_document_build(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_CHAT_ID': '123'}, clear=True), \
                patch.object(weekly.subprocess, 'run', side_effect=subprocess.TimeoutExpired('notify', 120)), \
                contextlib.redirect_stdout(io.StringIO()):
            out = Path(folder)
            (out / 'report.txt').write_text('Полный отчёт', encoding='utf-8')
            weekly.notify(out)

    def test_invalid_pdf_never_reaches_upload(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(weekly, 'run', side_effect=RuntimeError('build failed')):
            out = Path(folder)
            with self.assertRaisesRegex(RuntimeError, 'build failed'):
                weekly.build(out)
            state = weekly.read_json(out / 'run-state.json')
            self.assertFalse(state['build_ok'])
            self.assertEqual(state['error'], 'build failed')
            with self.assertRaisesRegex(RuntimeError, 'не прошли проверку'):
                weekly.upload(out)


class PdfTests(unittest.TestCase):
    def layout(self):
        return {'cols': 2, 'usable_w': 10000, 'margins': {'left': 700, 'right': 620, 'bottom': 900},
                'days': [{'title': 'Понедельник', 'over': [], 'pages': [[{'items': [{
                    'name': 'НТВ', 'rows': [{'label': '09:00', 'title': 'Новости'}]}]}]]}]}

    def test_oversized_channel_is_rejected(self):
        layout = self.layout()
        layout['days'][0]['over'] = [['НТВ', 1.2]]
        with self.assertRaisesRegex(ValueError, 'не влезает'):
            check_pdf.check_layout(layout)

    def test_pdf_drawing_order_does_not_have_to_match_reading_order(self):
        # Real Poppler output can list every timestamp before any title.
        bbox = b'''<html xmlns="http://www.w3.org/1999/xhtml"><page width="595" height="842">
          <word xMin="50" xMax="80" yMin="60">NTV</word>
          <word xMin="50" xMax="80" yMin="90">09:00</word>
          <word xMin="50" xMax="80" yMin="110">10:00</word>
          <word xMin="100" xMax="130" yMin="90.1">News</word>
          <word xMin="100" xMax="130" yMin="110.1">Film</word>
        </page></html>'''
        layout = self.layout()
        block = layout['days'][0]['pages'][0][0]['items'][0]
        block.update(name='NTV', rows=[{'label': '09:00', 'title': 'News'}, {'label': '10:00', 'title': 'Film'}])
        with patch.object(check_pdf.subprocess, 'run', return_value=Mock(stdout=bbox)):
            self.assertTrue(check_pdf.check_pdf(Path('unused.pdf'), layout)['ok'])

    def test_blank_footer_only_or_truncated_page_is_rejected(self):
        for words in ('<word xMin="290" xMax="310" yMin="810">1</word>',
                      '<word xMin="50" xMax="90" yMin="60">НТВ</word>'):
            bbox = ('<html xmlns="http://www.w3.org/1999/xhtml"><body><doc>'
                    '<page width="595" height="842">' + words + '</page></doc></body></html>').encode()
            with patch.object(check_pdf.subprocess, 'run', return_value=Mock(stdout=bbox)), \
                    self.assertRaisesRegex(ValueError, 'не найден полный текст'):
                check_pdf.check_pdf(Path('unused.pdf'), self.layout())

    def _pdf_with_title(self, title):
        layout = self.layout()
        block = layout['days'][0]['pages'][0][0]['items'][0]
        block['name'] = 'НТВ'
        block['rows'][0]['title'] = title
        bbox = ('''<html xmlns="http://www.w3.org/1999/xhtml"><page width="595" height="842">
          <word xMin="50" xMax="80" yMin="60">НТВ</word>
          <word xMin="50" xMax="80" yMin="90">09:00</word>
          <word xMin="100" xMax="210" yMin="90.1">''' + title +
                '''</word></page></html>''').encode('utf-8')
        return layout, bbox

    def test_pdf_accepts_plus_in_film_names(self):
        # Must pass the actual PDF validation path, not only title cleansing.
        for title in ('Х/ф «2+1»', '«16+1»', 'Фильм 18+2', 'Игра 12+3'):
            with self.subTest(title=title):
                layout, bbox = self._pdf_with_title(title)
                with patch.object(check_pdf.subprocess, 'run', return_value=Mock(stdout=bbox)):
                    self.assertTrue(check_pdf.check_pdf(Path('unused.pdf'), layout)['ok'])

    def test_pdf_rejects_genuine_age_rating_suffixes(self):
        for title in ('Новости (12+)', 'Фильм 16+', 'Мультфильм(6+)'):
            with self.subTest(title=title):
                layout, bbox = self._pdf_with_title(title)
                with patch.object(check_pdf.subprocess, 'run', return_value=Mock(stdout=bbox)), \
                        self.assertRaisesRegex(ValueError, 'возрастной ценз'):
                    check_pdf.check_pdf(Path('unused.pdf'), layout)

    def test_extra_blank_page_is_rejected(self):
        bbox = b'<html xmlns="http://www.w3.org/1999/xhtml"><page/><page/></html>'
        with patch.object(check_pdf.subprocess, 'run', return_value=Mock(stdout=bbox)), \
                self.assertRaisesRegex(ValueError, '2 страниц вместо 1'):
            check_pdf.check_pdf(Path('unused.pdf'), self.layout())


if __name__ == '__main__':
    unittest.main()
