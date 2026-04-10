from __future__ import annotations

import html

from app.web.components import render_datalist, render_field_error, render_form_alert, render_layout
from app.web.constants import HOME_SECTION_ORDER, MODE_COMBINED, MODE_COMPARE, MODE_SINGLE, MODE_SUM
from app.web.forms import CalculatorPageState, CombinedFieldData, CompareRowData, FormFeedback, SingleFormData, SumRowData
from app.web.presenter import ScalePresenter
from app.web_repository import ScaleEntryRecord, ScaleSummary
from app.web_service import CombinedEventResult, CombinedEventSpec


class WebRenderer:
    def __init__(self, presenter: ScalePresenter) -> None:
        self.presenter = presenter

    def render_message(self, title: str, message: str) -> str:
        return render_layout(title, f"<section class='page-head'><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p></section>")

    def render_not_found(self) -> str:
        return self.render_message("404", "Страница не найдена.")

    def render_home(self, scales: list[ScaleSummary]) -> str:
        grouped_cards = self.presenter.home_groups(scales)
        body_parts = [
            "<section class='hero'>"
            "<div class='hero-copy'>"
            "<h1>Очки World Athletics 2025</h1>"
            "<p>Полностью русская версия калькулятора очков по официальным таблицам World Athletics. Дисциплины собраны в спортивном порядке: от спринта к средним и длинным дистанциям, затем эстафеты, технические виды, шоссе и ходьба.</p>"
            "</div>"
            "<div class='hero-panel'>"
            "<div class='hero-note'>"
            "<strong>Быстрый старт</strong>"
            "<p>Выберите сценарий: рассчитать один результат, собрать сумму, сравнить наборы или посчитать многоборье по видам.</p>"
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
        ]
        for title in HOME_SECTION_ORDER:
            cards = grouped_cards.get(title, [])
            if cards:
                body_parts.append(self._render_home_group(title, cards))
        return render_layout("Очки World Athletics", "".join(body_parts))

    def render_scale(self, scale: ScaleSummary, entries: list[ScaleEntryRecord]) -> str:
        rows = "".join(
            "<tr>"
            f"<td>{entry.points}</td>"
            f"<td>{html.escape(entry.result_raw)}</td>"
            f"<td>{entry.result_value:.2f}</td>"
            "</tr>"
            for entry in entries[:120]
        )
        body = (
            "<section class='page-head scale-head'>"
            f"<h1>{html.escape(self.presenter.display_name(scale))} · {self.presenter.sex_label(scale.sex)}</h1>"
            f"<p>{html.escape(scale.section_ru)} · {html.escape(scale.discipline_code)} · очки {scale.min_points}–{scale.max_points}</p>"
            "<div class='tag-row'>"
            f"<span class='info-tag'>{html.escape(self.presenter.sex_label(scale.sex))}</span>"
            f"<span class='info-tag'>{html.escape(scale.section_ru)}</span>"
            "</div>"
            "<div class='hero-links'>"
            f"<a class='button secondary' href='/calculate?mode=single&scale_id={scale.scale_id}'>Рассчитать</a>"
            "</div>"
            "</section>"
            "<table><thead><tr><th>Очки</th><th>Результат</th><th>Значение</th></tr></thead><tbody>"
            f"{rows}"
            "</tbody></table>"
        )
        return render_layout(self.presenter.display_name(scale), body)

    def render_calculator(
        self,
        *,
        state: CalculatorPageState,
        all_scales: list[ScaleSummary],
        filtered_scales: list[ScaleSummary],
        choice_scales: list[ScaleSummary],
        selected_scale: ScaleSummary | None,
        active_combined: CombinedEventSpec,
        single_form: SingleFormData,
        sum_rows: list[SumRowData],
        compare_rows: list[CompareRowData],
        combined_fields: list[CombinedFieldData],
        result_block: str = "",
        feedback: FormFeedback | None = None,
    ) -> str:
        feedback = feedback or FormFeedback()
        labels = [self.presenter.scale_label(scale) for scale in choice_scales]
        body_parts = [
            "<section class='page-head calculator-head'>"
            "<h1>Калькулятор очков</h1>"
            "<p>Одиночный расчёт, сумма дисциплин, сравнение двух наборов и многоборье по видам в одном интерфейсе.</p>"
            "</section>",
            "<section class='page-head compact search-panel'>"
            "<h2>Поиск дисциплин</h2>"
            "<form method='get' class='stack-form compact-form'>"
            f"<input type='hidden' name='mode' value='{html.escape(state.mode)}'>"
            f"<label>Фильтр<input type='search' name='search' value='{html.escape(state.search_query)}' placeholder='Например: 100, высота, копьё, mixed'></label>"
            "<button class='button secondary' type='submit'>Отфильтровать</button>"
            "</form>"
            f"<p class='meta'>Сейчас доступно {len(filtered_scales)} шкал из {len(all_scales)}. Варианты в помещении выбираются внутри форм.</p>"
            "</section>",
            "<section class='calc-switches switch-panel'>"
            f"{self._mode_link(MODE_SINGLE, state, 'Одиночный расчёт')}"
            f"{self._mode_link(MODE_SUM, state, 'Сумма дисциплин')}"
            f"{self._mode_link(MODE_COMPARE, state, 'Сравнение наборов')}"
            f"{self._mode_link(MODE_COMBINED, state, 'Многоборье')}"
            "</section>",
            render_form_alert(feedback.message),
        ]

        if state.mode == MODE_SINGLE:
            body_parts.append(self._render_single_form(state, labels, selected_scale, single_form, feedback))
        if state.mode == MODE_SUM:
            body_parts.append(self._render_sum_form(state, labels, sum_rows, feedback))
        if state.mode == MODE_COMPARE:
            body_parts.append(self._render_compare_form(state, labels, compare_rows, feedback))
        if state.mode == MODE_COMBINED:
            body_parts.append(self._render_combined_form(active_combined, combined_fields, feedback))
        if result_block:
            body_parts.append(result_block)
        return render_layout("Калькулятор", "".join(body_parts))

    def render_single_result(self, scale: ScaleSummary, parsed, match) -> str:
        distance = abs(match.result_value - parsed.adjusted_value)
        return (
            "<section class='result-card'>"
            "<h2>Результат расчёта</h2>"
            "<div class='score-hero'>"
            f"<div class='score-value'>{match.points}<small>очков</small></div>"
            "<div class='score-meta'>"
            f"<p><strong>Дисциплина:</strong> {html.escape(self.presenter.display_name(scale))} · {self.presenter.sex_label(scale.sex)}</p>"
            f"<p><strong>Ввод:</strong> {html.escape(parsed.raw_input)} → {html.escape(parsed.normalized_display)}</p>"
            f"<p><strong>Табличный результат:</strong> {html.escape(match.result_raw)}</p>"
            f"<p><strong>Отклонение:</strong> {distance:.2f} {'сек' if scale.unit == 'time' else ('м' if scale.unit == 'metric' else 'очков')}.</p>"
            f"<p><a href='/scale/{scale.scale_id}'>Открыть таблицу дисциплины</a></p>"
            "</div>"
            "</div>"
            "</section>"
        )

    def render_sum_result(self, total: int, rows_html: str) -> str:
        return (
            "<section class='result-card'>"
            "<h2>Сумма очков</h2>"
            f"<div class='score-value solo'>{total}<small>очков</small></div>"
            "<table><thead><tr><th>Дисциплина</th><th>Результат</th><th>Очки</th><th>Табличная строка</th></tr></thead><tbody>"
            f"{rows_html}"
            "</tbody></table>"
            "</section>"
        )

    def render_compare_result(self, left_total: int, right_total: int, winner: str, left_rows: str, right_rows: str) -> str:
        delta = abs(left_total - right_total)
        return (
            "<section class='result-card'>"
            "<h2>Сравнение наборов</h2>"
            "<div class='duel-summary'>"
            f"<div class='duel-pill'><span>Набор А</span><strong>{left_total}</strong><small>очков</small></div>"
            f"<div class='duel-pill'><span>Набор Б</span><strong>{right_total}</strong><small>очков</small></div>"
            f"<div class='duel-pill accent'><span>Разница</span><strong>{delta}</strong><small>{html.escape(winner)}</small></div>"
            "</div>"
            "<div class='compare-tables'>"
            "<div><h3>Набор А</h3><table><thead><tr><th>Дисциплина</th><th>Результат</th><th>Очки</th></tr></thead><tbody>"
            f"{left_rows}"
            "</tbody></table></div>"
            "<div><h3>Набор Б</h3><table><thead><tr><th>Дисциплина</th><th>Результат</th><th>Очки</th></tr></thead><tbody>"
            f"{right_rows}"
            "</tbody></table></div>"
            "</div>"
            "</section>"
        )

    def render_combined_result(self, result: CombinedEventResult) -> str:
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

    def _render_home_group(self, title: str, cards_data: list[dict[str, object]]) -> str:
        cards = []
        for item in cards_data:
            scale = item["scale"]
            tags = "".join(f"<span class='info-tag'>{html.escape(tag)}</span>" for tag in item["tags"])
            tags_html = f"<div class='tag-row'>{tags}</div>" if tags else ""
            cards.append(
                f"<article class='scale-card' data-search='{html.escape(item['search_blob'])}'>"
                f"<h2>{html.escape(self.presenter.display_name(scale))}</h2>"
                f"<p class='meta'>{html.escape(item['subtitle'])}</p>"
                f"{tags_html}"
                "<div class='hero-links'>"
                f"<a class='button secondary' href='/calculate?mode=single&scale_id={scale.scale_id}'>Рассчитать</a>"
                f"<a class='button secondary' href='/scale/{scale.scale_id}'>Открыть шкалу</a>"
                "</div>"
                "</article>"
            )
        return f"<section><h2>{html.escape(title)}</h2><div class='card-grid'>{''.join(cards)}</div></section>"

    def _render_single_form(self, state: CalculatorPageState, labels: list[str], selected_scale: ScaleSummary | None, form: SingleFormData, feedback: FormFeedback) -> str:
        placeholder = self._result_placeholder(selected_scale)
        unit_help = self._unit_help(selected_scale)
        indoor_help = ""
        if selected_scale and self.presenter.has_indoor_variant(selected_scale):
            checked = " checked" if form.indoor else ""
            indoor_help = f"<label class='inline-check'><input type='checkbox' name='single_indoor' value='1'{checked}>Считать вариант в помещении</label>"
        hand_help = ""
        if selected_scale and selected_scale.hand_time_adjustment > 0:
            checked = " checked" if form.hand_timing else ""
            hand_help = (
                f"<label class='inline-check'><input type='checkbox' name='hand_timing' value='1'{checked}>"
                f"Ручной хронометраж (+{selected_scale.hand_time_adjustment:.2f} сек по правилам WA)</label>"
            )
        return (
            "<section class='page-head'>"
            "<h2>Одиночный расчёт</h2>"
            "<p>Начните вводить дисциплину по-русски, по коду WA или по дистанции. Поле подсказывает варианты прямо при наборе.</p>"
            f"{render_datalist(labels, 'discipline-list-single')}"
            "<form method='post' class='stack-form'>"
            "<input type='hidden' name='mode' value='single'>"
            f"<input type='hidden' name='search' value='{html.escape(state.search_query)}'>"
            f"<input type='hidden' name='scale_id' value='{selected_scale.scale_id if selected_scale else ''}'>"
            "<label>Дисциплина"
            f"<input list='discipline-list-single' name='scale_ref' value='{html.escape(form.scale_ref)}' placeholder='Например: Женщины · Спринт и барьеры · 100 м · 100m' required>"
            f"{render_field_error(feedback.error_for('scale_ref'))}</label>"
            "<label>Результат"
            f"<input type='text' name='result' value='{html.escape(form.result)}' placeholder='{html.escape(placeholder)}' required>"
            f"{render_field_error(feedback.error_for('result'))}</label>"
            f"{unit_help}{indoor_help}{hand_help}"
            "<div class='hero-links'>"
            "<button class='button' type='submit'>Рассчитать очки</button>"
            "<a class='button secondary' href='/calculate?mode=single'>Сбросить форму</a>"
            "</div>"
            "</form>"
            "</section>"
        )

    def _render_sum_form(self, state: CalculatorPageState, labels: list[str], rows: list[SumRowData], feedback: FormFeedback) -> str:
        row_html = []
        for row in rows:
            indoor_checked = " checked" if row.indoor else ""
            hand_checked = " checked" if row.hand_timing else ""
            row_html.append(
                "<div class='calc-row'>"
                "<label>Дисциплина"
                f"<input list='discipline-list' name='sum_scale_{row.index}' value='{html.escape(row.scale_ref)}' placeholder='Начните вводить дисциплину'>"
                f"{render_field_error(feedback.error_for(f'sum_scale_{row.index}'))}</label>"
                "<label>Результат"
                f"<input type='text' name='sum_result_{row.index}' value='{html.escape(row.result)}' placeholder='Например: 10.43, 1:58.00, 8.12'>"
                f"{render_field_error(feedback.error_for(f'sum_result_{row.index}'))}</label>"
                "<div class='check-stack'>"
                f"<label class='inline-check compact-check'><input type='checkbox' name='sum_indoor_{row.index}' value='1'{indoor_checked}>В помещении</label>"
                f"<label class='inline-check compact-check'><input type='checkbox' name='sum_hand_{row.index}' value='1'{hand_checked}>Ручное время</label>"
                "</div>"
                "</div>"
            )
        return (
            "<section class='page-head'>"
            "<h2>Сумма дисциплин</h2>"
            "<p>Соберите набор дисциплин и получите общую сумму очков. Варианты в помещении и ручное время можно отметить отдельно по каждой строке.</p>"
            f"{render_datalist(labels, 'discipline-list')}"
            "<form method='post' class='stack-form'>"
            "<input type='hidden' name='mode' value='sum'>"
            f"<input type='hidden' name='search' value='{html.escape(state.search_query)}'>"
            f"<input type='hidden' name='row_count' value='{state.row_count}'>"
            f"{''.join(row_html)}"
            "<div class='hero-links'>"
            "<button class='button' type='submit'>Посчитать сумму</button>"
            f"<a class='button secondary' href='/calculate?mode=sum&row_count={min(state.row_count + 1, 8)}&search={html.escape(state.search_query)}'>Добавить дисциплину</a>"
            "<a class='button secondary' href='/calculate?mode=sum'>Сбросить форму</a>"
            "</div>"
            "</form>"
            "</section>"
        )

    def _render_compare_form(self, state: CalculatorPageState, labels: list[str], rows: list[CompareRowData], feedback: FormFeedback) -> str:
        rows_html = []
        for row in rows:
            rows_html.append(
                "<div class='compare-row'>"
                f"{self._render_compare_side('A', row.index, row.left, feedback)}"
                f"{self._render_compare_side('Б', row.index, row.right, feedback)}"
                "</div>"
            )
        return (
            "<section class='page-head'>"
            "<h2>Сравнение наборов</h2>"
            "<p>Сравните двух спортсменов, два состава или два набора дисциплин. Внизу будет сумма по каждому набору и разница.</p>"
            f"{render_datalist(labels, 'discipline-list')}"
            "<form method='post' class='stack-form'>"
            "<input type='hidden' name='mode' value='compare'>"
            f"<input type='hidden' name='search' value='{html.escape(state.search_query)}'>"
            f"<input type='hidden' name='compare_count' value='{state.compare_count}'>"
            f"{''.join(rows_html)}"
            "<div class='hero-links'>"
            "<button class='button' type='submit'>Сравнить наборы</button>"
            f"<a class='button secondary' href='/calculate?mode=compare&compare_count={min(state.compare_count + 1, 6)}&search={html.escape(state.search_query)}'>Добавить строку</a>"
            "<a class='button secondary' href='/calculate?mode=compare'>Сбросить форму</a>"
            "</div>"
            "</form>"
            "</section>"
        )

    def _render_combined_form(self, spec: CombinedEventSpec, fields: list[CombinedFieldData], feedback: FormFeedback) -> str:
        options = "".join(
            f"<option value='{html.escape(item.key)}'{' selected' if item.key == spec.key else ''}>{html.escape(item.title_ru)}</option>"
            for item in self.presenter.service.list_combined_events()
        )
        rows = []
        for field in fields:
            discipline = next(item for item in spec.disciplines if item.code == field.code)
            scale = self.presenter.service.find_scale(spec.sex, discipline.code)
            checked = " checked" if field.hand_timing else ""
            placeholder = self._result_placeholder(scale)
            hand_option = ""
            if scale and scale.hand_time_adjustment > 0:
                hand_option = (
                    f"<label class='inline-check compact-check'><input type='checkbox' name='combined_hand_{field.code}' value='1'{checked}>"
                    f"Ручное время (+{scale.hand_time_adjustment:.2f})</label>"
                )
            rows.append(
                "<div class='combined-row'>"
                f"<div><strong>{html.escape(discipline.label_ru)}</strong><p class='meta'>{html.escape(discipline.code)}</p></div>"
                "<label>Результат"
                f"<input type='text' name='combined_{field.code}' value='{html.escape(field.value)}' placeholder='{html.escape(placeholder)}'>"
                f"{render_field_error(feedback.error_for(f'combined_{field.code}'))}</label>"
                f"{hand_option or '<div></div>'}"
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
            "<p class='meta'>Если заполнены не все виды, будет показана промежуточная сумма. Итоговая шкала `Dec./Hept./Pent.` здесь не используется напрямую.</p>"
            f"{''.join(rows)}"
            "<div class='hero-links'>"
            "<button class='button' type='submit'>Посчитать многоборье</button>"
            "<a class='button secondary' href='/calculate?mode=combined'>Сбросить форму</a>"
            "</div>"
            "</form>"
            "</section>"
        )

    def _render_compare_side(self, label: str, index: int, side, feedback: FormFeedback) -> str:
        prefix = "cmp_a" if label == "A" else "cmp_b"
        indoor_checked = " checked" if side.indoor else ""
        hand_checked = " checked" if side.hand_timing else ""
        return (
            "<div class='compare-col'>"
            f"<label>Набор {label}: дисциплина"
            f"<input list='discipline-list' name='{prefix}_scale_{index}' value='{html.escape(side.scale_ref)}' placeholder='Дисциплина'>"
            f"{render_field_error(feedback.error_for(f'{prefix}_scale_{index}'))}</label>"
            f"<label>Набор {label}: результат"
            f"<input type='text' name='{prefix}_result_{index}' value='{html.escape(side.result)}' placeholder='Результат'>"
            f"{render_field_error(feedback.error_for(f'{prefix}_result_{index}'))}</label>"
            f"<label class='inline-check compact-check'><input type='checkbox' name='{prefix}_indoor_{index}' value='1'{indoor_checked}>В помещении</label>"
            f"<label class='inline-check compact-check'><input type='checkbox' name='{prefix}_hand_{index}' value='1'{hand_checked}>Ручное время</label>"
            "</div>"
        )

    def _mode_link(self, mode: str, state: CalculatorPageState, label: str) -> str:
        params = [f"mode={mode}"]
        if state.search_query:
            params.append(f"search={html.escape(state.search_query)}")
        if mode == MODE_SUM:
            params.append(f"row_count={state.row_count}")
        if mode == MODE_COMPARE:
            params.append(f"compare_count={state.compare_count}")
        if mode == MODE_COMBINED:
            params.append(f"combined_key={html.escape(state.combined_key)}")
        css = "button active" if state.mode == mode else "button secondary"
        return f"<a class='{css}' href='/calculate?{'&'.join(params)}'>{label}</a>"

    def _result_placeholder(self, scale: ScaleSummary | None) -> str:
        if scale is None:
            return "10.43"
        if scale.unit == "time":
            return "10.43"
        if scale.unit == "points":
            return "6200"
        return "8.42"

    def _unit_help(self, scale: ScaleSummary | None) -> str:
        if scale is None:
            return "<p class='meta'>Сначала выберите дисциплину. После этого форма покажет подсказки по формату результата и вариант в помещении, если он есть.</p>"
        if scale.unit == "points":
            return "<p class='meta'>Для итоговой шкалы многоборья вводится уже готовая сумма очков.</p>"
        if scale.unit == "time":
            return "<p class='meta'>Для беговых дисциплин можно вводить секунды, минуты и часы: `10.43`, `1:58.00`, `2:10:35.50`.</p>"
        return "<p class='meta'>Для технических дисциплин вводите результат в метрах, например `8.42` или `17.35`.</p>"
