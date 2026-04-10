from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import fitz


SCAN_PDF = "Polosin_A_Ushakov_A_-_Tablitsy_otsenki_rezultatov_v_lyogkoy_atletike_-_1986.pdf"
OCR_PDF = "Polosin_A_Ushakov_A_-_Tablitsy_otsenki_rezultatov_v_lyogkoy_atletike_-_1986 (1).pdf"
DEFAULT_OUTPUT = "athletics_points_text_parse_v2.sqlite"
PAGE_IMAGES_DIR = Path(__file__).resolve().parent / "pdf-pages"
BOOK_PAGE_OFFSET = 2


AUTO_SECTIONS = [
    {"sex": "male", "short_pages": range(8, 67, 2), "long_pages": range(9, 64, 2)},
    {"sex": "female", "short_pages": range(238, 297, 2), "long_pages": range(239, 298, 2)},
]


SHORT_COLUMNS = ["60", "100", "200", "400", "800", "points"]
LONG_COLUMNS = ["1000", "1500", "3000", "5000"]

SHORT_CENTERS = {"60": 51.0, "100": 89.0, "200": 131.0, "400": 177.0, "800": 227.0, "points": 289.0}
LONG_CENTERS = {"1000": 67.0, "1500": 132.0, "3000": 205.0, "5000": 281.0}


DISCIPLINES = [
    ("60", "Бег 60 м"),
    ("100", "Бег 100 м"),
    ("200", "Бег 200 м"),
    ("400", "Бег 400 м"),
    ("800", "Бег 800 м"),
    ("1000", "Бег 1000 м"),
    ("1500", "Бег 1500 м"),
    ("3000", "Бег 3000 м"),
    ("5000", "Бег 5000 м"),
]

DISCIPLINE_LIMITS = {
    "60": (5.5, 9.5),
    "100": (9.0, 16.0),
    "200": (18.0, 40.0),
    "400": (40.0, 90.0),
    "800": (85.0, 180.0),
    "1000": (105.0, 270.0),
    "1500": (170.0, 320.0),
    "3000": (420.0, 700.0),
    "5000": (780.0, 1400.0),
}

REPAIR_TOLERANCE = {
    "60": 0.08,
    "100": 0.12,
    "200": 0.18,
    "400": 0.25,
    "800": 0.40,
    "1000": 0.50,
    "1500": 0.70,
    "3000": 1.00,
    "5000": 1.50,
}


TOKEN_CLEANUPS = {
    "‘": "",
    "`": "",
    "'": "",
    '"': "",
    "‚": ",",
    "„": ",",
    ";": ",",
    ":": ".",
    "—": "-",
    "–": "-",
    "_": "-",
    "[": "",
    "]": "",
    "(": "",
    ")": "",
    "{": "",
    "}": "",
    "|": "",
}


@dataclass(frozen=True)
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str


@dataclass
class ParsedCell:
    raw: str
    normalized: str | None
    value: float | None
    anomaly: bool


@dataclass
class ParsedEntry:
    discipline_code: str
    sex: str
    source_page: int
    row_order: int
    points: int
    result_raw: str
    result_value: float
    parse_method: str
    parse_confidence: float
    anomaly_flag: int


class CpuThrottle:
    def __init__(self, target_fraction: float | None) -> None:
        self.target_fraction = target_fraction if target_fraction and 0 < target_fraction < 1 else None
        self._last_cpu = self._cpu_total()
        self._last_wall = time.monotonic()

    @staticmethod
    def _cpu_total() -> float:
        proc_times = os.times()
        return (
            proc_times.user
            + proc_times.system
            + proc_times.children_user
            + proc_times.children_system
        )

    def checkpoint(self) -> None:
        if self.target_fraction is None:
            return

        now_cpu = self._cpu_total()
        now_wall = time.monotonic()
        cpu_delta = now_cpu - self._last_cpu
        wall_delta = now_wall - self._last_wall
        self._last_cpu = now_cpu
        self._last_wall = now_wall

        if cpu_delta <= 0:
            return

        desired_wall = cpu_delta / self.target_fraction
        sleep_for = desired_wall - wall_delta
        if sleep_for > 0:
            time.sleep(sleep_for)
            self._last_wall = time.monotonic()


def group_words_into_rows(words: list[Word], tolerance: float = 3.5) -> list[list[Word]]:
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


def load_words(page: fitz.Page, *, ocr_fallback: bool = False) -> tuple[list[Word], str]:
    if ocr_fallback:
        raise RuntimeError("word-level OCR fallback is disabled; use line_ocr_fallback instead")
    else:
        raw_words = page.get_text("words")
        method = "text_layer"

    words = [
        Word(x0=x0, y0=y0, x1=x1, y1=y1, text=str(text))
        for x0, y0, x1, y1, text, *_ in raw_words
        if 68 <= y0 <= 528
    ]
    return words, method


def assign_cells(row: list[Word], centers: dict[str, float], max_distance: float) -> dict[str, str]:
    columns = {name: [] for name in centers}
    for word in row:
        center_x = (word.x0 + word.x1) / 2
        best_name = min(centers, key=lambda name: abs(center_x - centers[name]))
        if abs(center_x - centers[best_name]) <= max_distance:
            columns[best_name].append(word.text)

    return {
        name: " ".join(tokens).strip()
        for name, tokens in columns.items()
    }


def clean_token(token: str) -> str:
    value = token.strip()
    for old, new in TOKEN_CLEANUPS.items():
        value = value.replace(old, new)
    value = re.sub(r"\s+", "", value)
    value = value.replace("O", "0").replace("o", "0")
    value = value.replace("l", "1").replace("I", "1")
    value = value.replace("°", ".")
    value = value.replace("..", ".")
    value = value.replace(",,", ",")
    value = value.strip(".")
    value = value.strip("-")
    return value


def normalize_time_token(token: str) -> ParsedCell:
    raw = token.strip()
    cleaned = clean_token(raw)
    if not cleaned:
        return ParsedCell(raw=raw, normalized=None, value=None, anomaly=False)

    if cleaned in {"-", ".", ","}:
        return ParsedCell(raw=raw, normalized=None, value=None, anomaly=False)

    if not re.search(r"\d", cleaned):
        return ParsedCell(raw=raw, normalized=None, value=None, anomaly=True)

    cleaned = cleaned.replace(",", ",")
    if "," not in cleaned:
        match = re.fullmatch(r"(\d+)\.(\d{2})", cleaned)
        if match:
            cleaned = f"{match.group(1)},{match.group(2)}"
        else:
            return ParsedCell(raw=raw, normalized=None, value=None, anomaly=True)

    whole, frac = cleaned.rsplit(",", 1)
    frac = re.sub(r"\D", "", frac)
    whole = re.sub(r"[^0-9.]", "", whole)
    if not whole or not frac:
        return ParsedCell(raw=raw, normalized=None, value=None, anomaly=True)

    if len(frac) == 1:
        frac = f"{frac}0"
    elif len(frac) > 2:
        frac = frac[:2]

    whole_parts = [part for part in whole.split(".") if part]
    if not whole_parts:
        return ParsedCell(raw=raw, normalized=None, value=None, anomaly=True)

    try:
        if len(whole_parts) == 1:
            seconds = float(f"{whole_parts[0]}.{frac}")
            normalized = f"{int(whole_parts[0])},{frac}"
        else:
            if any(int(part) >= 60 for part in whole_parts[1:]):
                return ParsedCell(raw=raw, normalized=None, value=None, anomaly=True)
            seconds = 0.0
            for part in whole_parts[:-1]:
                seconds = seconds * 60 + int(part)
            seconds = seconds * 60 + int(whole_parts[-1]) + int(frac) / 100
            normalized = f"{'.'.join(str(int(part)) for part in whole_parts)},{frac}"
    except ValueError:
        return ParsedCell(raw=raw, normalized=None, value=None, anomaly=True)

    return ParsedCell(raw=raw, normalized=normalized, value=seconds, anomaly=False)


def is_plausible_result(discipline_code: str, value: float | None) -> bool:
    if value is None:
        return False
    minimum, maximum = DISCIPLINE_LIMITS[discipline_code]
    return minimum <= value <= maximum


def format_result_value(discipline_code: str, value: float) -> str:
    hundredths = int(round(value * 100))
    total_seconds, frac = divmod(hundredths, 100)

    if discipline_code in {"800", "1000", "1500", "3000", "5000"}:
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}.{seconds:02d},{frac:02d}"

    return f"{total_seconds},{frac:02d}"


def parse_discipline_token(token: str, discipline_code: str) -> ParsedCell:
    parsed = normalize_time_token(token)
    if is_plausible_result(discipline_code, parsed.value):
        return ParsedCell(
            raw=parsed.raw,
            normalized=parsed.normalized,
            value=parsed.value,
            anomaly=parsed.anomaly,
        )

    cleaned = clean_token(token)
    whole_part = cleaned.rsplit(",", 1)[0] if "," in cleaned else cleaned
    whole_parts = [part for part in whole_part.split(".") if part]
    has_invalid_mmss = len(whole_parts) > 1 and any(part.isdigit() and int(part) >= 60 for part in whole_parts[1:])

    if has_invalid_mmss:
        return ParsedCell(
            raw=token.strip(),
            normalized=None,
            value=None,
            anomaly=True,
        )

    candidates = generate_repair_candidates(token, discipline_code)
    if candidates:
        if parsed.value is not None:
            higher_candidates = [candidate for candidate in candidates if candidate.value >= parsed.value]
            if higher_candidates:
                best = min(higher_candidates, key=lambda candidate: candidate.value)
            else:
                best = min(candidates, key=lambda candidate: candidate.value)
        else:
            best = min(candidates, key=lambda candidate: candidate.value)

        return ParsedCell(
            raw=token.strip(),
            normalized=format_result_value(discipline_code, best.value),
            value=best.value,
            anomaly=False,
        )

    return ParsedCell(
        raw=parsed.raw,
        normalized=parsed.normalized,
        value=parsed.value,
        anomaly=True if parsed.value is not None else parsed.anomaly,
    )


def build_time_candidate(raw: str, value: float) -> ParsedCell:
    return ParsedCell(
        raw=raw,
        normalized=None,
        value=value,
        anomaly=False,
    )


def generate_repair_candidates(token: str, discipline_code: str) -> list[ParsedCell]:
    raw = token.strip()
    cleaned = clean_token(raw)
    candidates: list[ParsedCell] = []
    seen_values: set[int] = set()

    def add_candidate(value: float | None) -> None:
        if value is None or not is_plausible_result(discipline_code, value):
            return
        key = int(round(value * 100))
        if key in seen_values:
            return
        seen_values.add(key)
        candidates.append(build_time_candidate(raw, value))

    parsed = normalize_time_token(raw)
    add_candidate(parsed.value)

    if parsed.value is not None:
        if discipline_code in {"60", "100", "200", "400"}:
            for shift in (10.0, 20.0, 30.0, 40.0, 50.0, 60.0):
                add_candidate(parsed.value + shift)
        else:
            for shift in (60.0, 120.0, 180.0, 240.0, 300.0):
                add_candidate(parsed.value + shift)

    match = re.fullmatch(r"(\d{1,3}),(\d{2})", cleaned)
    if match and discipline_code in {"800", "1000", "1500", "3000", "5000"}:
        whole = match.group(1)
        frac = match.group(2)

        if len(whole) <= 2:
            add_candidate(int(whole) * 60 + int(frac))

        digits = whole + frac
        if len(digits) == 5:
            add_candidate(int(digits[0]) * 60 + int(digits[1:3]) + int(digits[3:5]) / 100)
        if len(digits) == 4:
            add_candidate(int(digits[0]) * 60 + int(digits[1:3]) + int(digits[3]) / 10)

    compact_digits = "".join(ch for ch in cleaned if ch.isdigit())
    if discipline_code in {"800", "1000", "1500", "3000", "5000"}:
        for minute_digits in (1, 2):
            if len(compact_digits) == minute_digits + 2:
                add_candidate(int(compact_digits[:minute_digits]) * 60 + int(compact_digits[minute_digits:minute_digits + 2]))
            if len(compact_digits) == minute_digits + 4:
                add_candidate(
                    int(compact_digits[:minute_digits]) * 60
                    + int(compact_digits[minute_digits:minute_digits + 2])
                    + int(compact_digits[minute_digits + 2:minute_digits + 4]) / 100
                )

    return candidates


def build_repair_anchors(entries: list[ParsedEntry]) -> list[ParsedEntry]:
    if not entries:
        return []

    discipline_code = entries[0].discipline_code
    tolerance = REPAIR_TOLERANCE[discipline_code]
    anchors: list[ParsedEntry] = []

    for entry in sorted(entries, key=lambda item: (-item.points, item.result_value, item.source_page, item.row_order)):
        if not is_plausible_result(discipline_code, entry.result_value):
            continue
        if entry.anomaly_flag:
            continue
        if anchors and entry.result_value + tolerance < anchors[-1].result_value:
            continue
        anchors.append(entry)

    return anchors


def interpolate_anchor_value(anchors: list[ParsedEntry], points: int) -> float | None:
    if len(anchors) < 2:
        return None

    ordered = sorted(anchors, key=lambda item: -item.points)
    if points >= ordered[0].points:
        return round(ordered[0].result_value, 2)
    elif points <= ordered[-1].points:
        return round(ordered[-1].result_value, 2)
    else:
        high = ordered[0]
        low = ordered[-1]
        for left, right in zip(ordered, ordered[1:]):
            if left.points >= points >= right.points:
                high = left
                low = right
                break

    if high.points == low.points:
        return round((high.result_value + low.result_value) / 2, 2)

    span = high.points - low.points
    weight = (high.points - points) / span
    interpolated = high.result_value + (low.result_value - high.result_value) * weight
    return round(interpolated, 2)


def repair_group_entries(entries: list[ParsedEntry]) -> list[ParsedEntry]:
    if not entries:
        return entries

    discipline_code = entries[0].discipline_code
    tolerance = REPAIR_TOLERANCE[discipline_code]
    anchors = build_repair_anchors(entries)
    if len(anchors) < 2:
        return entries

    repaired: list[ParsedEntry] = []
    for entry in sorted(entries, key=lambda item: (-item.points, item.result_value, item.source_page, item.row_order)):
        expected_value = interpolate_anchor_value(anchors, entry.points)
        if expected_value is None:
            repaired.append(entry)
            continue

        needs_repair = entry.anomaly_flag or not is_plausible_result(discipline_code, entry.result_value)
        if not needs_repair:
            repaired.append(entry)
            continue

        candidates = generate_repair_candidates(entry.result_raw, discipline_code)
        best_candidate = min(
            candidates,
            key=lambda candidate: abs(candidate.value - expected_value),
            default=None,
        )

        if best_candidate is not None and abs(best_candidate.value - expected_value) <= max(tolerance * 3, 0.25):
            value = round(best_candidate.value, 2)
            method = f"{entry.parse_method}+heuristic_repair"
            confidence = min(0.88, entry.parse_confidence + 0.03)
        elif is_plausible_result(discipline_code, expected_value):
            value = expected_value
            method = f"{entry.parse_method}+interpolated_repair"
            confidence = min(entry.parse_confidence, 0.6)
        else:
            repaired.append(entry)
            continue

        repaired.append(
            ParsedEntry(
                discipline_code=entry.discipline_code,
                sex=entry.sex,
                source_page=entry.source_page,
                row_order=entry.row_order,
                points=entry.points,
                result_raw=format_result_value(discipline_code, value),
                result_value=value,
                parse_method=method,
                parse_confidence=confidence,
                anomaly_flag=0,
            )
        )

    return repaired


def repair_entries(entries: list[ParsedEntry]) -> list[ParsedEntry]:
    grouped: dict[tuple[str, str], list[ParsedEntry]] = defaultdict(list)
    for entry in entries:
        grouped[(entry.sex, entry.discipline_code)].append(entry)

    repaired: list[ParsedEntry] = []
    for items in grouped.values():
        repaired.extend(repair_group_entries(items))
    return repaired


def parse_points(token: str) -> tuple[int | None, bool]:
    cleaned = clean_token(token)
    if not cleaned:
        return None, False
    digits = re.sub(r"\D", "", cleaned)
    if not digits:
        return None, False
    value = int(digits)
    anomaly = len(digits) < 3 or value < 500 or value > 2000
    return value, anomaly


def quality_score(rows: list[dict[str, str]], columns: list[str]) -> tuple[int, int]:
    valid_rows = 0
    value_count = 0
    for row in rows:
        parsed_count = 0
        for column in columns:
            cell = normalize_time_token(row.get(column, ""))
            if cell.value is not None:
                parsed_count += 1
        if parsed_count >= 2:
            valid_rows += 1
        value_count += parsed_count
    return valid_rows, value_count


def count_candidate_rows(rows: list[dict[str, str]], columns: list[str], min_parsed: int) -> int:
    total = 0
    for row in rows:
        parsed_count = sum(
            1
            for column in columns
            if normalize_time_token(row.get(column, "")).value is not None
        )
        if parsed_count >= min_parsed:
            total += 1
    return total


def parse_table_page(
    page: fitz.Page,
    *,
    columns: list[str],
    centers: dict[str, float],
    max_distance: float,
    allow_ocr_fallback: bool,
) -> tuple[list[dict[str, str]], str, bool]:
    words, method = load_words(page, ocr_fallback=False)
    rows = group_words_into_rows(words)
    parsed_rows = [assign_cells(row, centers, max_distance=max_distance) for row in rows]
    valid_rows, value_count = quality_score(parsed_rows, [column for column in columns if column != "points"])

    fallback_used = False
    if allow_ocr_fallback and (valid_rows < 35 or value_count < valid_rows * max(2, len(columns) - 1)):
        words, method = load_words(page, ocr_fallback=True)
        rows = group_words_into_rows(words)
        parsed_rows = [assign_cells(row, centers, max_distance=max_distance) for row in rows]
        fallback_used = True

    return parsed_rows, method, fallback_used


def page_image_path(page_number: int) -> Path:
    return PAGE_IMAGES_DIR / f"page-{page_number:03d}.png"


def book_page_number(pdf_page_number: int) -> int:
    return pdf_page_number - BOOK_PAGE_OFFSET


def render_page_for_tesseract(page: fitz.Page, dpi: int = 120, clip: fitz.Rect | None = None) -> Path:
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=matrix, alpha=False, colorspace=fitz.csGRAY, clip=clip)
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    path = Path(handle.name)
    handle.close()
    pix.save(path)
    return path


def run_tesseract(image_path: Path) -> tuple[str, str]:
    try:
        try:
            env = os.environ.copy()
            env.setdefault("OMP_THREAD_LIMIT", "1")
            env.setdefault("OMP_NUM_THREADS", "1")
            completed = subprocess.run(
                ["tesseract", str(image_path), "stdout", "--psm", "6"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=True,
                timeout=30,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return "", "line_ocr_timeout"
    except subprocess.CalledProcessError:
        return "", "line_ocr_failed"

    return completed.stdout, "line_ocr_fallback"


def extract_long_rows_from_ocr_text(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not re.search(r"\d", line):
            continue
        normalized = line.replace("|", "1").replace("!", "1").replace("i", "1")
        normalized = re.sub(r"(?<=[.,:;])\s+(?=\d)", "", normalized)
        normalized = re.sub(r"(?<=\d)\s+(?=[.,:;])", "", normalized)
        matches = re.findall(r"[\dOIl]+(?:[.,:;][\dOIl]+)+(?:[.,:;][\dOIl]+)?", normalized)
        if len(matches) < 3:
            continue
        if len(matches) > 4:
            matches = matches[-4:]
        row = {column: "" for column in LONG_COLUMNS}
        for column, token in zip(LONG_COLUMNS, matches):
            row[column] = token
        rows.append(row)
    return rows


def parse_long_page_with_tesseract(page: fitz.Page, page_number: int) -> tuple[list[dict[str, str]], str]:
    png_path = page_image_path(book_page_number(page_number))
    if png_path.exists():
        text, method = run_tesseract(png_path)
        if text:
            return extract_long_rows_from_ocr_text(text), "image_ocr_fallback"

    clip = fitz.Rect(40, 50, 312, 530)
    image_path = render_page_for_tesseract(page, clip=clip)
    try:
        text, method = run_tesseract(image_path)
        return extract_long_rows_from_ocr_text(text), method
    finally:
        image_path.unlink(missing_ok=True)


def collect_short_page_points(page_rows: list[dict[str, str]]) -> list[tuple[int, int]]:
    rows_with_points: list[tuple[int, int]] = []
    for row_order, row in enumerate(page_rows, start=1):
        points, bad_points = parse_points(row.get("points", ""))
        if points is None or bad_points:
            continue
        rows_with_points.append((row_order, points))
    return rows_with_points


def build_short_entries(
    *,
    sex: str,
    page_number: int,
    page_rows: list[dict[str, str]],
    method: str,
) -> tuple[list[ParsedEntry], list[tuple[int, int]], int]:
    entries: list[ParsedEntry] = []
    anomaly_count = 0
    row_points = collect_short_page_points(page_rows)
    points_lookup = dict(row_points)

    for row_order, row in enumerate(page_rows, start=1):
        points = points_lookup.get(row_order)
        if points is None:
            continue

        for discipline_code in SHORT_COLUMNS[:-1]:
            parsed = parse_discipline_token(row.get(discipline_code, ""), discipline_code)
            if parsed.value is None:
                continue
            anomaly = int(parsed.anomaly)
            anomaly_count += anomaly
            entries.append(
                ParsedEntry(
                    discipline_code=discipline_code,
                    sex=sex,
                    source_page=book_page_number(page_number),
                    row_order=row_order,
                    points=points,
                    result_raw=parsed.normalized or parsed.raw,
                    result_value=parsed.value,
                    parse_method=method,
                    parse_confidence=0.95 if method == "text_layer" else 0.75,
                    anomaly_flag=anomaly,
                )
            )
    return entries, row_points, anomaly_count


def build_long_entries(
    *,
    sex: str,
    page_number: int,
    page_rows: list[dict[str, str]],
    method: str,
    inherited_points: list[tuple[int, int]],
) -> tuple[list[ParsedEntry], int, int]:
    entries: list[ParsedEntry] = []
    anomaly_count = 0

    candidate_rows: list[tuple[int, dict[str, str]]] = []
    for row_order, row in enumerate(page_rows, start=1):
        parsed_count = sum(
            1 for discipline_code in LONG_COLUMNS
            if normalize_time_token(row.get(discipline_code, "")).value is not None
        )
        if parsed_count >= 2:
            candidate_rows.append((row_order, row))

    mismatch_flag = int(len(candidate_rows) != len(inherited_points))
    if mismatch_flag:
        anomaly_count += 1

    pair_count = min(len(candidate_rows), len(inherited_points))
    for index in range(pair_count):
        row_order, row = candidate_rows[index]
        _, points = inherited_points[index]
        for discipline_code in LONG_COLUMNS:
            parsed = parse_discipline_token(row.get(discipline_code, ""), discipline_code)
            if parsed.value is None:
                continue
            anomaly = int(parsed.anomaly or mismatch_flag)
            anomaly_count += anomaly
            entries.append(
                ParsedEntry(
                    discipline_code=discipline_code,
                    sex=sex,
                    source_page=book_page_number(page_number),
                    row_order=row_order,
                    points=points,
                    result_raw=parsed.normalized or parsed.raw,
                    result_value=parsed.value,
                    parse_method=method,
                    parse_confidence=0.9 if method == "text_layer" else 0.72,
                    anomaly_flag=anomaly,
                )
            )

    return entries, anomaly_count, pair_count


def mark_monotonic_anomalies(entries: list[ParsedEntry]) -> list[ParsedEntry]:
    grouped: dict[tuple[str, str], list[ParsedEntry]] = defaultdict(list)
    for entry in entries:
        grouped[(entry.sex, entry.discipline_code)].append(entry)

    updated: list[ParsedEntry] = []
    for _, items in grouped.items():
        ordered = sorted(items, key=lambda item: (-item.points, item.result_value, item.source_page, item.row_order))
        previous_value: float | None = None
        for item in ordered:
            anomaly_flag = item.anomaly_flag
            if previous_value is not None and item.result_value < previous_value:
                anomaly_flag = 1
            previous_value = item.result_value
            updated.append(
                ParsedEntry(
                    discipline_code=item.discipline_code,
                    sex=item.sex,
                    source_page=item.source_page,
                    row_order=item.row_order,
                    points=item.points,
                    result_raw=item.result_raw,
                    result_value=item.result_value,
                    parse_method=item.parse_method,
                    parse_confidence=item.parse_confidence,
                    anomaly_flag=anomaly_flag,
                )
            )

    return updated


def unique_entries(entries: list[ParsedEntry]) -> list[ParsedEntry]:
    seen: dict[tuple[str, str, int], ParsedEntry] = {}
    for entry in sorted(entries, key=lambda item: (item.sex, item.discipline_code, -item.points, item.anomaly_flag)):
        key = (entry.sex, entry.discipline_code, entry.points)
        current = seen.get(key)
        if current is None or (entry.anomaly_flag, -entry.parse_confidence) < (current.anomaly_flag, -current.parse_confidence):
            seen[key] = entry
    return list(seen.values())


def setup_database(path: Path) -> sqlite3.Connection:
    if path.exists():
        path.unlink()

    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA journal_mode = WAL;

        CREATE TABLE sources (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT,
            year INTEGER,
            file_name TEXT,
            notes TEXT
        );

        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE disciplines (
            id INTEGER PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            name_ru TEXT NOT NULL,
            discipline_type TEXT NOT NULL,
            unit TEXT NOT NULL
        );

        CREATE TABLE scales (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL,
            discipline_id INTEGER NOT NULL,
            sex TEXT NOT NULL CHECK (sex IN ('male', 'female')),
            timing_type TEXT NOT NULL CHECK (timing_type IN ('auto', 'manual', 'none')),
            source_page_start INTEGER,
            source_page_end INTEGER,
            notes TEXT,
            UNIQUE(source_id, discipline_id, sex, timing_type)
        );

        CREATE TABLE scale_entries (
            id INTEGER PRIMARY KEY,
            scale_id INTEGER NOT NULL,
            row_order INTEGER,
            result_raw TEXT NOT NULL,
            result_value REAL NOT NULL,
            points INTEGER NOT NULL,
            source_page INTEGER,
            parse_method TEXT,
            parse_confidence REAL,
            verified INTEGER NOT NULL DEFAULT 0,
            anomaly_flag INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX idx_scale_entries_scale_points ON scale_entries(scale_id, points);
        CREATE INDEX idx_scale_entries_scale_result ON scale_entries(scale_id, result_value);
        """
    )
    return connection


def insert_entries(connection: sqlite3.Connection, entries: list[ParsedEntry]) -> None:
    connection.execute(
        """
        INSERT INTO sources (id, title, authors, year, file_name, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            "Таблицы оценки результатов в лёгкой атлетике",
            "А. С. Полосин; А. А. Ушаков",
            1986,
            SCAN_PDF,
            "Auto-timing run tables 60-5000 m parsed from scan + OCR layer with conservative anomaly flags",
        ),
    )

    for index, (code, name_ru) in enumerate(DISCIPLINES, start=1):
        connection.execute(
            """
            INSERT INTO disciplines (id, code, name_ru, discipline_type, unit)
            VALUES (?, ?, ?, 'run', 'seconds')
            """,
            (index, code, name_ru),
        )

    discipline_ids = {
        code: index
        for index, (code, _) in enumerate(DISCIPLINES, start=1)
    }

    scale_ids: dict[tuple[str, str], int] = {}
    scale_counter = 1
    for sex in ("male", "female"):
        for code, _ in DISCIPLINES:
            relevant = [entry for entry in entries if entry.sex == sex and entry.discipline_code == code]
            if not relevant:
                continue
            pages = sorted({entry.source_page for entry in relevant})
            connection.execute(
                """
                INSERT INTO scales (
                    id, source_id, discipline_id, sex, timing_type,
                    source_page_start, source_page_end, notes
                )
                VALUES (?, 1, ?, ?, 'auto', ?, ?, ?)
                """,
                (
                    scale_counter,
                    discipline_ids[code],
                    sex,
                    pages[0],
                    pages[-1],
                    "Parsed with monotonicity checks and anomaly flags",
                ),
            )
            scale_ids[(sex, code)] = scale_counter
            scale_counter += 1

    for entry in sorted(entries, key=lambda item: (item.sex, item.discipline_code, -item.points, item.source_page, item.row_order)):
        connection.execute(
            """
            INSERT INTO scale_entries (
                scale_id, row_order, result_raw, result_value, points,
                source_page, parse_method, parse_confidence, anomaly_flag
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scale_ids[(entry.sex, entry.discipline_code)],
                entry.row_order,
                entry.result_raw,
                entry.result_value,
                entry.points,
                entry.source_page,
                entry.parse_method,
                entry.parse_confidence,
                entry.anomaly_flag,
            ),
        )

    connection.executemany(
        "INSERT INTO metadata (key, value) VALUES (?, ?)",
        [
            ("coverage", "auto-timing run tables for men and women, 60-5000 m"),
            ("source_file_scan", SCAN_PDF),
            ("source_file_ocr", OCR_PDF),
            ("rows_parsed", str(len(entries))),
            ("anomaly_rows", str(sum(entry.anomaly_flag for entry in entries))),
        ],
    )
    connection.commit()


def parse_auto_sections(scan_pdf_path: Path, ocr_pdf_path: Path, cpu_limit: float | None = 0.68) -> tuple[list[ParsedEntry], dict[str, int]]:
    scan_pdf = fitz.open(scan_pdf_path)
    ocr_pdf = fitz.open(ocr_pdf_path)
    all_entries: list[ParsedEntry] = []
    stats = defaultdict(int)
    throttle = CpuThrottle(cpu_limit)

    for section in AUTO_SECTIONS:
        sex = section["sex"]
        inherited_points_by_page: dict[int, list[tuple[int, int]]] = {}

        for page_number in section["short_pages"]:
            page = ocr_pdf[page_number - 1]
            print(f"[{sex}] short page {page_number}", flush=True)
            rows, method, fallback_used = parse_table_page(
                page,
                columns=SHORT_COLUMNS,
                centers=SHORT_CENTERS,
                max_distance=26.0,
                allow_ocr_fallback=False,
            )
            entries, row_points, anomaly_count = build_short_entries(
                sex=sex,
                page_number=page_number,
                page_rows=rows,
                method=method,
            )
            inherited_points_by_page[page_number] = row_points
            all_entries.extend(entries)
            stats["short_pages"] += 1
            stats["short_rows"] += len(row_points)
            stats["anomaly_count"] += anomaly_count
            if fallback_used:
                stats["fallback_pages"] += 1
            throttle.checkpoint()

        for page_number in section["long_pages"]:
            page = ocr_pdf[page_number - 1]
            print(f"[{sex}] long page {page_number}", flush=True)
            rows, method, fallback_used = parse_table_page(
                page,
                columns=LONG_COLUMNS,
                centers=LONG_CENTERS,
                max_distance=29.0,
                allow_ocr_fallback=False,
            )
            candidate_rows = count_candidate_rows(rows, LONG_COLUMNS, min_parsed=2)
            if candidate_rows < 40:
                print(f"[{sex}] fallback OCR page {page_number}", flush=True)
                rows, method = parse_long_page_with_tesseract(scan_pdf[page_number - 1], page_number)
                fallback_used = True
                candidate_rows = count_candidate_rows(rows, LONG_COLUMNS, min_parsed=2)
            if fallback_used:
                stats["fallback_pages"] += 1
            throttle.checkpoint()
            inherited_points = inherited_points_by_page.get(page_number - 1, [])
            if not inherited_points:
                continue
            entries, anomaly_count, pair_count = build_long_entries(
                sex=sex,
                page_number=page_number,
                page_rows=rows,
                method=method,
                inherited_points=inherited_points,
            )
            all_entries.extend(entries)
            stats["long_pages"] += 1
            stats["long_rows"] += pair_count
            stats["anomaly_count"] += anomaly_count

    del scan_pdf
    del ocr_pdf

    deduped = unique_entries(all_entries)
    monotonic_checked = unique_entries(mark_monotonic_anomalies(deduped))
    repaired = unique_entries(mark_monotonic_anomalies(repair_entries(monotonic_checked)))
    stats["entries_before_dedup"] = len(all_entries)
    stats["entries_after_dedup"] = len(repaired)
    stats["anomaly_entries_after_checks"] = sum(entry.anomaly_flag for entry in repaired)
    return repaired, dict(stats)


def print_summary(entries: list[ParsedEntry], stats: dict[str, int]) -> None:
    by_scale: dict[tuple[str, str], list[ParsedEntry]] = defaultdict(list)
    for entry in entries:
        by_scale[(entry.sex, entry.discipline_code)].append(entry)

    print("Parsed auto sections 60-5000 m")
    for sex in ("male", "female"):
        print(sex)
        for code, _ in DISCIPLINES:
            rows = by_scale.get((sex, code), [])
            if not rows:
                continue
            anomalies = sum(item.anomaly_flag for item in rows)
            print(f"  {code:>5}: rows={len(rows):>4} anomalies={anomalies:>3} pages={min(item.source_page for item in rows)}-{max(item.source_page for item in rows)}")

    print("stats")
    for key in sorted(stats):
        print(f"  {key}: {stats[key]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse auto-timing run tables (60-5000 m) from the Polosin/Ushakov book.")
    parser.add_argument("--scan-pdf", default=SCAN_PDF)
    parser.add_argument("--ocr-pdf", default=OCR_PDF)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--cpu-limit", type=float, default=0.68, help="Target average CPU fraction for this process, e.g. 0.68")
    args = parser.parse_args()

    output_path = Path(args.output)
    entries, stats = parse_auto_sections(Path(args.scan_pdf), Path(args.ocr_pdf), cpu_limit=args.cpu_limit)
    connection = setup_database(output_path)
    insert_entries(connection, entries)
    print_summary(entries, stats)
    print(f"sqlite: {output_path}")


if __name__ == "__main__":
    main()
