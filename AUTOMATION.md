Следуй skill в этом репозитории: `.cursor/skills/tv-programma/SKILL.md` и `AGENTS.md`.

Скрипты уже в репозитории: `scripts/build_week.py`, `scripts/measure.py`, `scripts/render.js`.
Не ищи skill в домашней папке облачного агента — его там нет.

Собери телепрограмму для Ростова-на-Дону на СЛЕДУЮЩУЮ неделю (понедельник–воскресенье
после ближайшего воскресенья, если запуск в воскресенье — на неделю, которая начинается
завтра). Если следующей недели нет в источниках — скрипт сам возьмёт текущую.

Не скачивай HTML в чат и не собирай сетку вручную.

1. `python3 scripts/build_week.py` — получишь `nedelya.txt` и короткий отчёт.
   Источники внутри скрипта: Телеграф и Яндекс ТВ Ростов (`tv.yandex.ru/39`).
   При конфликте — Яндекс; для «Россия 1» — «Россия 1-Дон».
2. `python3 scripts/measure.py nedelya.txt 12 2 0 layout.json`
3. `npm install` если нужно, затем `node scripts/render.js layout.json programma.docx`
4. `soffice --headless --convert-to pdf programma.docx` (или `libreoffice`).
   Не используй `/mnt/skills/public/docx/...`.
5. Проверь: `pdfinfo programma.pdf | grep Pages` (около 40 страниц), нет пустых
   листов и оборванных блоков. Две-три страницы: `pdftoppm -jpeg -r 80 programma.pdf p`.
6. Через MCP yadisk загрузи оба файла в `/Панасенко/Телепрограмма/` как
   `programma-ГГГГ-ММ-ДД.docx` и `programma-ГГГГ-ММ-ДД.pdf`
   (дата — поле `monday` в `build-report.json`).
7. Если в отчёте `missing_days` — собери неделю без них и напиши об этом.
   Не придумывай сетку.

Не переносить из источника описания передач и возрастной ценз — только время и название.
