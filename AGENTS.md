# Телепрограмма

Этот репозиторий — рабочая среда для еженедельной сборки телепрограммы
для Ростова-на-Дону.

Читай skill: `.cursor/skills/tv-programma/SKILL.md`.
Скрипты: `scripts/build_week.py`, `scripts/measure.py`, `scripts/render.js`.

Не ищи skill в домашней папке агента, не качай HTML источников в чат
и не восстанавливай сетку по памяти. Сетку собирает `python3 scripts/build_week.py`.
Источники: `https://prov-telegraf.ru/teleprogramma/` и `https://tv.yandex.ru/39`
(при конфликте — Яндекс; для «Россия 1» — **Россия 1-Дон**).

После загрузки на диск вызвать `python3 scripts/notify-telegram.py`.
Секреты: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (только в Cursor Secrets, не в репо).
