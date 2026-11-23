Основной запуск — GitHub Actions: `.github/workflows/weekly-tv.yml`,
суббота 10:00 МСК. Настройка: `GITHUB_ACTIONS.md`.

Следующая инструкция сохраняется для ручного запуска агентом в Cursor.
Следуй skill в этом репозитории: `.cursor/skills/tv-programma/SKILL.md` и `AGENTS.md`.

Не ищи skill в домашней папке, не качай HTML в чат и не собирай сетку вручную.
Сетку пишет `python3 scripts/build_week.py`. Склейка одинаковых передач и отступ
от линейки уже внутри скриптов — `grouping.py` отдельно не запускай.

Дальше как в skill: measure → render → PDF → Яндекс.Диск
`/Панасенко/Телепрограмма/` → в Telegram тот же краткий итоговый отчёт
(`python3 scripts/notify-telegram.py`, текст через stdin).

