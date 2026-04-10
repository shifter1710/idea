from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.wa_parser import format_result_value
from app.web_repository import CalculationMatch, ParsedScaleRepository, ScaleEntryRecord, ScaleSummary


@dataclass(frozen=True)
class ParsedUserResult:
    raw_input: str
    normalized_display: str
    value: float
    adjusted_value: float


@dataclass(frozen=True)
class CombinedEventDiscipline:
    code: str
    label_ru: str


@dataclass(frozen=True)
class CombinedEventSpec:
    key: str
    title_ru: str
    sex: str
    discipline_code: str
    is_short_track: bool
    disciplines: tuple[CombinedEventDiscipline, ...]


@dataclass(frozen=True)
class CombinedEventRow:
    discipline: CombinedEventDiscipline
    scale: ScaleSummary
    parsed: ParsedUserResult
    match: CalculationMatch
    use_hand_timing: bool


@dataclass(frozen=True)
class CombinedEventResult:
    spec: CombinedEventSpec
    rows: tuple[CombinedEventRow, ...]
    total_points: int
    completed_count: int
    total_count: int


class WebScoringService:
    COMBINED_EVENTS: tuple[CombinedEventSpec, ...] = (
        CombinedEventSpec(
            key="decathlon",
            title_ru="Десятиборье",
            sex="male",
            discipline_code="Dec.",
            is_short_track=False,
            disciplines=(
                CombinedEventDiscipline("100m", "100 м"),
                CombinedEventDiscipline("LJ", "Прыжок в длину"),
                CombinedEventDiscipline("SP", "Толкание ядра"),
                CombinedEventDiscipline("HJ", "Прыжок в высоту"),
                CombinedEventDiscipline("400m", "400 м"),
                CombinedEventDiscipline("110mH", "110 м с барьерами"),
                CombinedEventDiscipline("DT", "Метание диска"),
                CombinedEventDiscipline("PV", "Прыжок с шестом"),
                CombinedEventDiscipline("JT", "Метание копья"),
                CombinedEventDiscipline("1500m", "1500 м"),
            ),
        ),
        CombinedEventSpec(
            key="heptathlon_women",
            title_ru="Семиборье",
            sex="female",
            discipline_code="Hept.",
            is_short_track=False,
            disciplines=(
                CombinedEventDiscipline("100mH", "100 м с барьерами"),
                CombinedEventDiscipline("HJ", "Прыжок в высоту"),
                CombinedEventDiscipline("SP", "Толкание ядра"),
                CombinedEventDiscipline("200m", "200 м"),
                CombinedEventDiscipline("LJ", "Прыжок в длину"),
                CombinedEventDiscipline("JT", "Метание копья"),
                CombinedEventDiscipline("800m", "800 м"),
            ),
        ),
        CombinedEventSpec(
            key="heptathlon_short_track_men",
            title_ru="Семиборье (в помещении)",
            sex="male",
            discipline_code="Hept. sh",
            is_short_track=True,
            disciplines=(
                CombinedEventDiscipline("60m", "60 м"),
                CombinedEventDiscipline("LJ", "Прыжок в длину"),
                CombinedEventDiscipline("SP", "Толкание ядра"),
                CombinedEventDiscipline("HJ", "Прыжок в высоту"),
                CombinedEventDiscipline("60mH", "60 м с барьерами"),
                CombinedEventDiscipline("PV", "Прыжок с шестом"),
                CombinedEventDiscipline("1000m", "1000 м"),
            ),
        ),
        CombinedEventSpec(
            key="pentathlon_short_track_women",
            title_ru="Пятиборье (в помещении)",
            sex="female",
            discipline_code="Pent. sh",
            is_short_track=True,
            disciplines=(
                CombinedEventDiscipline("60mH", "60 м с барьерами"),
                CombinedEventDiscipline("HJ", "Прыжок в высоту"),
                CombinedEventDiscipline("SP", "Толкание ядра"),
                CombinedEventDiscipline("LJ", "Прыжок в длину"),
                CombinedEventDiscipline("800m", "800 м"),
            ),
        ),
    )

    def __init__(self, repository: ParsedScaleRepository) -> None:
        self.repository = repository

    def list_scales(self) -> list[ScaleSummary]:
        return self.repository.list_scales()

    def get_scale_summary(self, scale_id: int) -> ScaleSummary | None:
        return self.repository.get_scale_summary(scale_id)

    def list_scale_entries(self, scale_id: int) -> list[ScaleEntryRecord]:
        return self.repository.list_scale_entries(scale_id)

    def get_entry(self, entry_id: int) -> ScaleEntryRecord | None:
        return self.repository.get_entry(entry_id)

    def find_scale(self, sex: str, discipline_code: str) -> ScaleSummary | None:
        return self.repository.find_scale(sex, discipline_code)

    def list_combined_events(self) -> list[CombinedEventSpec]:
        return list(self.COMBINED_EVENTS)

    def get_combined_event(self, key: str) -> CombinedEventSpec:
        for spec in self.COMBINED_EVENTS:
            if spec.key == key:
                return spec
        raise LookupError("Многоборье не найдено.")

    def calculate_points(self, scale_id: int, raw_result: str, use_hand_timing: bool = False) -> tuple[ScaleSummary, ParsedUserResult, CalculationMatch]:
        scale = self.repository.get_scale_summary(scale_id)
        if scale is None:
            raise LookupError("Дисциплина не найдена.")

        parsed = self.parse_result(raw_result, scale.unit, scale.hand_time_adjustment if use_hand_timing else 0.0)
        match = self.repository.find_score_for_result(scale.scale_id, parsed.adjusted_value)
        if match is None:
            raise LookupError("Для этой дисциплины нет записей.")
        return scale, parsed, match

    def calculate_combined_event(
        self,
        key: str,
        raw_results: dict[str, str],
        hand_timing_flags: dict[str, bool],
    ) -> CombinedEventResult:
        spec = self.get_combined_event(key)
        rows: list[CombinedEventRow] = []
        total = 0
        for discipline in spec.disciplines:
            raw_result = raw_results.get(discipline.code, "").strip()
            if not raw_result:
                continue
            scale = self.find_scale(spec.sex, discipline.code)
            if scale is None:
                raise LookupError(f"Не найдена шкала для вида {discipline.label_ru}.")
            use_hand = hand_timing_flags.get(discipline.code, False)
            _, parsed, match = self.calculate_points(scale.scale_id, raw_result, use_hand_timing=use_hand)
            rows.append(
                CombinedEventRow(
                    discipline=discipline,
                    scale=scale,
                    parsed=parsed,
                    match=match,
                    use_hand_timing=use_hand,
                )
            )
            total += match.points
        if not rows:
            raise ValueError("Для многоборья нужно заполнить хотя бы один результат.")
        return CombinedEventResult(
            spec=spec,
            rows=tuple(rows),
            total_points=total,
            completed_count=len(rows),
            total_count=len(spec.disciplines),
        )

    def parse_result(self, raw_result: str, unit: str, hand_adjustment: float = 0.0) -> ParsedUserResult:
        cleaned = raw_result.strip().replace(" ", "")
        if not cleaned:
            raise ValueError("Результат не должен быть пустым.")

        if unit == "time":
            canonical = cleaned.replace(",", ".")
            if ":" in canonical:
                parts = canonical.split(":")
                if len(parts) not in {2, 3}:
                    raise ValueError("Используйте формат времени вроде `10.43`, `1:45.62` или `2:10:35.50`.")
                try:
                    tail = float(Decimal(parts[-1]))
                    integers = [int(part) for part in parts[:-1]]
                except (InvalidOperation, ValueError) as exc:
                    raise ValueError("Не удалось распознать время.") from exc
                total = tail
                for part in reversed(integers):
                    total += part * 60
            else:
                try:
                    total = float(Decimal(canonical))
                except InvalidOperation as exc:
                    raise ValueError("Не удалось распознать время.") from exc
            if total <= 0:
                raise ValueError("Результат должен быть больше нуля.")
            adjusted = round(total + hand_adjustment, 2)
            return ParsedUserResult(
                raw_input=raw_result,
                normalized_display=format_result_value(round(total, 2), unit),
                value=round(total, 2),
                adjusted_value=adjusted,
            )

        if unit == "points":
            digits = cleaned.replace(",", "").replace(".", "")
            if not digits.isdigit():
                raise ValueError("Для многоборий укажите целое число очков.")
            value = float(int(digits))
            return ParsedUserResult(
                raw_input=raw_result,
                normalized_display=str(int(value)),
                value=value,
                adjusted_value=value,
            )

        canonical = cleaned.replace(",", ".")
        try:
            value = float(Decimal(canonical))
        except InvalidOperation as exc:
            raise ValueError("Используйте число в метрах, например `8.42` или `17,35`.") from exc
        if value <= 0:
            raise ValueError("Результат должен быть больше нуля.")
        normalized = format_result_value(round(value, 2), unit)
        return ParsedUserResult(
            raw_input=raw_result,
            normalized_display=normalized,
            value=round(value, 2),
            adjusted_value=round(value, 2),
        )
