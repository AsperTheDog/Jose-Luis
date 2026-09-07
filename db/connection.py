import json
import os
from typing import Any

import aiosqlite


class Database:
    """Owns the SQLite connection lifecycle and shared low-level query helpers.

    Repositories receive a ``Database`` and issue queries through it, so the
    connection (and its ``row_factory``) is configured in exactly one place.
    """

    def __init__(self, path: str = "bot_data.db"):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        self.job_registry: dict[str, dict[str, Any]] = self._load_json("jobs.json")

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path, timeout=30.0)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL;")
        await self.conn.execute("PRAGMA busy_timeout=5000;")
        await self.init_tables()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def init_tables(self) -> None:
        folder_path = "queries/init"
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        sql_files = sorted(f for f in os.listdir(folder_path) if f.endswith(".sql"))
        for file_name in sql_files:
            file_path = os.path.join(folder_path, file_name)
            with open(file_path, "r", encoding="utf-8") as f:
                sql_script = f.read()
            await self.conn.executescript(sql_script)
        await self.conn.commit()

    def execute(self, sql: str, parameters=None):
        return self.conn.execute(sql, parameters)

    def executescript(self, sql_script: str):
        return self.conn.executescript(sql_script)

    def executemany(self, sql: str, parameters):
        return self.conn.executemany(sql, parameters)

    async def commit(self) -> None:
        await self.conn.commit()

    @staticmethod
    def _load_json(path: str) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON file at {path}: {e}.")
        return None
