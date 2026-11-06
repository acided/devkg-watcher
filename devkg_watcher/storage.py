"""SQLite storage of vacancies already seen."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .parser import Vacancy

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vacancies (
    id          INTEGER PRIMARY KEY,
    url         TEXT NOT NULL,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    salary      TEXT NOT NULL,
    work_format TEXT NOT NULL,
    meta        TEXT NOT NULL,
    relevant    INTEGER NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: str | Path) -> None:
        self._conn = sqlite3.connect(path)
        self._conn.executescript(_SCHEMA)

    @classmethod
    def in_memory_copy(cls, path: str | Path) -> Storage:
        """Open an in-memory copy of an existing DB, so writes never touch the file."""
        storage = cls(":memory:")
        source = sqlite3.connect(path)
        try:
            source.backup(storage._conn)
        finally:
            source.close()
        return storage

    def close(self) -> None:
        self._conn.close()

    def is_empty(self) -> bool:
        return self._conn.execute("SELECT 1 FROM vacancies LIMIT 1").fetchone() is None

    def known_ids(self, ids: Iterable[int]) -> set[int]:
        ids = list(ids)
        if not ids:
            return set()
        placeholders = ",".join("?" * len(ids))
        rows = self._conn.execute(
            f"SELECT id FROM vacancies WHERE id IN ({placeholders})", ids
        ).fetchall()
        return {row[0] for row in rows}

    def touch(self, ids: Iterable[int]) -> None:
        """Mark already known vacancies as still listed."""
        now = _now()
        with self._conn:
            self._conn.executemany(
                "UPDATE vacancies SET last_seen = ? WHERE id = ?",
                [(now, i) for i in ids],
            )

    def add(self, vacancies: Iterable[tuple[Vacancy, bool]]) -> None:
        now = _now()
        with self._conn:
            self._conn.executemany(
                "INSERT OR IGNORE INTO vacancies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        v.id,
                        v.url,
                        v.title,
                        v.company,
                        v.salary,
                        v.work_format,
                        v.meta,
                        int(relevant),
                        now,
                        now,
                    )
                    for v, relevant in vacancies
                ],
            )
