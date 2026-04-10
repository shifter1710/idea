from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.repository import AthleticsRepository, Event


def normalize_result(raw_value: str) -> str:
    cleaned = raw_value.strip().replace(",", ".")
    if not cleaned:
        raise ValueError("Результат не должен быть пустым.")

    try:
        decimal_value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Результат должен быть числом.") from exc

    if decimal_value <= 0:
        raise ValueError("Результат должен быть больше нуля.")

    normalized = format(decimal_value.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


class ScoringService:
    def __init__(self, repository: AthleticsRepository) -> None:
        self.repository = repository

    def list_events(self) -> list[Event]:
        return self.repository.list_events()

    def calculate_points(self, event_id: int, raw_result: str) -> tuple[Event, str, int]:
        event = self.repository.get_event(event_id)
        if event is None:
            raise ValueError("Выбранная дисциплина не найдена.")

        result_key = normalize_result(raw_result)
        score_entry = self.repository.get_score(event_id, result_key)
        if score_entry is None:
            raise LookupError(
                "Для этой дисциплины и результата пока нет записи в базе данных."
            )

        return event, result_key, score_entry.points
