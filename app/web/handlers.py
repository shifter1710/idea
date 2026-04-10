from __future__ import annotations

import html

from app.web.constants import MODE_COMBINED, MODE_COMPARE, MODE_SINGLE, MODE_SUM
from app.web.forms import (
    CalculatorPageState,
    CombinedFieldData,
    CompareRowData,
    FormFeedback,
    SingleFormData,
    SumRowData,
    build_combined_fields,
    build_compare_rows,
    build_page_state,
    build_single_form_data,
    build_sum_rows,
)
from app.web.presenter import ScalePresenter
from app.web.views import WebRenderer
from app.web_service import CombinedEventSpec, WebScoringService


class WebHandlers:
    def __init__(self, service: WebScoringService, presenter: ScalePresenter, renderer: WebRenderer) -> None:
        self.service = service
        self.presenter = presenter
        self.renderer = renderer

    def home(self) -> str:
        return self.renderer.render_home(self.service.list_scales())

    def scale(self, scale_id: int) -> str:
        scale = self.service.get_scale_summary(scale_id)
        if scale is None:
            raise LookupError("Дисциплина не найдена.")
        return self.renderer.render_scale(scale, self.service.list_scale_entries(scale_id))

    def calculator(self, query: dict[str, list[str]], form: dict[str, list[str]]) -> str:
        all_scales = self.service.list_scales()
        combined_specs = self.service.list_combined_events()
        state = build_page_state(query, form, combined_specs[0].key)
        active_combined = self._active_combined(state)
        selected_scale = self._selected_scale(state, form)
        filtered_scales = self.presenter.filter_scales(all_scales, state.search_query)
        choice_scales = self.presenter.preferred_scale_choices(all_scales)
        single_form = build_single_form_data(form or query, state)
        sum_rows = build_sum_rows(form or query, state.row_count)
        compare_rows = build_compare_rows(form or query, state.compare_count)
        combined_fields = build_combined_fields(form or query, [discipline.code for discipline in active_combined.disciplines])

        feedback = FormFeedback()
        result_block = ""
        if form:
            result_block, feedback = self._handle_submission(state, form)
            selected_scale = self._selected_scale(state, form)

        return self.renderer.render_calculator(
            state=state,
            all_scales=all_scales,
            filtered_scales=filtered_scales,
            choice_scales=choice_scales,
            selected_scale=selected_scale,
            active_combined=active_combined,
            single_form=single_form,
            sum_rows=sum_rows,
            compare_rows=compare_rows,
            combined_fields=combined_fields,
            result_block=result_block,
            feedback=feedback,
        )

    def _handle_submission(self, state: CalculatorPageState, form: dict[str, list[str]]) -> tuple[str, FormFeedback]:
        if state.mode == MODE_SINGLE:
            return self._submit_single(form)
        if state.mode == MODE_SUM:
            return self._submit_sum(form, state.row_count)
        if state.mode == MODE_COMPARE:
            return self._submit_compare(form, state.compare_count)
        if state.mode == MODE_COMBINED:
            return self._submit_combined(form, state.combined_key)
        return "", FormFeedback()

    def _submit_single(self, form: dict[str, list[str]]) -> tuple[str, FormFeedback]:
        data = build_single_form_data(form, build_page_state({}, form, self.service.list_combined_events()[0].key))
        field_errors: dict[str, str] = {}
        try:
            scale = self.presenter.resolve_scale_selection(data.scale_ref, data.indoor) if data.scale_ref else None
            if scale is None:
                field_errors["scale_ref"] = "Выберите дисциплину из списка или введите корректное название."
                raise ValueError("Проверьте выбранную дисциплину.")
            scale, parsed, match = self.service.calculate_points(scale.scale_id, data.result, use_hand_timing=data.hand_timing)
            return self.renderer.render_single_result(scale, parsed, match), FormFeedback()
        except LookupError as exc:
            field_errors.setdefault("scale_ref", str(exc))
            return "", FormFeedback(message="Не удалось выполнить расчёт.", field_errors=field_errors)
        except ValueError as exc:
            if "дисциплин" in str(exc).lower() or "дисциплина" in str(exc).lower():
                field_errors.setdefault("scale_ref", str(exc))
            else:
                field_errors.setdefault("result", str(exc))
            return "", FormFeedback(message="Проверьте введённые значения и повторите расчёт.", field_errors=field_errors)

    def _submit_sum(self, form: dict[str, list[str]], row_count: int) -> tuple[str, FormFeedback]:
        rows = build_sum_rows(form, row_count)
        field_errors: dict[str, str] = {}
        total = 0
        rendered_rows: list[str] = []
        used_rows = 0
        for row in rows:
            scale_ref = row.scale_ref.strip()
            result = row.result.strip()
            if not scale_ref and not result:
                continue
            if not scale_ref:
                field_errors[f"sum_scale_{row.index}"] = "Выберите дисциплину."
                continue
            if not result:
                field_errors[f"sum_result_{row.index}"] = "Введите результат."
                continue
            try:
                scale = self.presenter.resolve_scale_selection(scale_ref, row.indoor)
                if scale is None:
                    raise LookupError("Дисциплина не найдена.")
                scale_summary, parsed, match = self.service.calculate_points(scale.scale_id, result, use_hand_timing=row.hand_timing)
            except LookupError as exc:
                field_errors[f"sum_scale_{row.index}"] = str(exc)
                continue
            except ValueError as exc:
                field_errors[f"sum_result_{row.index}"] = str(exc)
                continue
            used_rows += 1
            total += match.points
            rendered_rows.append(
                "<tr>"
                f"<td>{html.escape(self.presenter.display_name(scale_summary))}</td>"
                f"<td>{html.escape(parsed.normalized_display)}</td>"
                f"<td>{match.points}</td>"
                f"<td>{html.escape(match.result_raw)}</td>"
                "</tr>"
            )
        if field_errors:
            return "", FormFeedback(message="Исправьте ошибки в строках формы.", field_errors=field_errors)
        if used_rows == 0:
            return "", FormFeedback(message="Для суммы нужно заполнить хотя бы одну дисциплину и результат.")
        return self.renderer.render_sum_result(total, "".join(rendered_rows)), FormFeedback()

    def _submit_compare(self, form: dict[str, list[str]], compare_count: int) -> tuple[str, FormFeedback]:
        rows = build_compare_rows(form, compare_count)
        field_errors: dict[str, str] = {}
        left_total = 0
        right_total = 0
        left_rows: list[str] = []
        right_rows: list[str] = []
        used_rows = 0
        for row in rows:
            left_points, left_used = self._append_compare_side(
                row.index, "cmp_a", row.left.scale_ref, row.left.result, row.left.indoor, row.left.hand_timing, left_rows, field_errors
            )
            right_points, right_used = self._append_compare_side(
                row.index, "cmp_b", row.right.scale_ref, row.right.result, row.right.indoor, row.right.hand_timing, right_rows, field_errors
            )
            left_total += left_points
            right_total += right_points
            used_rows += left_used + right_used
        if field_errors:
            return "", FormFeedback(message="Исправьте ошибки в форме сравнения.", field_errors=field_errors)
        if used_rows == 0:
            return "", FormFeedback(message="Для сравнения нужно заполнить хотя бы один результат.")
        winner = "Набор А впереди" if left_total > right_total else "Набор Б впереди" if right_total > left_total else "Ничья"
        left_html = "".join(left_rows) or "<tr><td colspan='3'>Нет строк</td></tr>"
        right_html = "".join(right_rows) or "<tr><td colspan='3'>Нет строк</td></tr>"
        return self.renderer.render_compare_result(left_total, right_total, winner, left_html, right_html), FormFeedback()

    def _append_compare_side(
        self,
        index: int,
        prefix: str,
        scale_ref: str,
        result: str,
        indoor: bool,
        hand_timing: bool,
        rendered_rows: list[str],
        field_errors: dict[str, str],
    ) -> tuple[int, int]:
        scale_ref = scale_ref.strip()
        result = result.strip()
        if not scale_ref and not result:
            return 0, 0
        if not scale_ref:
            field_errors[f"{prefix}_scale_{index}"] = "Выберите дисциплину."
            return 0, 0
        if not result:
            field_errors[f"{prefix}_result_{index}"] = "Введите результат."
            return 0, 0
        try:
            scale = self.presenter.resolve_scale_selection(scale_ref, indoor)
            if scale is None:
                raise LookupError("Дисциплина не найдена.")
            _, parsed, match = self.service.calculate_points(scale.scale_id, result, use_hand_timing=hand_timing)
        except LookupError as exc:
            field_errors[f"{prefix}_scale_{index}"] = str(exc)
            return 0, 0
        except ValueError as exc:
            field_errors[f"{prefix}_result_{index}"] = str(exc)
            return 0, 0
        rendered_rows.append(
            f"<tr><td>{html.escape(self.presenter.display_name(scale))}</td><td>{html.escape(parsed.normalized_display)}</td><td>{match.points}</td></tr>"
        )
        return match.points, 1

    def _submit_combined(self, form: dict[str, list[str]], combined_key: str) -> tuple[str, FormFeedback]:
        spec = self.service.get_combined_event(combined_key)
        fields = build_combined_fields(form, [discipline.code for discipline in spec.disciplines])
        field_errors: dict[str, str] = {}
        raw_results = {field.code: field.value for field in fields}
        hand_flags = {field.code: field.hand_timing for field in fields}
        try:
            result = self.service.calculate_combined_event(spec.key, raw_results, hand_flags)
            return self.renderer.render_combined_result(result), FormFeedback()
        except LookupError as exc:
            return "", FormFeedback(message=str(exc))
        except ValueError as exc:
            if "хотя бы один результат" in str(exc).lower():
                return "", FormFeedback(message=str(exc))
            for field in fields:
                if field.value.strip():
                    field_errors[f"combined_{field.code}"] = str(exc)
                    break
            return "", FormFeedback(message="Проверьте результаты по видам многоборья.", field_errors=field_errors)

    def _active_combined(self, state: CalculatorPageState) -> CombinedEventSpec:
        try:
            return self.service.get_combined_event(state.combined_key)
        except LookupError:
            return self.service.list_combined_events()[0]

    def _selected_scale(self, state: CalculatorPageState, form: dict[str, list[str]]) -> ScaleSummary | None:
        selected_scale = self.service.get_scale_summary(state.selected_scale_id) if state.selected_scale_id else None
        if selected_scale is None and state.selected_scale_ref:
            try:
                selected_scale = self.presenter.find_scale_by_label(state.selected_scale_ref)
            except LookupError:
                selected_scale = None
        if not state.single_indoor and selected_scale and self.presenter.is_indoor(selected_scale):
            return self.presenter.outdoor_partner(selected_scale)
        if state.selected_scale_ref:
            resolved = self.presenter.resolve_scale_selection(state.selected_scale_ref, state.single_indoor)
            if resolved is not None:
                return resolved
        return selected_scale
