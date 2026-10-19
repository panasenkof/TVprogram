# Телепрограмма

Сборка телепрограммы 15 федеральных каналов на неделю для **Ростова-на-Дону**:
DOCX и PDF в газетной вёрстке (A4, две колонки, блок канала не разрывается).
Одинаковые передачи склеиваются в одну строку; текст не вплотную к вертикальной линейке.

Источники:
- черновик: [prov-telegraf.ru/teleprogramma](https://prov-telegraf.ru/teleprogramma/)
- сверка (при конфликте главнее): [tv.yandex.ru/39](https://tv.yandex.ru/39)
  (Ростов-на-Дону; «Россия 1» = Россия 1-Дон)

## Автоматически в GitHub Actions

Каждое воскресенье в **10:00 по Москве** workflow **Weekly TV programme**
собирает следующую неделю (при отсутствии сетки — текущую), проверяет DOCX/PDF,
загружает их в `/Панасенко/Телепрограмма/` и отправляет итог в Telegram.
Результаты, отчёты и три превью сохраняются также в артефакте GitHub на 30 дней.
Нормальный объём после группировки — около 22–24 страниц.

**Первый запуск и получение секретов: [GITHUB_ACTIONS.md](GITHUB_ACTIONS.md).**
Нужны `YADISK_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` в Repository secrets.
Ручной пробный запуск доступен без секретов (включён параметр `dry_run`).

## Локально

```bash
pip install -r requirements.txt
npm install
python3 scripts/build_week.py
python3 scripts/measure.py nedelya.txt 12 2 0 layout.json
node scripts/render.js layout.json programma.docx
soffice --headless --convert-to pdf programma.docx
```

После сборки агент вызывает `python3 scripts/notify-telegram.py`.
Токен бота в репозиторий не класть: используйте переменные окружения локально
или Secrets соответствующей среды (GitHub Actions / Cursor).

Репозиторий нужно подключить в автоматизации (поле репозитория / environment).
Без него облачный агент стартует с пустой папкой и не находит skill и скрипты.

В поле инструкций Cursor достаточно короткой отсылки к `AUTOMATION.md` —
не копируйте туда весь skill. Правки вёрстки подхватываются из `main` сами.

