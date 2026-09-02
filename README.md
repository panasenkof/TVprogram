# Телепрограмма

Сборка телепрограммы 15 федеральных каналов РФ на неделю: DOCX и PDF
в газетной вёрстке (A4, две колонки, блок канала не разрывается).

Источник: [prov-telegraf.ru/teleprogramma](https://prov-telegraf.ru/teleprogramma/).

## Локально

```bash
pip install -r requirements.txt
npm install
python3 scripts/build_week.py
python3 scripts/measure.py nedelya.txt 12 2 0 layout.json
node scripts/render.js layout.json programma.docx
soffice --headless --convert-to pdf programma.docx
```

## Автоматизация Cursor

Репозиторий нужно подключить в автоматизации (поле репозитория / environment).
Без него облачный агент стартует с пустой папкой и не находит skill и скрипты.
