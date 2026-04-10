from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import fitz


HEADER_Y_MIN = 24.0
HEADER_Y_MAX = 42.0
HEADER_TOKEN_TOLERANCE = 13.0
ROW_TOLERANCE = 3.5
DATA_CLUSTER_TOLERANCE = 12.0

RUS_SECTION_LABELS = {
    "sprints": "Спринт",
    "hurdles": "Барьеры",
    "relays": "Эстафеты",
    "middle": "Средние дистанции",
    "long": "Длинные дистанции",
    "road": "Шоссе",
    "walk_road": "Спортивная ходьба по шоссе",
    "walk_track": "Спортивная ходьба на дорожке",
    "field": "Прыжки, метания и многоборья",
}


@dataclass(frozen=True)
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2


def group_words_into_rows(words: list[Word], tolerance: float = ROW_TOLERANCE) -> list[list[Word]]:
    rows: list[list[Word]] = []
    current: list[Word] = []
    current_y: float | None = None
    for word in sorted(words, key=lambda item: (item.y0, item.x0)):
        if current_y is None or abs(word.y0 - current_y) <= tolerance:
            current.append(word)
            current_y = word.y0 if current_y is None else (current_y + word.y0) / 2
            continue
        rows.append(sorted(current, key=lambda item: item.x0))
        current = [word]
        current_y = word.y0
    if current:
        rows.append(sorted(current, key=lambda item: item.x0))
    return rows


def classify_section(title: str) -> tuple[str, str]:
    upper = title.upper()
    if "SPRINTS" in upper:
        return "sprints", RUS_SECTION_LABELS["sprints"]
    if "HURDLES" in upper:
        return "hurdles", RUS_SECTION_LABELS["hurdles"]
    if "RELAYS" in upper:
        return "relays", RUS_SECTION_LABELS["relays"]
    if "MIDDLE DISTANCES" in upper:
        return "middle", RUS_SECTION_LABELS["middle"]
    if "LONG DISTANCES" in upper:
        return "long", RUS_SECTION_LABELS["long"]
    if "RACE WALKING ON ROAD" in upper:
        return "walk_road", RUS_SECTION_LABELS["walk_road"]
    if "RACE WALKING ON TRACK" in upper:
        return "walk_track", RUS_SECTION_LABELS["walk_track"]
    if "ROAD RUNNING" in upper:
        return "road", RUS_SECTION_LABELS["road"]
    if "JUMPS, THROWS AND COMBINED EVENTS" in upper:
        return "field", RUS_SECTION_LABELS["field"]
    return "other", title.strip().title()


def infer_event_kind(code: str, section_key: str) -> tuple[str, str]:
    if code in {"HJ", "PV", "LJ", "TJ", "SP", "DT", "HT", "JT"}:
        return "higher", "metric"
    if code in {"Pent. sh", "Hept. sh", "Hept.", "Dec."}:
        return "higher", "points"
    return "lower", "time"


def hand_timing_adjustment(code: str) -> float:
    if code in {"50m", "55m", "60m", "100m", "200m", "50mH", "55mH", "60mH", "100mH", "110mH"}:
        return 0.24
    if code in {"300m", "400m", "400mH"}:
        return 0.14
    return 0.0


def parse_numeric_value(raw: str, unit: str) -> float:
    text = raw.strip()
    if unit == "time":
        parts = text.replace(",", "").split(":")
        if len(parts) == 1:
            return float(parts[0])
        total = 0.0
        for part in parts[:-1]:
            total = total * 60 + int(part)
        return total * 60 + float(parts[-1])
    if unit == "points":
        return float(int(text))
    return float(text)


def format_result_value(value: float, unit: str) -> str:
    if unit == "time":
        if value >= 3600:
            hours = int(value // 3600)
            rem = value - hours * 3600
            minutes = int(rem // 60)
            seconds = rem - minutes * 60
            return f"{hours}:{minutes:02d}:{seconds:05.2f}".rstrip("0").rstrip(".")
        if value >= 60:
            minutes = int(value // 60)
            seconds = value - minutes * 60
            return f"{minutes}:{seconds:05.2f}".rstrip("0").rstrip(".")
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if unit == "points":
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def merge_header_tokens(header_words: list[Word], centers: list[float]) -> list[str]:
    labels = {index: [] for index in range(len(centers))}
    for word in header_words:
        if word.text == "Points":
            continue
        index = min(range(len(centers)), key=lambda item: abs(centers[item] - word.center_x))
        labels[index].append(word)

    merged: list[str] = []
    for index in range(len(centers)):
        parts = [word.text for word in sorted(labels[index], key=lambda item: item.x0)]
        label = " ".join(parts).strip()
        label = re.sub(r"\s+", " ", label)
        merged.append(label)
    return merged


def cluster_centers(values: list[float], tolerance: float = DATA_CLUSTER_TOLERANCE) -> list[float]:
    if not values:
        return []
    clusters: list[list[float]] = [[values[0]]]
    for value in sorted(values):
        if abs(value - clusters[-1][-1]) <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [sum(cluster) / len(cluster) for cluster in clusters]


def parse_table_page(page: fitz.Page) -> dict | None:
    title = page.get_text("text").splitlines()[0].strip()
    upper_title = title.upper()
    sex = "female" if "WOMEN" in upper_title else "male" if "MEN" in upper_title else None
    if sex is None:
        return None

    words = [
        Word(x0=x0, y0=y0, x1=x1, y1=y1, text=str(text))
        for x0, y0, x1, y1, text, *_ in page.get_text("words")
    ]
    rows = group_words_into_rows(words)
    header_row = next(
        (
            row
            for row in rows
            if any(word.text == "Points" for word in row) and any(HEADER_Y_MIN <= word.y0 <= HEADER_Y_MAX for word in row)
        ),
        None,
    )
    if header_row is None:
        return None

    data_rows = []
    header_y = min(word.y0 for word in header_row)
    for row in rows:
        if min(word.y0 for word in row) <= header_y:
            continue
        first = row[0].text.strip()
        if first.isdigit():
            data_rows.append(row)
    if not data_rows:
        return None

    point_center = data_rows[0][0].center_x
    non_point_centers: list[float] = []
    for row in data_rows[:60]:
        for word in row[1:]:
            if word.center_x > point_center + 18:
                non_point_centers.append(word.center_x)
    centers = cluster_centers(non_point_centers)
    if not centers:
        return None

    header_words = [word for word in header_row if word.center_x > point_center + 18]
    event_codes = merge_header_tokens(header_words, centers)
    if not any(event_codes):
        return None

    section_key, section_ru = classify_section(title)
    events = []
    for code in event_codes:
        code = code.strip()
        if not code:
            continue
        event_sex = "mixed" if code.startswith("4x400mix") else sex
        better, unit = infer_event_kind(code, section_key)
        label_ru = code
        if code == "Mile" and section_key == "road":
            label_ru = "Миля (шоссе)"
        elif code == "Mile sh" and section_key == "road":
            label_ru = "Миля short track (шоссе)"
        elif code.endswith(" sh"):
            label_ru = f"{code} (short track)"
        events.append(
            {
                "sex": event_sex,
                "event_code": code,
                "event_label_ru": label_ru,
                "event_id": f"{event_sex}:{section_key}:{code}",
                "section_key": section_key,
                "section_ru": section_ru,
                "better": better,
                "unit": unit,
                "hand_time_adjustment": hand_timing_adjustment(code),
            }
        )

    entries_by_event = {event["event_code"]: [] for event in events}
    for row in data_rows:
        points = int(row[0].text)
        buckets = {index: [] for index in range(len(centers))}
        for word in row[1:]:
            if word.center_x <= point_center + 18:
                continue
            index = min(range(len(centers)), key=lambda item: abs(centers[item] - word.center_x))
            buckets[index].append(word)
        for index, event in enumerate(events):
            raw = " ".join(word.text for word in sorted(buckets[index], key=lambda item: item.x0)).strip()
            if not raw or raw == "-":
                continue
            entries_by_event[event["event_code"]].append(
                {
                    "points": points,
                    "raw": raw,
                    "value": parse_numeric_value(raw, event["unit"]),
                }
            )

    return {
        "sex": sex,
        "section_key": section_key,
        "section_ru": section_ru,
        "title": title,
        "events": events,
        "entries_by_event": entries_by_event,
    }


def build_tables(pdf_path: Path) -> dict:
    pdf = fitz.open(pdf_path)
    events: list[dict] = []
    event_map: dict[str, dict] = {}
    for page_number in range(len(pdf)):
        parsed = parse_table_page(pdf[page_number])
        if parsed is None:
            continue
        for event in parsed["events"]:
            payload = event_map.setdefault(
                event["event_id"],
                {
                    **event,
                    "entries": [],
                },
            )
            payload["entries"].extend(parsed["entries_by_event"].get(event["event_code"], []))

    for event in event_map.values():
        deduped: dict[int, dict] = {}
        for entry in sorted(event["entries"], key=lambda item: (-item["points"], item["value"])):
            deduped.setdefault(entry["points"], entry)
        event["entries"] = list(deduped.values())
        events.append(event)

    events.sort(key=lambda item: (item.get("sex", ""), item.get("section_ru", ""), item.get("event_label_ru", "")))
    return {
        "source": "World Athletics Scoring Tables of Athletics 2025 revised edition",
        "events": events,
    }


def load_or_build_tables(pdf_path: Path, cache_path: Path) -> dict:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    payload = build_tables(pdf_path)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
