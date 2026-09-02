# Телепрограмма

Этот репозиторий — рабочая среда для еженедельной сборки телепрограммы
для Ростова-на-Дону.

Читай skill: `.cursor/skills/tv-programma/SKILL.md`.
Скрипты: `scripts/build_week.py`, `scripts/grouping.py`, `scripts/measure.py`,
`scripts/render.js`.

Не ищи skill в домашней папке агента, не качай HTML источников в чат
и не восстанавливай сетку по памяти. Сетку собирает `python3 scripts/build_week.py`.
Перед сборкой: `git pull --ff-only origin main` и проверь, что есть
`scripts/grouping.py`. Поле инструкций в Cursor само по git не обновляется.
Источники: `https://prov-telegraf.ru/teleprogramma/` и `https://tv.yandex.ru/39`
(при конфликте — Яндекс; для «Россия 1» — **Россия 1-Дон**).

Последним шагом отправить в Telegram тот же краткий итоговый отчёт, что и
в конце запуска: `python3 scripts/notify-telegram.py` (текст через stdin).
Секреты: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (только в Cursor Secrets, не в репо).
