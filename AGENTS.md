# Телепрограмма

Этот репозиторий — рабочая среда для еженедельной сборки телепрограммы
для Ростова-на-Дону.

Читай skill: `.cursor/skills/tv-programma/SKILL.md`.
Скрипты: `scripts/build_week.py`, `scripts/grouping.py`, `scripts/measure.py`,
`scripts/render.js`.

Не ищи skill в домашней папке агента, не качай HTML источников в чат
и не восстанавливай сетку по памяти. Сетку собирает `python3 scripts/build_week.py`.
Источники: `https://prov-telegraf.ru/teleprogramma/` и `https://tv.yandex.ru/39`
(при конфликте — Яндекс; для «Россия 1» — **Россия 1-Дон**).

Последним шагом отправить в Telegram тот же краткий итоговый отчёт, что и
в конце запуска: `python3 scripts/notify-telegram.py` (текст через stdin).
Секреты: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (в Secrets выбранной среды, не в репо).

Основная автоматизация — `.github/workflows/weekly-tv.yml`: воскресенье,
10:00 МСК. Инструкция настройки — `GITHUB_ACTIONS.md`. Сценарий
`scripts/weekly.py` вызывает существующие сборку и вёрстку, проверяет PDF,
загружает оба файла на Диск через REST API (`YADISK_TOKEN`) и отправляет отчёт.
В GitHub Actions MCP yadisk не используется. При отсутствии Telegram-секретов
уведомление пропускается, сборка продолжается. После группировки ожидаемо
около 22–24 страниц; проверять полноту текста и блоков, а не число 40.

