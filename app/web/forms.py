from __future__ import annotations

from dataclasses import dataclass, field

from app.web.constants import MODE_SINGLE, SUPPORTED_MODES


class InputData:
    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self.mapping = mapping

    def first(self, key: str, default: str = "") -> str:
        values = self.mapping.get(key)
        return values[0] if values else default

    def checked(self, key: str) -> bool:
        return self.first(key, "0") == "1"

    def bounded_int(self, key: str, default: int, min_value: int, max_value: int) -> int:
        raw = self.first(key, str(default))
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        return max(min_value, min(max_value, value))


@dataclass(frozen=True)
class CalculatorPageState:
    mode: str
    search_query: str
    row_count: int
    compare_count: int
    combined_key: str
    selected_scale_id: int | None
    selected_scale_ref: str
    single_indoor: bool


@dataclass(frozen=True)
class SingleFormData:
    scale_id: int | None
    scale_ref: str
    result: str
    hand_timing: bool
    indoor: bool


@dataclass(frozen=True)
class SumRowData:
    index: int
    scale_ref: str
    result: str
    hand_timing: bool
    indoor: bool


@dataclass(frozen=True)
class CompareSideData:
    scale_ref: str
    result: str
    hand_timing: bool
    indoor: bool


@dataclass(frozen=True)
class CompareRowData:
    index: int
    left: CompareSideData
    right: CompareSideData


@dataclass(frozen=True)
class CombinedFieldData:
    code: str
    value: str
    hand_timing: bool


@dataclass(frozen=True)
class FormFeedback:
    message: str | None = None
    field_errors: dict[str, str] = field(default_factory=dict)

    def error_for(self, field_name: str) -> str:
        return self.field_errors.get(field_name, "")


def build_page_state(query: dict[str, list[str]], form: dict[str, list[str]], default_combined_key: str) -> CalculatorPageState:
    source = InputData(form or query)
    mode = source.first("mode", MODE_SINGLE)
    if mode not in SUPPORTED_MODES:
        mode = MODE_SINGLE
    selected_scale_id = None
    raw_scale_id = source.first("scale_id")
    if raw_scale_id.isdigit():
        selected_scale_id = int(raw_scale_id)
    return CalculatorPageState(
        mode=mode,
        search_query=source.first("search").strip().lower(),
        row_count=source.bounded_int("row_count", default=4, min_value=2, max_value=8),
        compare_count=source.bounded_int("compare_count", default=3, min_value=1, max_value=6),
        combined_key=source.first("combined_key", default_combined_key),
        selected_scale_id=selected_scale_id,
        selected_scale_ref=source.first("scale_ref").strip(),
        single_indoor=source.checked("single_indoor"),
    )


def build_single_form_data(form: dict[str, list[str]], state: CalculatorPageState) -> SingleFormData:
    source = InputData(form)
    return SingleFormData(
        scale_id=state.selected_scale_id,
        scale_ref=source.first("scale_ref").strip(),
        result=source.first("result").strip(),
        hand_timing=source.checked("hand_timing"),
        indoor=source.checked("single_indoor"),
    )


def build_sum_rows(source_mapping: dict[str, list[str]], row_count: int) -> list[SumRowData]:
    source = InputData(source_mapping)
    return [
        SumRowData(
            index=index,
            scale_ref=source.first(f"sum_scale_{index}"),
            result=source.first(f"sum_result_{index}"),
            hand_timing=source.checked(f"sum_hand_{index}"),
            indoor=source.checked(f"sum_indoor_{index}"),
        )
        for index in range(row_count)
    ]


def build_compare_rows(source_mapping: dict[str, list[str]], compare_count: int) -> list[CompareRowData]:
    source = InputData(source_mapping)
    rows: list[CompareRowData] = []
    for index in range(compare_count):
        rows.append(
            CompareRowData(
                index=index,
                left=CompareSideData(
                    scale_ref=source.first(f"cmp_a_scale_{index}"),
                    result=source.first(f"cmp_a_result_{index}"),
                    hand_timing=source.checked(f"cmp_a_hand_{index}"),
                    indoor=source.checked(f"cmp_a_indoor_{index}"),
                ),
                right=CompareSideData(
                    scale_ref=source.first(f"cmp_b_scale_{index}"),
                    result=source.first(f"cmp_b_result_{index}"),
                    hand_timing=source.checked(f"cmp_b_hand_{index}"),
                    indoor=source.checked(f"cmp_b_indoor_{index}"),
                ),
            )
        )
    return rows


def build_combined_fields(source_mapping: dict[str, list[str]], codes: list[str]) -> list[CombinedFieldData]:
    source = InputData(source_mapping)
    return [
        CombinedFieldData(
            code=code,
            value=source.first(f"combined_{code}"),
            hand_timing=source.checked(f"combined_hand_{code}"),
        )
        for code in codes
    ]
