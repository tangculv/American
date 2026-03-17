from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..config import ProjectPaths


class ManagedConnection(sqlite3.Connection):
    def __enter__(self) -> ManagedConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False


def get_connection(paths: ProjectPaths | None = None) -> ManagedConnection:
    paths = paths or ProjectPaths()
    paths.ensure()
    database_path = Path(paths.database_path)
    connection = sqlite3.connect(database_path, factory=ManagedConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


@contextmanager
def sqlite_connection(paths: ProjectPaths | None = None) -> Iterator[sqlite3.Connection]:
    connection = get_connection(paths)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
