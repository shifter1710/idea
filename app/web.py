from __future__ import annotations

import html
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from app.config import BASE_DIR, load_settings
from app.web_repository import ParsedScaleRepository, ScaleEntryRecord, ScaleSummary
from app.web_service import CombinedEventResult, CombinedEventSpec, WebScoringService


def run() -> None:
    settings = load_settings()
    repository = ParsedScaleRepository(BASE_DIR)
    service = WebScoringService(repository)
    application = WebApplication(service)
    with make_server(settings.web_host, settings.web_port, application) as server:
        print(f"Web UI started on http://{settings.web_host}:{settings.web_port}", flush=True)
        server.serve_forever()


class WebApplication:
    HOME_SECTION_ORDER = (
        "Спринт и барьеры",
        "Средние дистанции",
        "Длинные дистанции",
        "Эстафеты",
        "Технические виды",
        "Шоссе и ходьба",
    )
    TECHNICAL_ORDER = {
        "Прыжок в длину": 10,
        "Тройной прыжок": 20,
        "Прыжок в высоту": 30,
        "Прыжок с шестом": 40,
        "Толкание ядра": 50,
        "Метание диска": 60,
        "Метание молота": 70,
        "Метание копья": 80,
        "Пятиборье": 90,
        "Пятиборье (в помещении)": 91,
        "Семиборье": 100,
        "Семиборье (в помещении)": 101,
        "Десятиборье": 110,
    }

    def __init__(self, service: WebScoringService) -> None:
        self.service = service

    def __call__(self, environ, start_response):
        method = environ["REQUEST_METHOD"].upper()
        path = environ.get("PATH_INFO", "/")
        query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        form = self._parse_form(environ) if method == "POST" else {}

        try:
            if path == "/":
                return self._respond_html(start_response, self.render_home())
            if path == "/calculate":
                return self._respond_html(start_response, self.render_calculator(query, form if method == "POST" else {}))
            if path.startswith("/scale/"):
                return self._respond_html(start_response, self.render_scale(path))
            return self._respond_html(start_response, self.render_not_found(), status="404 Not Found")
        except ValueError as exc:
            return self._respond_html(start_response, self.render_message("Ошибка", str(exc)), status="400 Bad Request")
        except LookupError as exc:
            return self._respond_html(start_response, self.render_message("Не найдено", str(exc)), status="404 Not Found")

    def render_home(self) -> str:
        scales = self.service.list_scales()
        grouped_cards = self._home_collections(scales)
        body_parts = [
            "<section class='hero'>"
            "<div class='hero-copy'>"
            "<h1>Очки World Athletics 2025</h1>"
            "<p>Полностью русская версия калькулятора очков по официальным таблицам World Athletics. Дисциплины собраны в спортивном порядке: от спринта к средним и длинным дистанциям, затем эстафеты, технические виды, шоссе и ходьба.</p>"
            "</div>"
            "<div class='hero-panel'>"
            "<div class='hero-note'>"
            "<strong>Быстрый старт</strong>"
            "<p>Выберите режим расчёта, введите дисциплину и результат. Для многодисциплинарного зачёта используйте сумму или сравнение наборов.</p>"
            "</div>"
            "<div class='hero-links'>"
            "<a class='button' href='/calculate'>Открыть калькулятор</a>"
            "<a class='button secondary' href='/calculate?mode=compare'>Сравнить наборы</a>"
            "</div>"
            "</div>"
            "</section>",
            "<section class='page-head compact search-panel'>"
            "<h2>Поиск дисциплины</h2>"
            "<p>Начните вводить название, код или раздел. Карточки ниже фильтруются сразу.</p>"
            "<input type='search' id='scale-search' placeholder='Например: 100, длина, барьеры, марафон'>"
            "</section>",
            "<section class='page-head compact search-panel'>"
            "<h2>Как читать дисциплины</h2>"
            "<p>Если дисциплина есть и на стадионе, и в помещении, на главной она показана один раз. Переключение на вариант в помещении делается уже в калькуляторе.</p>"
            "</section>",
        ]
        for section_title in self.HOME_SECTION_ORDER:
            cards = grouped_cards.get(section_title, [])
            if cards:
                body_parts.append(self._render_home_group(section_title, cards))
        body = "".join(body_parts)
        return self._layout("Очки World Athletics", body)

    def render_scale(self, path: str) -> str:
        scale_id = int(path.rsplit("/", 1)[1])
        scale = self.service.get_scale_summary(scale_id)
        if scale is None:
            raise LookupError("Дисциплина не найдена.")
        entries = self.service.list_scale_entries(scale_id)
        preview = entries[:120]
        rows = "".join(self._entry_row(entry) for entry in preview)
        body = (
            "<section class='page-head scale-head'>"
            f"<h1>{html.escape(self._display_name(scale))} · {self._sex_label(scale.sex)}</h1>"
            f"<p>{html.escape(scale.section_ru)} · {html.escape(scale.discipline_code)} · очки {scale.min_points}–{scale.max_points}</p>"
            "<div class='tag-row'>"
            f"<span class='info-tag'>{html.escape(self._sex_label(scale.sex))}</span>"
            f"<span class='info-tag'>{html.escape(scale.section_ru)}</span>"
            "</div>"
            "<div class='hero-links'>"
            f"<a class='button secondary' href='/calculate?scale_id={scale.scale_id}'>Рассчитать</a>"
            "</div>"
            "</section>"
            "<table><thead><tr>"
            "<th>Очки</th><th>Результат</th><th>Значение</th>"
            "</tr></thead><tbody>"
            f"{rows}"
            "</tbody></table>"
        )
        return self._layout(self._display_name(scale), body)

    def render_calculator(self, query: dict[str, list[str]], form: dict[str, list[str]]) -> str:
        scales = self.service.list_scales()
        selected_scale_id = (form.get("scale_id") or query.get("scale_id") or [""])[0]
        selected_scale = None
        if selected_scale_id.isdigit():
            selected_scale = self.service.get_scale_summary(int(selected_scale_id))
        selected_scale_ref = (form.get("scale_ref") or [""])[0].strip()
        if not selected_scale and selected_scale_ref:
            try:
                selected_scale = self._find_scale_by_label(selected_scale_ref)
            except LookupError:
                selected_scale = None
        single_indoor = (form.get("single_indoor") or query.get("single_indoor") or ["0"])[0] == "1"
        if not single_indoor and selected_scale and self._is_indoor(selected_scale):
            single_indoor = True
        search_query = (form.get("search") or query.get("search") or [""])[0].strip().lower()
        filtered_scales = self._filter_scales(scales, search_query)
        mode = (form.get("mode") or query.get("mode") or ["single"])[0]
        row_count = self._safe_int((form.get("row_count") or query.get("row_count") or ["4"])[0], default=4, min_value=2, max_value=8)
        compare_count = self._safe_int((form.get("compare_count") or query.get("compare_count") or ["3"])[0], default=3, min_value=1, max_value=6)
        combined_specs = self.service.list_combined_events()
        combined_key = (form.get("combined_key") or query.get("combined_key") or [combined_specs[0].key])[0]
        try:
            active_combined = self.service.get_combined_event(combined_key)
        except LookupError:
            active_combined = combined_specs[0]
        choice_scales = self._preferred_scale_choices(scales)
        scale_labels = [self._scale_label_text(scale) for scale in choice_scales]
        selected_display_scale = self._outdoor_partner(selected_scale) if selected_scale and self._has_indoor_variant(selected_scale) else selected_scale
        active_scale_ref = selected_scale_ref or (self._scale_label_text(selected_display_scale) if selected_display_scale else "")
        active_single_scale = self._resolve_scale_selection(active_scale_ref, single_indoor) if active_scale_ref else selected_scale
        if active_single_scale is None:
            active_single_scale = selected_scale

        result_block = ""
        if form:
            if mode == "single":
                result_block = self._render_single_result(form)
            elif mode == "sum":
                result_block = self._render_sum_result(form, row_count)
            elif mode == "compare":
                result_block = self._render_compare_result(form, compare_count)
            elif mode == "combined":
                result_block = self._render_combined_result(form)

        placeholder = "10.43" if active_single_scale and active_single_scale.unit == "time" else "8.42"
        if active_single_scale and active_single_scale.unit == "points":
            placeholder = "6200"
        hand_help = ""
        if active_single_scale and active_single_scale.hand_time_adjustment > 0:
            hand_help = (
                "<label class='inline-check'>"
                "<input type='checkbox' name='hand_timing' value='1'>"
                f"Ручной хронометраж (+{active_single_scale.hand_time_adjustment:.2f} сек по правилам WA)"
                "</label>"
            )
        unit_help = ""
        if active_single_scale and active_single_scale.unit == "points":
            unit_help = (
                "<p class='meta'>Для многоборья вводится уже итоговая сумма очков многоборья. "
                "Калькулятор не складывает автоматически виды внутри десятиборья, семиборья или пятиборья.</p>"
            )
        elif active_single_scale and active_single_scale.unit == "time":
            unit_help = "<p class='meta'>Для беговых дисциплин можно вводить секунды, минуты и часы: например `10.43`, `1:58.00`, `2:10:35.50`.</p>"
        elif active_single_scale:
            unit_help = "<p class='meta'>Для технических дисциплин вводите результат в метрах, например `8.42` или `17.35`.</p>"
        indoor_help = ""
        indoor_checked = " checked" if single_indoor else ""
        if active_single_scale and self._has_indoor_variant(active_single_scale):
            indoor_help = (
                f"<label class='inline-check'><input type='checkbox' name='single_indoor' value='1'{indoor_checked}>"
                "Считать вариант в помещении</label>"
            )
        body_parts = [
            "<section class='page-head calculator-head'>"
            "<h1>Калькулятор очков</h1>"
            "<p>Интерфейс считает одиночный результат, сумму дисциплин и сравнение двух наборов. Если результат попадает между строками таблицы, берётся меньшая оценка.</p>"
            "</section>",
            "<section class='page-head compact search-panel'>"
            "<h2>Поиск дисциплин</h2>"
            "<form method='get' class='stack-form compact-form'>"
            f"<input type='hidden' name='mode' value='{html.escape(mode)}'>"
            f"<label>Фильтр<input type='search' name='search' value='{html.escape((form.get('search') or query.get('search') or [''])[0])}' placeholder='Например: 100, высота, копьё, mixed'></label>"
            "<button class='button secondary' type='submit'>Отфильтровать</button>"
            "</form>"
            f"<p class='meta'>Сейчас доступно {len(filtered_scales)} шкал из {len(scales)}. Варианты в помещении выбираются внутри калькулятора.</p>"
            "</section>",
            "<section class='calc-switches switch-panel'>"
            f"<a class='button {'active' if mode == 'single' else 'secondary'}' href='/calculate?mode=single&search={html.escape(search_query)}'>Одиночный расчёт</a>"
            f"<a class='button {'active' if mode == 'sum' else 'secondary'}' href='/calculate?mode=sum&row_count={row_count}&search={html.escape(search_query)}'>Сумма дисциплин</a>"
            f"<a class='button {'active' if mode == 'compare' else 'secondary'}' href='/calculate?mode=compare&compare_count={compare_count}&search={html.escape(search_query)}'>Сравнение наборов</a>"
            f"<a class='button {'active' if mode == 'combined' else 'secondary'}' href='/calculate?mode=combined&combined_key={html.escape(active_combined.key)}'>Многоборье</a>"
            "</section>",
        ]
        if mode == "single":
            body_parts.extend(
                [
                    "<section class='page-head'>"
                    "<h2>Одиночный расчёт</h2>"
                    "<p>Начните вводить дисциплину по-русски, по коду WA или по дистанции. Поле подсказывает варианты прямо при наборе.</p>"
                    f"{self._discipline_datalist(scale_labels, datalist_id='discipline-list-single')}"
                    "<form method='post' class='stack-form'>"
                    "<input type='hidden' name='mode' value='single'>"
                    f"<input type='hidden' name='search' value='{html.escape(search_query)}'>"
                    f"<input type='hidden' name='scale_id' value='{active_single_scale.scale_id if active_single_scale else ''}'>"
                    f"<label>Дисциплина<input list='discipline-list-single' name='scale_ref' value='{html.escape(active_scale_ref)}' placeholder='Например: Женщины · Спринт · 100 м · 100m' required></label>"
                    f"<label>Результат<input type='text' name='result' value='{html.escape((form.get('result') or [''])[0])}' placeholder='{html.escape(placeholder)}' required></label>"
                    f"{unit_help}"
                    f"{indoor_help}"
                    f"{hand_help}"
                    "<button class='button' type='submit'>Рассчитать</button>"
                    "</form>"
                    "</section>"
                ]
            )
        if mode == "sum":
            body_parts.append(self._render_sum_form(form, filtered_scales, scale_labels, row_count, search_query))
        if mode == "compare":
            body_parts.append(self._render_compare_form(form, filtered_scales, scale_labels, compare_count, search_query))
        if mode == "combined":
            body_parts.append(self._render_combined_form(form, active_combined))
        if result_block:
            body_parts.append(result_block)
        body = "".join(body_parts)
        return self._layout("Калькулятор", body)

    @staticmethod
    def render_message(title: str, message: str) -> str:
        return WebApplication._layout(title, f"<section class='page-head'><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p></section>")

    @staticmethod
    def render_not_found() -> str:
        return WebApplication.render_message("404", "Страница не найдена.")

    @staticmethod
    def _entry_row(entry: ScaleEntryRecord) -> str:
        return (
            "<tr>"
            f"<td>{entry.points}</td>"
            f"<td>{html.escape(entry.result_raw)}</td>"
            f"<td>{entry.result_value:.2f}</td>"
            "</tr>"
        )

    def _render_home_group(self, title: str, cards_data: list[dict[str, object]]) -> str:
        cards = []
        for item in cards_data:
            scale = item["scale"]
            tags = "".join(f"<span class='info-tag'>{html.escape(tag)}</span>" for tag in item["tags"])
            search_blob = item["search_blob"]
            tags_html = f"<div class='tag-row'>{tags}</div>" if tags else ""
            cards.append(
                f"<article class='scale-card' data-search='{html.escape(search_blob)}'>"
                f"<h2>{html.escape(self._display_name(scale))}</h2>"
                f"<p class='meta'>{html.escape(item['subtitle'])}</p>"
                f"{tags_html}"
                "<div class='hero-links'>"
                f"<a class='button secondary' href='/calculate?scale_id={scale.scale_id}'>Рассчитать</a>"
                f"<a class='button secondary' href='/scale/{scale.scale_id}'>Открыть шкалу</a>"
                "</div>"
                "</article>"
            )
        return f"<section><h2>{html.escape(title)}</h2><div class='card-grid'>{''.join(cards)}</div></section>"

    def _render_scale_group(self, title: str, scales: list[ScaleSummary], aggregate: bool = True) -> str:
        cards = []
        current_section = None
        for scale in scales:
            if scale.section_ru != current_section:
                current_section = scale.section_ru
                cards.append(f"<div class='section-tag'>{html.escape(current_section)}</div>")
            search_blob = self._search_blob(scale)
            meta_line = f"{html.escape(scale.discipline_code)} · очки {scale.min_points}-{scale.max_points}"
            if not aggregate:
                meta_line = f"{html.escape(self._sex_label(scale.sex))} · {html.escape(scale.discipline_code)} · очки {scale.min_points}-{scale.max_points}"
            cards.append(
                f"<article class='scale-card' data-search='{html.escape(search_blob)}'>"
                f"<h2>{html.escape(self._display_name(scale))}</h2>"
                f"<p class='meta'>{meta_line}</p>"
                "<div class='hero-links'>"
                f"<a class='button secondary' href='/scale/{scale.scale_id}'>Таблица</a>"
                f"<a class='button secondary' href='/calculate?scale_id={scale.scale_id}'>Расчёт</a>"
                "</div>"
                "</article>"
            )
        return f"<section><h2>{html.escape(title)}</h2><div class='card-grid'>{''.join(cards)}</div></section>"

    def _home_collections(self, scales: list[ScaleSummary]) -> dict[str, list[dict[str, object]]]:
        by_code: dict[str, list[ScaleSummary]] = defaultdict(list)
        for scale in scales:
            key = f"{self._home_section(scale)}:{self._base_discipline_code(scale.discipline_code)}"
            by_code[key].append(scale)
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for items in by_code.values():
            ordered = sorted(items, key=lambda item: (self._is_indoor(item), item.sex != "male", item.sex, item.scale_id))
            base_scale = next((item for item in ordered if not self._is_indoor(item)), ordered[0])
            section = self._home_section(base_scale)
            tags: list[str] = []
            sexes = {item.sex for item in ordered}
            if sexes == {"female"}:
                tags.append("женщины")
            elif sexes == {"male"}:
                tags.append("мужчины")
            elif sexes == {"mixed"}:
                tags.append("смешанные")
            if any(self._is_indoor(item) for item in ordered):
                tags.append("есть вариант в помещении")
            grouped[section].append(
                {
                    "scale": base_scale,
                    "subtitle": self._home_subtitle(base_scale, sexes),
                    "tags": tags,
                    "search_blob": " ".join(self._search_blob(item) for item in ordered),
                }
            )
        for section, items in grouped.items():
            items.sort(key=lambda item: self._home_sort_key(item["scale"]))
        return grouped

    def _home_section(self, scale: ScaleSummary) -> str:
        section = scale.section_ru
        if section in {"Спринт", "Барьеры"}:
            return "Спринт и барьеры"
        if section == "Средние дистанции":
            return "Средние дистанции"
        if section == "Длинные дистанции":
            return "Длинные дистанции"
        if section == "Эстафеты":
            return "Эстафеты"
        if section == "Прыжки, метания и многоборья":
            return "Технические виды"
        return "Шоссе и ходьба"

    def _home_subtitle(self, scale: ScaleSummary, sexes: set[str]) -> str:
        subtitle = scale.discipline_code
        if sexes == {"mixed"}:
            subtitle = f"Смешанная дисциплина · {subtitle}"
        elif sexes == {"female"}:
            subtitle = f"Женщины · {subtitle}"
        elif sexes == {"male"}:
            subtitle = f"{self._sex_label(scale.sex)} · {subtitle}"
        return subtitle

    def _home_sort_key(self, scale: ScaleSummary) -> tuple[float, int, str]:
        section = self._home_section(scale)
        name = self._display_name(scale)
        code = scale.discipline_code
        if section == "Технические виды":
            return (self.TECHNICAL_ORDER.get(name, 999.0), 0, name)
        if section == "Эстафеты":
            relay_match = re.fullmatch(r"4x(\d+)(m|km)(mix)?", self._base_discipline_code(code))
            if relay_match:
                distance, unit, mixed = relay_match.groups()
                base = float(distance) * (1000 if unit == "km" else 1)
                return (base, 1 if mixed else 0, name)
        numeric = self._event_distance_value(code)
        hurdle = 1 if "H" in code else 0
        steeple = 2 if "SC" in code else 0
        walk = 3 if "W" in code else 0
        mixed = 1 if scale.sex == "mixed" else 0
        return (numeric, hurdle + steeple + walk + mixed, name)

    def _event_distance_value(self, code: str) -> float:
        base = self._base_discipline_code(code)
        if base == "Mile":
            return 1609.34
        if base == "2 Miles":
            return 3218.68
        if base == "10 Miles":
            return 16093.4
        if base == "HM":
            return 21097.5
        if base == "Half Marathon":
            return 21097.5
        if base == "Marathon":
            return 42195
        if re.fullmatch(r"\d[\d,]* km", base):
            return float(base.replace(" km", "").replace(",", "")) * 1000
        if re.fullmatch(r"\d[\d,]*km", base):
            return float(base.replace("km", "").replace(",", "")) * 1000
        relay_match = re.fullmatch(r"4x(\d+)(m|km)(mix)?", base)
        if relay_match:
            distance, unit, _ = relay_match.groups()
            return float(distance) * (1000 if unit == "km" else 1)
        walk_match = re.fullmatch(r"(\d[\d,]*)(m|km)W", base)
        if walk_match:
            distance, unit = walk_match.groups()
            return float(distance.replace(",", "")) * (1000 if unit == "km" else 1)
        barrier_match = re.fullmatch(r"(\d[\d,]*)mH", base)
        if barrier_match:
            return float(barrier_match.group(1).replace(",", ""))
        steeple_match = re.fullmatch(r"(\d[\d,]*)m SC", base)
        if steeple_match:
            return float(steeple_match.group(1).replace(",", ""))
        metric_match = re.fullmatch(r"(\d[\d,]*)m", base)
        if metric_match:
            return float(metric_match.group(1).replace(",", ""))
        return 999999.0

    def _render_single_result(self, form: dict[str, list[str]]) -> str:
        scale_ref = (form.get("scale_ref") or [""])[0].strip()
        scale_id_raw = (form.get("scale_id") or ["0"])[0]
        prefer_indoor = (form.get("single_indoor") or ["0"])[0] == "1"
        if scale_ref:
            scale = self._resolve_scale_selection(scale_ref, prefer_indoor)
            if scale is None:
                raise LookupError("Дисциплина не найдена.")
            scale_id = scale.scale_id
        elif scale_id_raw.isdigit():
            scale_id = int(scale_id_raw)
        else:
            raise LookupError("Дисциплина не найдена.")
        use_hand_timing = form.get("hand_timing", ["0"])[0] == "1"
        scale, parsed, match = self.service.calculate_points(scale_id, form.get("result", [""])[0], use_hand_timing=use_hand_timing)
        distance = abs(match.result_value - parsed.adjusted_value)
        adjustment_line = ""
        if use_hand_timing and scale.hand_time_adjustment > 0:
            adjustment_line = (
                f"<p><strong>Поправка ручного хронометража:</strong> +{scale.hand_time_adjustment:.2f} сек. "
                f"В расчёт пошло {parsed.adjusted_value:.2f}.</p>"
            )
        return (
            "<section class='result-card'>"
            "<h2>Результат расчёта</h2>"
            "<div class='score-hero'>"
            f"<div class='score-value'>{match.points}<small>очков</small></div>"
            "<div class='score-meta'>"
            f"<p><strong>Дисциплина:</strong> {html.escape(self._display_name(scale))} · {self._sex_label(scale.sex)}</p>"
            f"<p><strong>Ввод:</strong> {html.escape(parsed.raw_input)} → {html.escape(parsed.normalized_display)}</p>"
            f"{adjustment_line}"
            f"<p><strong>Табличный результат:</strong> {html.escape(match.result_raw)}</p>"
            f"<p><strong>Отклонение:</strong> {distance:.2f} {'сек' if scale.unit == 'time' else ('м' if scale.unit == 'metric' else 'очков')}.</p>"
            f"<p><a href='/scale/{scale.scale_id}'>Открыть таблицу дисциплины</a></p>"
            "</div>"
            "</div>"
            "</section>"
        )

    def _render_sum_form(
        self,
        form: dict[str, list[str]],
        filtered_scales: list[ScaleSummary],
        scale_labels: list[str],
        row_count: int,
        search_query: str,
    ) -> str:
        rows = []
        for index in range(row_count):
            label_value = (form.get(f"sum_scale_{index}") or [""])[0]
            result_value = (form.get(f"sum_result_{index}") or [""])[0]
            hand_checked = " checked" if (form.get(f"sum_hand_{index}") or ["0"])[0] == "1" else ""
            indoor_checked = " checked" if (form.get(f"sum_indoor_{index}") or ["0"])[0] == "1" else ""
            rows.append(
                "<div class='calc-row'>"
                f"<label>Дисциплина<input list='discipline-list' name='sum_scale_{index}' value='{html.escape(label_value)}' placeholder='Начните вводить дисциплину'></label>"
                f"<label>Результат<input type='text' name='sum_result_{index}' value='{html.escape(result_value)}' placeholder='Например: 10.43, 1:58.00, 8.12'></label>"
                "<div class='check-stack'>"
                f"<label class='inline-check compact-check'><input type='checkbox' name='sum_indoor_{index}' value='1'{indoor_checked}>В помещении</label>"
                f"<label class='inline-check compact-check'><input type='checkbox' name='sum_hand_{index}' value='1'{hand_checked}>Ручное время</label>"
                "</div>"
                "</div>"
            )
        datalist = self._discipline_datalist(scale_labels)
        return (
            "<section class='page-head'>"
            "<h2>Сумма нескольких дисциплин</h2>"
            "<p>Можно собрать набор дисциплин и получить общую сумму очков.</p>"
            f"{datalist}"
            "<form method='post' class='stack-form'>"
            "<input type='hidden' name='mode' value='sum'>"
            f"<input type='hidden' name='search' value='{html.escape(search_query)}'>"
            f"<input type='hidden' name='row_count' value='{row_count}'>"
            f"{''.join(rows)}"
            "<div class='hero-links'>"
            "<button class='button' type='submit'>Посчитать сумму</button>"
            f"<a class='button secondary' href='/calculate?mode=sum&row_count={min(row_count + 1, 8)}&search={html.escape(search_query)}'>Добавить дисциплину</a>"
            "</div>"
            "</form>"
            "</section>"
        )

    def _render_sum_result(self, form: dict[str, list[str]], row_count: int) -> str:
        rows = []
        total = 0
        for index in range(row_count):
            label = (form.get(f"sum_scale_{index}") or [""])[0].strip()
            result = (form.get(f"sum_result_{index}") or [""])[0].strip()
            if not label or not result:
                continue
            scale = self._resolve_scale_selection(label, (form.get(f"sum_indoor_{index}") or ["0"])[0] == "1")
            if scale is None:
                raise LookupError(f"Дисциплина не найдена: {label}")
            use_hand = (form.get(f"sum_hand_{index}") or ["0"])[0] == "1"
            scale_summary, parsed, match = self.service.calculate_points(scale.scale_id, result, use_hand_timing=use_hand)
            total += match.points
            rows.append(
                "<tr>"
                f"<td>{html.escape(self._display_name(scale_summary))}</td>"
                f"<td>{html.escape(parsed.normalized_display)}</td>"
                f"<td>{match.points}</td>"
                f"<td>{html.escape(match.result_raw)}</td>"
                "</tr>"
            )
        if not rows:
            raise ValueError("Для суммы нужно заполнить хотя бы одну дисциплину и результат.")
        return (
            "<section class='result-card'>"
            "<h2>Сумма очков</h2>"
            f"<div class='score-value solo'>{total}<small>очков</small></div>"
            "<table><thead><tr><th>Дисциплина</th><th>Результат</th><th>Очки</th><th>Табличная строка</th></tr></thead><tbody>"
            f"{''.join(rows)}"
            "</tbody></table>"
            "</section>"
        )

    def _render_compare_form(
        self,
        form: dict[str, list[str]],
        filtered_scales: list[ScaleSummary],
        scale_labels: list[str],
        compare_count: int,
        search_query: str,
    ) -> str:
        rows = []
        for index in range(compare_count):
            left_label = (form.get(f"cmp_a_scale_{index}") or [""])[0]
            left_result = (form.get(f"cmp_a_result_{index}") or [""])[0]
            right_label = (form.get(f"cmp_b_scale_{index}") or [""])[0]
            right_result = (form.get(f"cmp_b_result_{index}") or [""])[0]
            left_hand = " checked" if (form.get(f"cmp_a_hand_{index}") or ["0"])[0] == "1" else ""
            right_hand = " checked" if (form.get(f"cmp_b_hand_{index}") or ["0"])[0] == "1" else ""
            left_indoor = " checked" if (form.get(f"cmp_a_indoor_{index}") or ["0"])[0] == "1" else ""
            right_indoor = " checked" if (form.get(f"cmp_b_indoor_{index}") or ["0"])[0] == "1" else ""
            rows.append(
                "<div class='compare-row'>"
                "<div class='compare-col'>"
                f"<label>Набор А: дисциплина<input list='discipline-list' name='cmp_a_scale_{index}' value='{html.escape(left_label)}' placeholder='Дисциплина'></label>"
                f"<label>Набор А: результат<input type='text' name='cmp_a_result_{index}' value='{html.escape(left_result)}' placeholder='Результат'></label>"
                f"<label class='inline-check compact-check'><input type='checkbox' name='cmp_a_indoor_{index}' value='1'{left_indoor}>В помещении</label>"
                f"<label class='inline-check compact-check'><input type='checkbox' name='cmp_a_hand_{index}' value='1'{left_hand}>Ручное время</label>"
                "</div>"
                "<div class='compare-col'>"
                f"<label>Набор Б: дисциплина<input list='discipline-list' name='cmp_b_scale_{index}' value='{html.escape(right_label)}' placeholder='Дисциплина'></label>"
                f"<label>Набор Б: результат<input type='text' name='cmp_b_result_{index}' value='{html.escape(right_result)}' placeholder='Результат'></label>"
                f"<label class='inline-check compact-check'><input type='checkbox' name='cmp_b_indoor_{index}' value='1'{right_indoor}>В помещении</label>"
                f"<label class='inline-check compact-check'><input type='checkbox' name='cmp_b_hand_{index}' value='1'{right_hand}>Ручное время</label>"
                "</div>"
                "</div>"
            )
        datalist = self._discipline_datalist(scale_labels)
        return (
            "<section class='page-head'>"
            "<h2>Сравнение двух наборов</h2>"
            "<p>Можно сравнить двух спортсменов, два состава или два набора дисциплин. Внизу будет сумма по каждому набору и разница.</p>"
            f"{datalist}"
            "<form method='post' class='stack-form'>"
            "<input type='hidden' name='mode' value='compare'>"
            f"<input type='hidden' name='search' value='{html.escape(search_query)}'>"
            f"<input type='hidden' name='compare_count' value='{compare_count}'>"
            f"{''.join(rows)}"
            "<div class='hero-links'>"
            "<button class='button' type='submit'>Сравнить наборы</button>"
            f"<a class='button secondary' href='/calculate?mode=compare&compare_count={min(compare_count + 1, 6)}&search={html.escape(search_query)}'>Добавить строку</a>"
            "</div>"
            "</form>"
            "</section>"
        )

    def _render_compare_result(self, form: dict[str, list[str]], compare_count: int) -> str:
        left_rows = []
        right_rows = []
        left_total = 0
        right_total = 0
        for index in range(compare_count):
            left_label = (form.get(f"cmp_a_scale_{index}") or [""])[0].strip()
            left_result = (form.get(f"cmp_a_result_{index}") or [""])[0].strip()
            if left_label and left_result:
                scale = self._resolve_scale_selection(left_label, (form.get(f"cmp_a_indoor_{index}") or ["0"])[0] == "1")
                if scale is None:
                    raise LookupError(f"Дисциплина не найдена: {left_label}")
                _, parsed, match = self.service.calculate_points(scale.scale_id, left_result, use_hand_timing=(form.get(f"cmp_a_hand_{index}") or ["0"])[0] == "1")
                left_total += match.points
                left_rows.append(
                    f"<tr><td>{html.escape(self._display_name(scale))}</td><td>{html.escape(parsed.normalized_display)}</td><td>{match.points}</td></tr>"
                )
            right_label = (form.get(f"cmp_b_scale_{index}") or [""])[0].strip()
            right_result = (form.get(f"cmp_b_result_{index}") or [""])[0].strip()
            if right_label and right_result:
                scale = self._resolve_scale_selection(right_label, (form.get(f"cmp_b_indoor_{index}") or ["0"])[0] == "1")
                if scale is None:
                    raise LookupError(f"Дисциплина не найдена: {right_label}")
                _, parsed, match = self.service.calculate_points(scale.scale_id, right_result, use_hand_timing=(form.get(f"cmp_b_hand_{index}") or ["0"])[0] == "1")
                right_total += match.points
                right_rows.append(
                    f"<tr><td>{html.escape(self._display_name(scale))}</td><td>{html.escape(parsed.normalized_display)}</td><td>{match.points}</td></tr>"
                )
        if not left_rows and not right_rows:
            raise ValueError("Для сравнения нужно заполнить хотя бы один результат.")
        delta = left_total - right_total
        winner = "Набор А впереди" if delta > 0 else "Набор Б впереди" if delta < 0 else "Ничья"
        left_table_rows = "".join(left_rows) or "<tr><td colspan='3'>Нет строк</td></tr>"
        right_table_rows = "".join(right_rows) or "<tr><td colspan='3'>Нет строк</td></tr>"
        return (
            "<section class='result-card'>"
            "<h2>Сравнение наборов</h2>"
            "<div class='duel-summary'>"
            f"<div class='duel-pill'><span>Набор А</span><strong>{left_total}</strong><small>очков</small></div>"
            f"<div class='duel-pill'><span>Набор Б</span><strong>{right_total}</strong><small>очков</small></div>"
            f"<div class='duel-pill accent'><span>Разница</span><strong>{abs(delta)}</strong><small>{html.escape(winner)}</small></div>"
            "</div>"
            "<div class='compare-tables'>"
            "<div><h3>Набор А</h3><table><thead><tr><th>Дисциплина</th><th>Результат</th><th>Очки</th></tr></thead><tbody>"
            f"{left_table_rows}"
            "</tbody></table></div>"
            "<div><h3>Набор Б</h3><table><thead><tr><th>Дисциплина</th><th>Результат</th><th>Очки</th></tr></thead><tbody>"
            f"{right_table_rows}"
            "</tbody></table></div>"
            "</div>"
            "</section>"
        )

    def _render_combined_form(self, form: dict[str, list[str]], active_spec: CombinedEventSpec) -> str:
        options = "".join(
            f"<option value='{html.escape(spec.key)}'{' selected' if spec.key == active_spec.key else ''}>{html.escape(spec.title_ru)}</option>"
            for spec in self.service.list_combined_events()
        )
        rows = []
        for discipline in active_spec.disciplines:
            value = (form.get(f"combined_{discipline.code}") or [""])[0]
            checked = " checked" if (form.get(f"combined_hand_{discipline.code}") or ["0"])[0] == "1" else ""
            scale = self.service.find_scale(active_spec.sex, discipline.code)
            hand_help = ""
            placeholder = "8.42"
            if scale is not None:
                if scale.unit == "time":
                    placeholder = "10.43"
                elif scale.unit == "points":
                    placeholder = "6200"
                if scale.hand_time_adjustment > 0:
                    hand_help = (
                        f"<label class='inline-check compact-check'><input type='checkbox' name='combined_hand_{discipline.code}' value='1'{checked}>"
                        f"Ручное время (+{scale.hand_time_adjustment:.2f})</label>"
                    )
            rows.append(
                "<div class='combined-row'>"
                f"<div><strong>{html.escape(discipline.label_ru)}</strong><p class='meta'>{html.escape(discipline.code)}</p></div>"
                f"<label>Результат<input type='text' name='combined_{discipline.code}' value='{html.escape(value)}' placeholder='{html.escape(placeholder)}'></label>"
                f"{hand_help or '<div></div>'}"
                "</div>"
            )
        return (
            "<section class='page-head'>"
            "<h2>Многоборье</h2>"
            "<p>Выберите формат многоборья и введите результаты по видам. Калькулятор сам посчитает очки по каждому виду и общую сумму.</p>"
            "<form method='post' class='stack-form'>"
            "<input type='hidden' name='mode' value='combined'>"
            "<label>Формат многоборья<select name='combined_key'>"
            f"{options}"
            "</select></label>"
            "<p class='meta'>Если заполнены не все виды, будет показана промежуточная сумма. Итоговая шкала `Dec./Hept./Pent.` при этом не используется напрямую.</p>"
            f"{''.join(rows)}"
            "<button class='button' type='submit'>Посчитать многоборье</button>"
            "</form>"
            "</section>"
        )

    def _render_combined_result(self, form: dict[str, list[str]]) -> str:
        key = (form.get("combined_key") or [""])[0]
        spec = self.service.get_combined_event(key)
        raw_results = {
            discipline.code: (form.get(f"combined_{discipline.code}") or [""])[0]
            for discipline in spec.disciplines
        }
        hand_flags = {
            discipline.code: (form.get(f"combined_hand_{discipline.code}") or ["0"])[0] == "1"
            for discipline in spec.disciplines
        }
        result = self.service.calculate_combined_event(key, raw_results, hand_flags)
        return self._render_combined_result_card(result)

    def _render_combined_result_card(self, result: CombinedEventResult) -> str:
        rows = []
        for row in result.rows:
            hand_note = " + ручное время" if row.use_hand_timing else ""
            rows.append(
                "<tr>"
                f"<td>{html.escape(row.discipline.label_ru)}</td>"
                f"<td>{html.escape(row.parsed.normalized_display)}{html.escape(hand_note)}</td>"
                f"<td>{row.match.points}</td>"
                f"<td>{html.escape(row.match.result_raw)}</td>"
                "</tr>"
            )
        summary = (
            f"Промежуточная сумма по {result.completed_count} из {result.total_count} видов."
            if result.completed_count < result.total_count
            else f"Полная сумма по всем {result.total_count} видам."
        )
        return (
            "<section class='result-card'>"
            f"<h2>{html.escape(result.spec.title_ru)}</h2>"
            f"<div class='score-value solo'>{result.total_points}<small>очков</small></div>"
            f"<p class='meta'>{html.escape(summary)}</p>"
            "<table><thead><tr><th>Вид</th><th>Результат</th><th>Очки</th><th>Табличная строка</th></tr></thead><tbody>"
            f"{''.join(rows)}"
            "</tbody></table>"
            "</section>"
        )

    def _discipline_datalist(self, labels: list[str], datalist_id: str = "discipline-list") -> str:
        options = "".join(f"<option value='{html.escape(label)}'></option>" for label in labels)
        return f"<datalist id='{html.escape(datalist_id)}'>{options}</datalist>"

    def _find_scale_by_label(self, label: str) -> ScaleSummary:
        wanted = label.strip().lower()
        for scale in self._preferred_scale_choices(self.service.list_scales()):
            variants = {
                self._scale_label_text(scale).lower(),
                self._display_name(scale).lower(),
                self._base_discipline_code(scale.discipline_code).lower(),
                f"{self._sex_label(scale.sex).lower()} {self._display_name(scale).lower()}",
                f"{self._sex_label(scale.sex).lower()} {self._base_discipline_code(scale.discipline_code).lower()}",
            }
            if wanted in variants:
                return scale
        raise LookupError(f"Дисциплина не найдена: {label}")

    def _resolve_scale_selection(self, label: str, prefer_indoor: bool) -> ScaleSummary | None:
        scale = self._find_scale_by_label(label)
        if prefer_indoor:
            indoor = self.service.find_scale(scale.sex, f"{self._base_discipline_code(scale.discipline_code)} sh")
            if indoor is not None:
                return indoor
        return scale

    def _preferred_scale_choices(self, scales: list[ScaleSummary]) -> list[ScaleSummary]:
        choices = []
        seen: set[tuple[str, str, str]] = set()
        for scale in sorted(scales, key=lambda item: (item.sex, item.section_ru, item.scale_id)):
            key = (scale.sex, scale.section_ru, self._base_discipline_code(scale.discipline_code))
            if self._is_indoor(scale) and self.service.find_scale(scale.sex, self._base_discipline_code(scale.discipline_code)) is not None:
                continue
            if key in seen:
                continue
            seen.add(key)
            choices.append(scale)
        return choices

    @staticmethod
    def _base_discipline_code(code: str) -> str:
        return code.removesuffix(" sh")

    def _is_indoor(self, scale: ScaleSummary) -> bool:
        return scale.discipline_code.endswith(" sh") or "short track" in scale.discipline_name.lower()

    def _has_indoor_variant(self, scale: ScaleSummary) -> bool:
        base_code = self._base_discipline_code(scale.discipline_code)
        if scale.discipline_code.endswith(" sh"):
            return self.service.find_scale(scale.sex, base_code) is not None
        return self.service.find_scale(scale.sex, f"{base_code} sh") is not None

    def _outdoor_partner(self, scale: ScaleSummary | None) -> ScaleSummary | None:
        if scale is None or not self._is_indoor(scale):
            return scale
        return self.service.find_scale(scale.sex, self._base_discipline_code(scale.discipline_code)) or scale

    def _filter_scales(self, scales: list[ScaleSummary], needle: str) -> list[ScaleSummary]:
        if not needle:
            return scales
        return [scale for scale in scales if needle in self._search_blob(scale)]

    def _search_blob(self, scale: ScaleSummary) -> str:
        return " ".join(
            [
                self._sex_label(scale.sex).lower(),
                self._home_section(scale).lower(),
                self._display_name(scale).lower(),
                self._display_name(self._outdoor_partner(scale) or scale).lower(),
                scale.discipline_code.lower(),
                self._base_discipline_code(scale.discipline_code).lower(),
                self._discipline_alias_blob(scale).lower(),
            ]
        )

    def _scale_label_text(self, scale: ScaleSummary) -> str:
        return f"{self._sex_label(scale.sex)} · {self._home_section(scale)} · {self._display_name(scale)} · {self._base_discipline_code(scale.discipline_code)}"

    def _display_name(self, scale: ScaleSummary) -> str:
        return self._translate_discipline_name(scale.discipline_name)

    def _discipline_alias_blob(self, scale: ScaleSummary) -> str:
        name = self._display_name(scale)
        code = scale.discipline_code
        aliases = [name, code]
        if "м" in name:
            aliases.append(name.replace(" м", "м"))
        if "в помещении" in name:
            aliases.append(name.replace("в помещении", "indoor"))
        return " ".join(aliases)

    @staticmethod
    def _translate_discipline_name(name: str) -> str:
        exact = {
            "HJ": "Прыжок в высоту",
            "PV": "Прыжок с шестом",
            "LJ": "Прыжок в длину",
            "TJ": "Тройной прыжок",
            "SP": "Толкание ядра",
            "DT": "Метание диска",
            "HT": "Метание молота",
            "JT": "Метание копья",
            "Hept.": "Семиборье",
            "Hept. sh": "Семиборье (в помещении)",
            "Pent. sh": "Пятиборье (в помещении)",
            "Pent.": "Пятиборье",
            "Dec.": "Десятиборье",
            "4x100m": "Эстафета 4×100 м",
            "4x200m": "Эстафета 4×200 м",
            "4x400m": "Эстафета 4×400 м",
            "4x400mix": "Смешанная эстафета 4×400 м",
            "Mile": "Миля",
            "2 Miles": "2 мили",
            "10 Miles": "10 миль",
            "Half Marathon": "Полумарафон",
            "HM": "Полумарафон",
            "Marathon": "Марафон",
        }
        if name in exact:
            return exact[name]
        translated = name
        short_track = False
        if translated.endswith(" sh (short track)"):
            translated = translated.removesuffix(" sh (short track)")
            short_track = True
        elif translated.endswith(" sh"):
            translated = translated.removesuffix(" sh")
            short_track = True

        post_short_track_exact = {
            "Mile": "Миля",
            "2 Miles": "2 мили",
            "Hept.": "Семиборье",
            "Pent.": "Пятиборье",
            "4x400mix": "Смешанная эстафета 4×400 м",
        }
        translated = post_short_track_exact.get(translated, translated)

        if translated.endswith(" SC"):
            distance = translated.removesuffix(" SC")
            if distance.endswith("m") and distance[:-1].replace(",", "").isdigit():
                distance = f"{distance[:-1]} м"
            translated = f"{distance} с препятствиями"

        relay_match = re.fullmatch(r"4x(\d+)(m|km)(mix)?", translated)
        if relay_match:
            distance, unit, mixed = relay_match.groups()
            label = f"Эстафета 4×{distance} {'м' if unit == 'm' else 'км'}"
            if mixed:
                label = f"Смешанная {label.lower()}"
            translated = label

        hurdle_match = re.fullmatch(r"(\d[\d,]*)mH", translated)
        if hurdle_match:
            translated = f"{hurdle_match.group(1)} м с барьерами"

        walk_match = re.fullmatch(r"(\d[\d,]*)(m|km)W", translated)
        if walk_match:
            distance, unit = walk_match.groups()
            translated = f"Спортивная ходьба {distance} {'м' if unit == 'm' else 'км'}"

        if re.fullmatch(r"\d[\d,]*m", translated):
            translated = f"{translated[:-1]} м"
        elif re.fullmatch(r"\d[\d,]* km", translated):
            translated = translated.replace(" km", " км")
        elif re.fullmatch(r"\d[\d,]*km", translated):
            translated = translated.replace("km", " км")

        if short_track:
            translated = f"{translated} (в помещении)"
        return translated

    @staticmethod
    def _safe_int(raw: str, default: int, min_value: int, max_value: int) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        return max(min_value, min(max_value, value))

    @staticmethod
    def _sex_label(sex: str) -> str:
        if sex == "male":
            return "Мужчины"
        if sex == "female":
            return "Женщины"
        return "Смешанные"

    @staticmethod
    def _parse_form(environ) -> dict[str, list[str]]:
        size = int(environ.get("CONTENT_LENGTH", "0") or "0")
        raw_body = environ["wsgi.input"].read(size).decode("utf-8") if size else ""
        return parse_qs(raw_body, keep_blank_values=True)

    @staticmethod
    def _respond_html(start_response, html_text: str, status: str = "200 OK"):
        body = html_text.encode("utf-8")
        start_response(
            status,
            [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ],
        )
        return [body]

    @staticmethod
    def _layout(title: str, body: str) -> str:
        styles = """
        :root {
          --bg: #efe6d8;
          --panel: rgba(255, 250, 242, 0.92);
          --panel-strong: #fffdf8;
          --ink: #1d1b19;
          --accent: #9d3c27;
          --accent-soft: #d58d62;
          --accent-deep: #6e2417;
          --line: #dccfbf;
          --line-strong: #ceb79f;
          --muted: #5a544d;
          --shadow: 0 18px 44px rgba(67, 45, 29, .10);
        }
        * { box-sizing: border-box; }
        body {
          margin: 0;
          font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
          background:
            radial-gradient(circle at top left, #fff8ec 0, rgba(255,248,236,.7) 28%, transparent 52%),
            radial-gradient(circle at bottom right, rgba(213,141,98,.18), transparent 32%),
            linear-gradient(180deg, #e9dcc8, #f5efe5 42%, #efe7dc);
          color: var(--ink);
        }
        a { color: var(--accent); text-decoration: none; }
        .shell { max-width: 1200px; margin: 0 auto; padding: 24px; }
        .topbar {
          display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between;
          position: sticky; top: 0; z-index: 10;
          padding: 14px 0 18px;
          border-bottom: 1px solid rgba(206, 183, 159, .65);
          margin-bottom: 24px;
          backdrop-filter: blur(10px);
          background: linear-gradient(180deg, rgba(245,239,229,.92), rgba(245,239,229,.62));
        }
        .brand { font-size: 28px; font-weight: 700; letter-spacing: .03em; }
        .nav { display: flex; flex-wrap: wrap; gap: 14px; }
        .nav a {
          padding: 10px 14px;
          border-radius: 999px;
          color: var(--ink);
          background: rgba(255,255,255,.42);
          border: 1px solid rgba(206,183,159,.5);
        }
        .hero, .page-head, .result-card, .scale-card, .stack-form, table {
          background: var(--panel);
          border: 1px solid rgba(220, 207, 191, .95);
          border-radius: 22px;
          box-shadow: var(--shadow);
          overflow: hidden;
          background-clip: padding-box;
        }
        .hero, .page-head, .result-card, .stack-form { padding: 24px; margin-bottom: 24px; }
        .page-head.compact { padding: 18px 24px; }
        .hero {
          display: grid;
          grid-template-columns: minmax(0, 1.3fr) minmax(280px, .7fr);
          gap: 22px;
          align-items: stretch;
          background:
            linear-gradient(135deg, rgba(255,251,245,.97), rgba(248,239,227,.88)),
            radial-gradient(circle at top right, rgba(157,60,39,.12), transparent 40%);
        }
        .hero-copy { display: grid; gap: 18px; }
        .hero-panel {
          display: grid;
          gap: 16px;
          align-content: space-between;
          background: linear-gradient(180deg, rgba(250,242,230,.86), rgba(255,255,255,.7));
          border: 1px solid rgba(206,183,159,.75);
          border-radius: 18px;
          padding: 20px;
          overflow: hidden;
        }
        .hero-note p { margin-bottom: 0; }
        .hero h1, .page-head h1 { margin: 0 0 8px; font-size: 44px; line-height: .98; letter-spacing: -.02em; }
        .page-head h2, .result-card h2 { margin: 0 0 8px; font-size: 28px; }
        .hero p, .page-head p, .meta { color: var(--muted); }
        .button {
          display: inline-block; border: 0; border-radius: 999px; background: linear-gradient(180deg, var(--accent), var(--accent-deep)); color: #fff;
          padding: 12px 18px; cursor: pointer; font: inherit;
          box-shadow: 0 12px 24px rgba(110, 36, 23, .18);
        }
        .button.secondary {
          background: linear-gradient(180deg, #f4e8d9, #ead6bf);
          color: var(--ink);
          box-shadow: none;
          border: 1px solid rgba(206,183,159,.8);
        }
        .button.active {
          background: linear-gradient(180deg, var(--accent), var(--accent-deep));
          box-shadow: inset 0 0 0 2px rgba(255,255,255,.25), 0 12px 24px rgba(110, 36, 23, .18);
        }
        .hero-links { display: flex; flex-wrap: wrap; gap: 10px; }
        .hero-stats, .tag-row, .duel-summary { display: flex; flex-wrap: wrap; gap: 12px; }
        .stat-pill, .info-tag, .duel-pill {
          display: inline-flex;
          flex-direction: column;
          gap: 2px;
          min-width: 110px;
          padding: 12px 14px;
          border-radius: 16px;
          background: rgba(255,255,255,.6);
          border: 1px solid rgba(206,183,159,.7);
          overflow: hidden;
        }
        .stat-pill span, .duel-pill strong { font-size: 28px; line-height: 1; }
        .stat-pill small, .duel-pill small, .duel-pill span, .info-tag { color: var(--muted); }
        .info-tag { min-width: auto; flex-direction: row; align-items: center; }
        .duel-pill.accent {
          background: linear-gradient(180deg, rgba(157,60,39,.12), rgba(213,141,98,.18));
          border-color: rgba(157,60,39,.25);
        }
        .calc-switches { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 24px; }
        .switch-panel {
          padding: 10px;
          border-radius: 20px;
          background: rgba(255,250,242,.68);
          border: 1px solid rgba(220,207,191,.85);
          box-shadow: var(--shadow);
          overflow: hidden;
        }
        .grid-two { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }
        .card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }
        .section-tag {
          color: var(--muted);
          font-size: 14px;
          text-transform: uppercase;
          letter-spacing: .08em;
          margin-top: 8px;
        }
        .scale-card {
          padding: 18px;
          transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
          background:
            linear-gradient(180deg, rgba(255,253,248,.92), rgba(252,245,235,.88));
        }
        .scale-card:hover {
          transform: translateY(-3px);
          border-color: rgba(157,60,39,.3);
          box-shadow: 0 22px 38px rgba(67, 45, 29, .12);
        }
        .scale-card h2 { margin: 0 0 8px; }
        .stack-form { display: grid; gap: 14px; }
        .compact-form { grid-template-columns: minmax(0, 1fr) auto; align-items: end; }
        .calc-row, .compare-row, .compare-tables, .combined-row {
          display: grid;
          gap: 14px;
        }
        .calc-row { grid-template-columns: minmax(0, 1.3fr) minmax(180px, .8fr) auto; }
        .combined-row {
          grid-template-columns: minmax(180px, .8fr) minmax(180px, 1fr) auto;
          align-items: end;
          padding: 14px;
          border: 1px solid var(--line);
          border-radius: 16px;
          background: linear-gradient(180deg, rgba(255,253,248,.94), rgba(249,241,230,.86));
        }
        .compare-row, .compare-tables { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .compare-col {
          display: grid;
          gap: 12px;
          padding: 14px;
          border: 1px solid var(--line);
          border-radius: 14px;
          background: linear-gradient(180deg, rgba(255,253,248,.94), rgba(249,241,230,.86));
          overflow: hidden;
        }
        .check-stack {
          display: grid;
          gap: 8px;
          align-self: end;
          padding-bottom: 10px;
        }
        label { display: grid; gap: 8px; font-weight: 700; }
        .inline-check { display: flex; align-items: center; gap: 10px; font-weight: 400; }
        .compact-check { align-self: end; padding-bottom: 12px; }
        input, select {
          width: 100%; padding: 12px 14px; border: 1px solid var(--line-strong); border-radius: 14px;
          background: var(--panel-strong); font: inherit; color: var(--ink);
          box-shadow: inset 0 1px 0 rgba(255,255,255,.75);
        }
        input[type='checkbox'] { width: auto; }
        input:focus, select:focus {
          outline: 2px solid rgba(157,60,39,.22);
          border-color: rgba(157,60,39,.55);
        }
        .search-panel {
          background:
            linear-gradient(180deg, rgba(255,251,245,.9), rgba(251,243,232,.88));
        }
        .calculator-head, .scale-head {
          background:
            linear-gradient(180deg, rgba(255,251,245,.96), rgba(247,238,226,.88));
        }
        .score-hero {
          display: grid;
          grid-template-columns: minmax(180px, .45fr) minmax(0, 1fr);
          gap: 20px;
          align-items: start;
        }
        .score-value {
          display: grid;
          align-content: center;
          gap: 6px;
          min-height: 160px;
          border-radius: 22px;
          background: linear-gradient(180deg, rgba(157,60,39,.96), rgba(110,36,23,.96));
          color: #fff;
          padding: 22px;
          font-size: 54px;
          line-height: .9;
          text-align: center;
          box-shadow: 0 20px 40px rgba(110,36,23,.22);
          overflow: hidden;
        }
        .score-value.solo { margin-bottom: 20px; min-height: 0; font-size: 46px; }
        .score-value small {
          font-size: 16px;
          letter-spacing: .08em;
          text-transform: uppercase;
          color: rgba(255,255,255,.78);
        }
        .score-meta {
          display: grid;
          gap: 2px;
          align-content: start;
        }
        table {
          width: 100%;
          border-collapse: separate;
          border-spacing: 0;
          overflow: hidden;
        }
        th, td { padding: 12px 14px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
        th {
          background: linear-gradient(180deg, #f1e3d0, #ead6bf);
          font-size: 14px;
          text-transform: uppercase;
          letter-spacing: .05em;
          color: var(--muted);
        }
        thead th:first-child { border-top-left-radius: 18px; }
        thead th:last-child { border-top-right-radius: 18px; }
        tbody tr:last-child td:first-child { border-bottom-left-radius: 18px; }
        tbody tr:last-child td:last-child { border-bottom-right-radius: 18px; }
        tbody tr:last-child td { border-bottom: 0; }
        @media (max-width: 900px) {
          .grid-two { grid-template-columns: 1fr; }
          .hero, .score-hero, .compact-form, .calc-row, .compare-row, .compare-tables, .combined-row { grid-template-columns: 1fr; }
          .hero h1, .page-head h1 { font-size: 32px; }
          .score-value { min-height: 0; font-size: 42px; }
          .shell { padding: 16px; }
        }
        """
        script = """
        <script>
        document.addEventListener('DOMContentLoaded', function () {
          const input = document.getElementById('scale-search');
          if (!input) return;
          const cards = Array.from(document.querySelectorAll('.scale-card[data-search]'));
          input.addEventListener('input', function () {
            const q = input.value.trim().toLowerCase();
            cards.forEach(function (card) {
              const hit = !q || (card.dataset.search || '').includes(q);
              card.style.display = hit ? '' : 'none';
            });
          });
        });
        </script>
        """
        navigation = (
            "<header class='topbar'>"
            "<div class='brand'>Очки WA 2025</div>"
            "<nav class='nav'>"
            "<a href='/'>Главная</a>"
            "<a href='/calculate'>Калькулятор</a>"
            "</nav>"
            "</header>"
        )
        return (
            "<!doctype html><html lang='ru'><head>"
            "<meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{html.escape(title)}</title>"
            f"<style>{styles}</style>"
            f"{script}</head><body><div class='shell'>"
            f"{navigation}{body}"
            "</div></body></html>"
        )
