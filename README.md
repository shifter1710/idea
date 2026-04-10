# Athletics Web

Русскоязычный веб-калькулятор очков по официальным `World Athletics Scoring Tables of Athletics, 2025 revised edition`.

## Что теперь в проекте

- основа расчёта: официальный PDF `world_athletics_scoring_tables_2025.pdf`
- локальный кэш после парсинга: `world_athletics_scoring_2025.json`
- покрытие: `162` дисциплины (`80` мужских, `80` женских, `2` смешанных)
- правило между строками: берётся меньшая оценка из таблицы
- для ручного хронометража поддержаны поправки WA там, где они предусмотрены
- веб-слой разложен на отдельные модули: маршрутизация, handlers, формы, presenter, views и UI-components

Старая OCR/SQLite-ветка с книгой Полосина больше не является основной для веб-калькулятора.

## Запуск

```bash
pip install -r requirements.txt
python3 main.py
```

Для сервера через Docker Compose:

```bash
docker compose up -d --build
```

Если приложение запускается через systemd unit, после изменения unit-файла нужно выполнить:

```bash
cp deploy/systemd/athletics-web-compose.service /etc/systemd/system/athletics-web-compose.service
systemctl daemon-reload
systemctl restart athletics-web-compose.service
```

По умолчанию интерфейс поднимается на:

```text
http://127.0.0.1:8080
```

## Источник данных

- официальный PDF World Athletics 2025:
  `world_athletics_scoring_tables_2025.pdf`
- при первом запуске таблицы парсятся в:
  `world_athletics_scoring_2025.json`

## Основные страницы

- `/`
  главная страница с дисциплинами в спортивном порядке

- `/calculate`
  калькулятор очков с режимами `single`, `sum`, `compare`, `combined`

- `/scale/<id>`
  просмотр таблицы конкретной дисциплины

## Веб-архитектура

Новый web-слой разделён так:

- `app/web/app.py`
  bootstrap приложения и WSGI entrypoint

- `app/web/routes.py`
  маршрутизация HTTP-запросов

- `app/web/handlers.py`
  orchestration-логика страниц и mode dispatch

- `app/web/forms.py`
  typed parsing и нормализация query/form input

- `app/web/presenter.py`
  presentation-логика дисциплин, labels, indoor/outdoor resolution и поиск

- `app/web/views.py`
  серверный HTML-рендеринг страниц и result blocks

- `app/web/components.py`
  layout, стили и повторно используемые HTML-компоненты
