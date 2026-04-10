# SQLite Manual Review

Файл базы:
- `athletics_points_text_parse_v3.sqlite`

## Что внутри

В базе 4 основные сущности:

- `sources`
  Описывает источник данных. Сейчас это одна книга.

- `disciplines`
  Справочник дисциплин.
  Основные поля:
  - `id`
  - `code` (`60`, `100`, `200`, `400`, `800`, `1000`, `1500`, `3000`, `5000`)
  - `name_ru`

- `scales`
  Описывает конкретную шкалу для:
  - дисциплины
  - пола
  - типа хронометража

  Важные поля:
  - `id`
  - `discipline_id`
  - `sex` (`male` / `female`)
  - `timing_type` (`auto`)

- `scale_entries`
  Основная таблица с результатами.
  Одна строка = одно значение таблицы очков.

  Важные поля:
  - `id`
  - `scale_id`
  - `points`
  - `result_raw`
  - `result_value`
  - `source_page`
  - `parse_method`
  - `anomaly_flag`

## Как это связано

- `disciplines` говорит, что такое код дисциплины.
- `scales` связывает дисциплину с полом и типом хронометража.
- `scale_entries` хранит сами значения `points -> result`.

Пример:
- дисциплина `1500`
- пол `female`
- тип `auto`
- дальше в `scale_entries` лежат строки этой шкалы с очками и временем.

## Что править вручную

Обычно вручную правятся строки в `scale_entries`.

Чаще всего нужно менять:
- `result_raw`
- `result_value`
- иногда `anomaly_flag` с `1` на `0`, если строка проверена вручную

Остальные таблицы обычно трогать не нужно.

## Полезные запросы

Показать все строки в удобном виде:

```sql
select
  e.id,
  d.code,
  d.name_ru,
  s.sex,
  e.points,
  e.result_raw,
  e.result_value,
  e.source_page,
  e.parse_method,
  e.anomaly_flag
from scale_entries e
join scales s on s.id = e.scale_id
join disciplines d on d.id = s.discipline_id
order by s.sex, cast(d.code as int), e.points desc;
```

Показать только подозрительные строки:

```sql
select
  e.id,
  d.code,
  s.sex,
  e.points,
  e.result_raw,
  e.result_value,
  e.source_page,
  e.parse_method
from scale_entries e
join scales s on s.id = e.scale_id
join disciplines d on d.id = s.discipline_id
where e.anomaly_flag = 1
order by s.sex, cast(d.code as int), e.points desc;
```

Показать одну конкретную шкалу, например `female 1000`:

```sql
select
  e.id,
  e.points,
  e.result_raw,
  e.result_value,
  e.source_page,
  e.parse_method,
  e.anomaly_flag
from scale_entries e
join scales s on s.id = e.scale_id
join disciplines d on d.id = s.discipline_id
where d.code = '1000' and s.sex = 'female'
order by e.points desc;
```

Пример ручной правки одной строки:

```sql
update scale_entries
set result_raw = '3.45,62',
    result_value = 225.62,
    anomaly_flag = 0
where id = 1234;
```

## Что сейчас выглядит лучше всего

По сравнению с предыдущей базой:
- записей стало больше: `12206` против `10918`
- аномалий стало сильно меньше: `145` против `3678`

Текущая база уже заметно чище, но не идеальна.

## Где остались основные ручные проверки

Самые проблемные группы сейчас:

- `male 800`
  Осталось `22` аномалии.
  Это главный хвост.

- `female 1000`
  Осталось `19` аномалий.

- `female 200`
  Осталось `15` аномалий.

- `female 400`
  Осталось `15` аномалий.

- `male 1500`
  Осталось `9` аномалий.

- `female 1500`
  Осталось `9` аномалий.

## Нормальные диапазоны, на которые можно ориентироваться

Грубо по текущей базе:

- `male 800`: примерно `98.00 .. 148.01`
- `male 1500`: примерно `201.92 .. 254.00`
- `female 1000`: примерно `122.54 .. 254.95`
- `female 200`: примерно `20.95 .. 29.87`
- `female 400`: примерно `46.74 .. 84.74`
- `female 3000`: примерно `477.80 .. 634.80`

Если значение резко выбивается за такой диапазон, это почти наверняка OCR-ошибка.

## Практический порядок ручной проверки

Рекомендуемый порядок:

1. Сначала открыть все строки с `anomaly_flag = 1`.
2. Начать с `male 800`.
3. Потом `female 1000`.
4. Потом `female 200` и `female 400`.
5. После ручной проверки выставлять `anomaly_flag = 0`.

## Если нужен экспорт перед ручной правкой

Можно выгрузить только подозрительные строки:

```sql
select
  e.id,
  d.code,
  s.sex,
  e.points,
  e.result_raw,
  e.result_value,
  e.source_page,
  e.parse_method
from scale_entries e
join scales s on s.id = e.scale_id
join disciplines d on d.id = s.discipline_id
where e.anomaly_flag = 1
order by s.sex, cast(d.code as int), e.points desc;
```

И уже по `id` править нужные записи обратно в SQLite.
