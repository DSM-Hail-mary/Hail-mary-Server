"""SQLite connection helper for the Hail-Mary backend server.

Single-file SQLite database (문서/제안서_백엔드추가.md 4.4.1: "SQLite(로컬 개발·데모)").
`open_database()` is the one place that knows how to open + initialize the DB,
so the FastAPI app, data-loading scripts, and tests all share the same setup.
"""
import sqlite3
from pathlib import Path
from typing import Union

from Hail_Mary.server.db.schema import init_db


def open_database(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open (creating parent directories and the file if needed) a SQLite
    connection with dict-like row access, and ensure the schema exists."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    init_db(connection)
    return connection
