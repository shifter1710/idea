from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    id: int
    code: str
    name: str
    unit: str


@dataclass(frozen=True)
class ScoreEntry:
    event_id: int
    result_key: str
    points: int


class AthleticsRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def list_events(self) -> list[Event]:
        rows = self.connection.execute(
            "SELECT id, code, name, unit FROM events ORDER BY id"
        ).fetchall()
        return [Event(**dict(row)) for row in rows]

    def get_event(self, event_id: int) -> Event | None:
        row = self.connection.execute(
            "SELECT id, code, name, unit FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        return Event(**dict(row)) if row else None

    def get_score(self, event_id: int, result_key: str) -> ScoreEntry | None:
        row = self.connection.execute(
            """
            SELECT event_id, result_key, points
            FROM score_entries
            WHERE event_id = ? AND result_key = ?
            """,
            (event_id, result_key),
        ).fetchone()
        return ScoreEntry(**dict(row)) if row else None
