Это файл-инструкция облачного запуска. Поле инструкций в Cursor — копия:
после правок в git его нужно вставить сюда снова. Перед сборкой всегда
подтягивай origin/main, иначе сработает снимок среды со старыми скриптами.

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
test -f scripts/grouping.py
git log -1 --oneline
```

Если `scripts/grouping.py` нет — остановись: клонирован не тот репозиторий
или не ветка `main`.

Дальше следуй skill в этом репозитории: `.cursor/skills/tv-programma/SKILL.md`
и `AGENTS.md`.

Скрипты: `scripts/build_week.py`, `scripts/grouping.py`, `scripts/measure.py`,
`scripts/render.js`. Не ищи skill в домашней папке облачного агента.
`grouping.py` отдельно не запускай: его импортируют `build_week.py` и `measure.py`
(одинаковые передачи в одну строку; отступ от вертикальной линейки — в measure/render).

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
8. Последним шагом отправь в Telegram **тот же краткий итоговый отчёт**,
   что и в конце запуска (статус, даты недели, файлы на Диске, страницы PDF,
   пропуски/ошибки). Через stdin:
   `python3 scripts/notify-telegram.py <<'EOF' …отчёт… EOF`
   Секреты только из `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`, не печатать.
   Если переменных нет — не срывай задачу. Если сборка упала раньше —
   всё равно пришли отчёт об ошибке.

Не переносить из источника описания передач и возрастной ценз — только время и название.
