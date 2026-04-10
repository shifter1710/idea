from __future__ import annotations

import re
from collections import defaultdict

from app.web.constants import HOME_SECTION_ORDER, TECHNICAL_ORDER
from app.web_repository import ScaleSummary
from app.web_service import WebScoringService


class ScalePresenter:
    def __init__(self, service: WebScoringService) -> None:
        self.service = service

    def home_groups(self, scales: list[ScaleSummary]) -> dict[str, list[dict[str, object]]]:
        by_code: dict[str, list[ScaleSummary]] = defaultdict(list)
        for scale in scales:
            key = f"{self.home_section(scale)}:{self.base_discipline_code(scale.discipline_code)}"
            by_code[key].append(scale)

        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for items in by_code.values():
            ordered = sorted(items, key=lambda item: (self.is_indoor(item), item.sex != "male", item.sex, item.scale_id))
            base_scale = next((item for item in ordered if not self.is_indoor(item)), ordered[0])
            sexes = {item.sex for item in ordered}
            tags: list[str] = []
            if sexes == {"female"}:
                tags.append("женщины")
            elif sexes == {"male"}:
                tags.append("мужчины")
            elif sexes == {"mixed"}:
                tags.append("смешанные")
            if any(self.is_indoor(item) for item in ordered):
                tags.append("есть вариант в помещении")
            section = self.home_section(base_scale)
            grouped[section].append(
                {
                    "scale": base_scale,
                    "subtitle": self.home_subtitle(base_scale, sexes),
                    "tags": tags,
                    "search_blob": " ".join(self.search_blob(item) for item in ordered),
                }
            )
        for section, items in grouped.items():
            items.sort(key=lambda item: self.home_sort_key(item["scale"]))
        return {section: grouped.get(section, []) for section in HOME_SECTION_ORDER}

    def home_section(self, scale: ScaleSummary) -> str:
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

    def home_subtitle(self, scale: ScaleSummary, sexes: set[str]) -> str:
        subtitle = self.base_discipline_code(scale.discipline_code)
        if sexes == {"mixed"}:
            return f"Смешанная дисциплина · {subtitle}"
        if sexes == {"female"}:
            return f"Женщины · {subtitle}"
        if sexes == {"male"}:
            return f"{self.sex_label(scale.sex)} · {subtitle}"
        return subtitle

    def home_sort_key(self, scale: ScaleSummary) -> tuple[float, int, str]:
        section = self.home_section(scale)
        name = self.display_name(scale)
        code = scale.discipline_code
        if section == "Технические виды":
            return (TECHNICAL_ORDER.get(name, 999.0), 0, name)
        if section == "Эстафеты":
            relay_match = re.fullmatch(r"4x(\d+)(m|km)(mix)?", self.base_discipline_code(code))
            if relay_match:
                distance, unit, mixed = relay_match.groups()
                base = float(distance) * (1000 if unit == "km" else 1)
                return (base, 1 if mixed else 0, name)
        numeric = self.event_distance_value(code)
        hurdle = 1 if "H" in code else 0
        steeple = 2 if "SC" in code else 0
        walk = 3 if "W" in code else 0
        mixed = 1 if scale.sex == "mixed" else 0
        return (numeric, hurdle + steeple + walk + mixed, name)

    def event_distance_value(self, code: str) -> float:
        base = self.base_discipline_code(code)
        specials = {
            "Mile": 1609.34,
            "2 Miles": 3218.68,
            "10 Miles": 16093.4,
            "HM": 21097.5,
            "Half Marathon": 21097.5,
            "Marathon": 42195,
        }
        if base in specials:
            return specials[base]
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

    def preferred_scale_choices(self, scales: list[ScaleSummary]) -> list[ScaleSummary]:
        choices: list[ScaleSummary] = []
        seen: set[tuple[str, str, str]] = set()
        for scale in sorted(scales, key=lambda item: (item.sex, item.section_ru, item.scale_id)):
            key = (scale.sex, scale.section_ru, self.base_discipline_code(scale.discipline_code))
            if self.is_indoor(scale) and self.service.find_scale(scale.sex, self.base_discipline_code(scale.discipline_code)) is not None:
                continue
            if key in seen:
                continue
            seen.add(key)
            choices.append(scale)
        return choices

    def find_scale_by_label(self, label: str) -> ScaleSummary:
        wanted = label.strip().lower()
        for scale in self.preferred_scale_choices(self.service.list_scales()):
            variants = {
                self.scale_label(scale).lower(),
                self.display_name(scale).lower(),
                self.base_discipline_code(scale.discipline_code).lower(),
                f"{self.sex_label(scale.sex).lower()} {self.display_name(scale).lower()}",
                f"{self.sex_label(scale.sex).lower()} {self.base_discipline_code(scale.discipline_code).lower()}",
            }
            if wanted in variants:
                return scale
        raise LookupError(f"Дисциплина не найдена: {label}")

    def resolve_scale_selection(self, label: str, prefer_indoor: bool) -> ScaleSummary | None:
        scale = self.find_scale_by_label(label)
        if prefer_indoor:
            indoor = self.service.find_scale(scale.sex, f"{self.base_discipline_code(scale.discipline_code)} sh")
            if indoor is not None:
                return indoor
        return scale

    @staticmethod
    def base_discipline_code(code: str) -> str:
        return code.removesuffix(" sh")

    def is_indoor(self, scale: ScaleSummary) -> bool:
        return scale.discipline_code.endswith(" sh") or "short track" in scale.discipline_name.lower()

    def has_indoor_variant(self, scale: ScaleSummary) -> bool:
        base_code = self.base_discipline_code(scale.discipline_code)
        if self.is_indoor(scale):
            return self.service.find_scale(scale.sex, base_code) is not None
        return self.service.find_scale(scale.sex, f"{base_code} sh") is not None

    def outdoor_partner(self, scale: ScaleSummary | None) -> ScaleSummary | None:
        if scale is None or not self.is_indoor(scale):
            return scale
        return self.service.find_scale(scale.sex, self.base_discipline_code(scale.discipline_code)) or scale

    def filter_scales(self, scales: list[ScaleSummary], needle: str) -> list[ScaleSummary]:
        if not needle:
            return scales
        return [scale for scale in scales if needle in self.search_blob(scale)]

    def search_blob(self, scale: ScaleSummary) -> str:
        return " ".join(
            [
                self.sex_label(scale.sex).lower(),
                self.home_section(scale).lower(),
                self.display_name(scale).lower(),
                self.display_name(self.outdoor_partner(scale) or scale).lower(),
                scale.discipline_code.lower(),
                self.base_discipline_code(scale.discipline_code).lower(),
                self.discipline_alias_blob(scale).lower(),
            ]
        )

    def scale_label(self, scale: ScaleSummary) -> str:
        return f"{self.sex_label(scale.sex)} · {self.home_section(scale)} · {self.display_name(scale)} · {self.base_discipline_code(scale.discipline_code)}"

    def display_name(self, scale: ScaleSummary) -> str:
        return self.translate_discipline_name(scale.discipline_name)

    def discipline_alias_blob(self, scale: ScaleSummary) -> str:
        name = self.display_name(scale)
        aliases = [name, scale.discipline_code]
        if "м" in name:
            aliases.append(name.replace(" м", "м"))
        if "в помещении" in name:
            aliases.append(name.replace("в помещении", "indoor"))
        return " ".join(aliases)

    def sex_label(self, sex: str) -> str:
        if sex == "male":
            return "Мужчины"
        if sex == "female":
            return "Женщины"
        return "Смешанные"

    @staticmethod
    def translate_discipline_name(name: str) -> str:
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

        translated = {
            "Mile": "Миля",
            "2 Miles": "2 мили",
            "Hept.": "Семиборье",
            "Pent.": "Пятиборье",
            "4x400mix": "Смешанная эстафета 4×400 м",
        }.get(translated, translated)

        if translated.endswith(" SC"):
            distance = translated.removesuffix(" SC")
            if distance.endswith("m") and distance[:-1].replace(",", "").isdigit():
                distance = f"{distance[:-1]} м"
            translated = f"{distance} с препятствиями"

        relay_match = re.fullmatch(r"4x(\d+)(m|km)(mix)?", translated)
        if relay_match:
            distance, unit, mixed = relay_match.groups()
            label = f"Эстафета 4×{distance} {'м' if unit == 'm' else 'км'}"
            translated = f"Смешанная {label.lower()}" if mixed else label

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
