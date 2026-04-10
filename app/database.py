from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            unit TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS score_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            result_key TEXT NOT NULL,
            points INTEGER NOT NULL,
            UNIQUE(event_id, result_key),
            FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
        );
        """
    )
    connection.commit()


def seed_placeholder_events(connection: sqlite3.Connection) -> None:
    existing = connection.execute("SELECT COUNT(*) AS count FROM events").fetchone()
    if existing and existing["count"] > 0:
        return

    connection.executemany(
        """
        INSERT INTO events (code, name, unit)
        VALUES (?, ?, ?)
        """,
        [
            ("100m", "100 метров", "seconds"),
            ("200m", "200 метров", "seconds"),
            ("400m", "400 метров", "seconds"),
            ("800m", "800 метров", "minutes"),
            ("1500m", "1500 метров", "minutes"),
        ],
    )
    connection.commit()
