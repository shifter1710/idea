from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.wa_parser import format_result_value, load_or_build_tables


PDF_FILENAME = "world_athletics_scoring_tables_2025.pdf"
CACHE_FILENAME = "world_athletics_scoring_2025.json"


@dataclass(frozen=True)
class ScaleSummary:
    scale_id: int
    event_id: str
    discipline_code: str
    discipline_name: str
    sex: str
    section_ru: str
    better: str
    unit: str
    hand_time_adjustment: float
    entry_count: int
    min_points: int
    max_points: int


@dataclass(frozen=True)
class ScaleEntryRecord:
    entry_id: int
    scale_id: int
    discipline_code: str
    discipline_name: str
    sex: str
    points: int
    result_raw: str
    result_value: float


@dataclass(frozen=True)
class CalculationMatch:
    scale_id: int
    discipline_code: str
    discipline_name: str
    sex: str
    points: int
    result_raw: str
    result_value: float
    match_kind: str


class ParsedScaleRepository:
    def __init__(self, base_dir: Path) -> None:
        payload = load_or_build_tables(base_dir / PDF_FILENAME, base_dir / CACHE_FILENAME)
        self._scales_by_id: dict[int, ScaleSummary] = {}
        self._entries_by_scale_id: dict[int, list[ScaleEntryRecord]] = {}
        self._scale_id_by_event_id: dict[str, int] = {}

        for scale_id, event in enumerate(payload["events"], start=1):
            entries = sorted(event["entries"], key=lambda item: -item["points"])
            if not entries:
                continue
            summary = ScaleSummary(
                scale_id=scale_id,
                event_id=event["event_id"],
                discipline_code=event["event_code"],
                discipline_name=event["event_label_ru"],
                sex=event["sex"],
                section_ru=event["section_ru"],
                better=event["better"],
                unit=event["unit"],
                hand_time_adjustment=float(event["hand_time_adjustment"]),
                entry_count=len(entries),
                min_points=min(item["points"] for item in entries),
                max_points=max(item["points"] for item in entries),
            )
            self._scale_id_by_event_id[event["event_id"]] = scale_id
            self._scales_by_id[scale_id] = summary
            self._entries_by_scale_id[scale_id] = [
                ScaleEntryRecord(
                    entry_id=scale_id * 10000 + index,
                    scale_id=scale_id,
                    discipline_code=summary.discipline_code,
                    discipline_name=summary.discipline_name,
                    sex=summary.sex,
                    points=int(item["points"]),
                    result_raw=str(item["raw"]),
                    result_value=float(item["value"]),
                )
                for index, item in enumerate(entries, start=1)
            ]

    def list_scales(self) -> list[ScaleSummary]:
        return sorted(
            self._scales_by_id.values(),
            key=lambda item: (item.sex, item.section_ru, item.discipline_name),
        )

    def get_scale_summary(self, scale_id: int) -> ScaleSummary | None:
        return self._scales_by_id.get(scale_id)

    def find_scale(self, sex: str, discipline_code: str) -> ScaleSummary | None:
        for scale in self.list_scales():
            if scale.sex == sex and scale.discipline_code == discipline_code:
                return scale
        return None

    def list_scale_entries(self, scale_id: int) -> list[ScaleEntryRecord]:
        return list(self._entries_by_scale_id.get(scale_id, []))

    def get_entry(self, entry_id: int) -> ScaleEntryRecord | None:
        scale_id = entry_id // 10000
        for entry in self._entries_by_scale_id.get(scale_id, []):
            if entry.entry_id == entry_id:
                return entry
        return None

    def find_score_for_result(self, scale_id: int, result_value: float) -> CalculationMatch | None:
        scale = self.get_scale_summary(scale_id)
        entries = self._entries_by_scale_id.get(scale_id, [])
        if scale is None or not entries:
            return None

        if scale.better == "lower":
            for entry in entries:
                if entry.result_value >= result_value:
                    return CalculationMatch(
                        scale_id=entry.scale_id,
                        discipline_code=entry.discipline_code,
                        discipline_name=entry.discipline_name,
                        sex=entry.sex,
                        points=entry.points,
                        result_raw=format_result_value(entry.result_value, scale.unit),
                        result_value=entry.result_value,
                        match_kind="table",
                    )
            entry = entries[-1]
        else:
            for entry in entries:
                if entry.result_value <= result_value:
                    return CalculationMatch(
                        scale_id=entry.scale_id,
                        discipline_code=entry.discipline_code,
                        discipline_name=entry.discipline_name,
                        sex=entry.sex,
                        points=entry.points,
                        result_raw=format_result_value(entry.result_value, scale.unit),
                        result_value=entry.result_value,
                        match_kind="table",
                    )
            entry = entries[-1]

        return CalculationMatch(
            scale_id=entry.scale_id,
            discipline_code=entry.discipline_code,
            discipline_name=entry.discipline_name,
            sex=entry.sex,
            points=entry.points,
            result_raw=format_result_value(entry.result_value, scale.unit),
            result_value=entry.result_value,
            match_kind="table",
        )
