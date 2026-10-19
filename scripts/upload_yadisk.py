#!/usr/bin/env python3
"""Upload and verify files via Yandex Disk REST API; never log credentials/URLs."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

FOLDER = '/Панасенко/Телепрограмма'
API = 'https://cloud-api.yandex.net/v1/disk'


class DiskError(RuntimeError):
    pass


class DiskClient:
    def __init__(self, token: str):
        if not token.strip():
            raise DiskError('Не задан секрет YADISK_TOKEN')
        self.token = token.strip()

    def api(self, method: str, endpoint: str = '/resources', **params) -> dict:
        url = API + endpoint + '?' + urllib.parse.urlencode(params)
        for attempt in range(3):
            req = urllib.request.Request(url, method=method, headers={
                'Authorization': 'OAuth ' + self.token, 'Accept': 'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=60) as response:
                    body = response.read()
                    return json.loads(body) if body else {}
            except urllib.error.HTTPError as exc:
                if method == 'PUT' and endpoint == '/resources' and exc.code == 409:
                    if self.api('GET', path=params['path'], fields='type').get('type') == 'dir':
                        return {}
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    hints = {401: 'обновите YADISK_TOKEN', 403: 'проверьте права disk.read и disk.write',
                             507: 'освободите место на Диске'}
                    raise DiskError(f"Яндекс Диск: HTTP {exc.code}; "
                                    f"{hints.get(exc.code, 'см. код ответа API')}") from None
            except (OSError, ValueError):
                if attempt == 2:
                    raise DiskError('Яндекс Диск: нет связи или некорректный ответ API') from None
            time.sleep(2 ** attempt)
        raise DiskError('Яндекс Диск: запрос не выполнен')

    def ensure_folder(self, folder: str = FOLDER) -> None:
        current = ''
        for part in PurePosixPath(folder).parts:
            if part == '/':
                continue
            current += '/' + part
            self.api('PUT', path=current)

    def upload(self, local: Path, remote: str) -> None:
        data = local.read_bytes()
        for attempt in range(3):
            link = self.api('GET', '/resources/upload', path=remote, overwrite='true')
            href = link.get('href', '')
            parsed = urllib.parse.urlsplit(href)
            if parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.yandex.net'):
                raise DiskError('Яндекс Диск: некорректная ссылка загрузки')
            # The signed upload link authenticates the PUT. Do not forward the OAuth token.
            req = urllib.request.Request(href, data=data, method='PUT', headers={
                'Content-Type': 'application/octet-stream'})
            try:
                with urllib.request.urlopen(req, timeout=120) as response:
                    response.read()
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise DiskError(f'Яндекс Диск: ошибка загрузки HTTP {exc.code}') from None
            except OSError:
                if attempt == 2:
                    raise DiskError('Яндекс Диск: ошибка связи при загрузке') from None
            time.sleep(2 ** attempt)
        digest = hashlib.sha256(data).hexdigest()
        for attempt in range(5):
            meta = self.api('GET', path=remote, fields='size,sha256')
            if meta.get('size') == len(data) and meta.get('sha256') == digest:
                return
            if attempt < 4:
                time.sleep(2)
        raise DiskError(f'Яндекс Диск: размер или SHA-256 не совпал для {local.name}')
