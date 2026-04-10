from __future__ import annotations

import csv
import sys
from pathlib import Path

from app.config import load_settings
from app.database import connect, initialize_database, seed_placeholder_events


def main(csv_path: str) -> None:
    source = Path(csv_path)
    if not source.exists():
        raise FileNotFoundError(f"CSV file not found: {source}")

    settings = load_settings()
    connection = connect(settings.database_path)
    initialize_database(connection)
    seed_placeholder_events(connection)

    rows_to_insert: list[tuple[int, str, int]] = []
    with source.open("r", encoding="utf-8", newline="") as file_handle:
        reader = csv.DictReader(file_handle)
        required_columns = {"event_id", "result_key", "points"}
        if not required_columns.issubset(reader.fieldnames or set()):
            raise ValueError(
                "CSV must contain columns: event_id,result_key,points"
            )

        for row in reader:
            rows_to_insert.append(
                (
                    int(row["event_id"]),
                    row["result_key"].strip(),
                    int(row["points"]),
                )
            )

    connection.executemany(
        """
        INSERT INTO score_entries (event_id, result_key, points)
        VALUES (?, ?, ?)
        ON CONFLICT(event_id, result_key) DO UPDATE SET points = excluded.points
        """,
        rows_to_insert,
    )
    connection.commit()

    print(f"Imported {len(rows_to_insert)} rows into {settings.database_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python import_scores.py data/score_entries.csv")
    main(sys.argv[1])
