import json
import os
import sqlite3
from typing import Any

import aiosqlite

from db.schema import parse_create_tables


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class Database:
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
        definitions: dict[str, list[tuple[str, str]]] = {}
        for file_name in sql_files:
            file_path = os.path.join(folder_path, file_name)
            with open(file_path, "r", encoding="utf-8") as f:
                sql_script = f.read()
            await self.conn.executescript(sql_script)
            self._merge_table_definitions(definitions, parse_create_tables(sql_script))
        await self.conn.commit()
        await self._add_missing_columns(definitions)

    @staticmethod
    def _merge_table_definitions(
        target: dict[str, list[tuple[str, str]]],
        parsed: dict[str, list[tuple[str, str]]],
    ) -> None:
        for table, columns in parsed.items():
            known = {name for name, _ in target.setdefault(table, [])}
            target[table].extend((name, definition) for name, definition in columns if name not in known)

    async def _add_missing_columns(self, definitions: dict[str, list[tuple[str, str]]]) -> None:
        added = 0
        for table, columns in definitions.items():
            async with self.conn.execute(f"PRAGMA table_info({_quote_identifier(table)})") as cursor:
                existing = {row["name"] for row in await cursor.fetchall()}
            if not existing:
                continue

            for name, definition in columns:
                if name in existing:
                    continue
                try:
                    await self.conn.execute(
                        f"ALTER TABLE {_quote_identifier(table)} ADD COLUMN {definition}"
                    )
                except sqlite3.OperationalError as error:
                    print(f"[db] No se pudo añadir la columna {table}.{name}: {error}")
                else:
                    existing.add(name)
                    added += 1
                    print(f"[db] Columna añadida: {table}.{name}")
        await self.conn.commit()
        if added:
            print(f"[db] {added} columna(s) añadida(s) desde queries/init.")

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
