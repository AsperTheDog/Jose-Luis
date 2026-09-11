from typing import Any, Optional

import aiosqlite
from discord import Emoji

from db.repositories.base import BaseRepository


class GachaRepository(BaseRepository):
    async def add_unit_definition(self, unit_id: str, name: str, phrase: str, interpreter: str, rarity: int, source: str, emoji: str) -> bool:
        try:
            await self._db.execute(
                """INSERT INTO gacha_unit_definitions (unit_id, name, phrase, interpreter, rarity, source, emoji) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (unit_id, name, phrase, interpreter, rarity, source, emoji),
            )
            await self._db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def fix_missing_emojis(self, emojis: list[Emoji]) -> int:
        emoji_map = {emoji.name: str(emoji) for emoji in emojis}

        async with self._db.execute("SELECT unit_id, name FROM gacha_unit_definitions WHERE emoji IS NULL OR emoji = ''") as cursor:
            rows = await cursor.fetchall()

        fixed_count = 0
        for row in rows:
            unit_id = row["unit_id"]
            if unit_id in emoji_map:
                await self._db.execute("UPDATE gacha_unit_definitions SET emoji = ? WHERE unit_id = ?", (emoji_map[unit_id], unit_id))
                fixed_count += 1

        if fixed_count > 0:
            await self._db.commit()

        return fixed_count

    async def get_unit_definition(self, unit_id: str) -> Optional[dict[str, Any]]:
        async with self._db.execute("SELECT * FROM gacha_unit_definitions WHERE unit_id = ?", (unit_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_unit_definition_by_name(self, name: str) -> Optional[dict[str, Any]]:
        async with self._db.execute("SELECT * FROM gacha_unit_definitions WHERE LOWER(name) = LOWER(?)", (name,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_all_unit_definitions(self) -> dict[str, dict[str, Any]]:
        async with self._db.execute("SELECT * FROM gacha_unit_definitions") as cursor:
            rows = await cursor.fetchall()
            return {row["unit_id"]: dict(row) for row in rows}

    async def delete_unit_definition(self, unit_id: str) -> bool:
        cursor = await self._db.execute("DELETE FROM gacha_unit_definitions WHERE unit_id = ?", (unit_id,))
        await self._db.execute("DELETE FROM gacha_shards WHERE unit_id = ?", (unit_id,))
        await self._db.execute("DELETE FROM gacha_units_owned WHERE unit_id = ?", (unit_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    async def ensure_user(self, user_id: int) -> None:
        await self._db.execute("INSERT OR IGNORE INTO gacha_users (user_id) VALUES (?)", (user_id,))
        await self._db.commit()

    async def get_dust(self, user_id: int) -> int:
        await self.ensure_user(user_id)
        async with self._db.execute("SELECT dust FROM gacha_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def add_dust(self, user_id: int, amount: int) -> None:
        await self.ensure_user(user_id)
        await self._db.execute("UPDATE gacha_users SET dust = MAX(0, dust + ?) WHERE user_id = ?", (int(amount), user_id))
        await self._db.commit()

    async def add_shard(self, user_id: int, unit_id: str, amount: int = 1) -> None:
        await self._db.execute(
            """INSERT INTO gacha_shards (user_id, unit_id, amount) VALUES (?, ?, ?)
               ON CONFLICT(user_id, unit_id) DO UPDATE SET amount = amount + excluded.amount""",
            (user_id, unit_id, amount),
        )
        await self._db.commit()

    async def get_shards(self, user_id: int) -> dict[str, int]:
        async with self._db.execute("SELECT unit_id, amount FROM gacha_shards WHERE user_id = ? AND amount > 0", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return dict(rows)

    async def get_shard_count(self, user_id: int, unit_id: str) -> int:
        async with self._db.execute("SELECT amount FROM gacha_shards WHERE user_id = ? AND unit_id = ?", (user_id, unit_id)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def remove_shards(self, user_id: int, unit_id: str, amount: int) -> bool:
        current = await self.get_shard_count(user_id, unit_id)
        if current < amount:
            return False
        await self._db.execute("UPDATE gacha_shards SET amount = amount - ? WHERE user_id = ? AND unit_id = ?", (amount, user_id, unit_id))
        await self._db.commit()
        return True

    async def add_unit(self, user_id: int, unit_id: str, amount: int = 1) -> None:
        await self._db.execute(
            """INSERT INTO gacha_units_owned (user_id, unit_id, amount) VALUES (?, ?, ?)
               ON CONFLICT(user_id, unit_id) DO UPDATE SET amount = amount + excluded.amount""",
            (user_id, unit_id, amount),
        )
        await self._db.commit()

    async def get_units(self, user_id: int) -> dict[str, int]:
        async with self._db.execute("SELECT unit_id, amount FROM gacha_units_owned WHERE user_id = ? AND amount > 0", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return dict(rows)

    async def get_unit_count(self, user_id: int, unit_id: str) -> int:
        async with self._db.execute("SELECT amount FROM gacha_units_owned WHERE user_id = ? AND unit_id = ?", (user_id, unit_id)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_all_owned_units(self) -> list[tuple[int, str, int]]:
        async with self._db.execute("SELECT user_id, unit_id, amount FROM gacha_units_owned WHERE amount > 0") as cursor:
            return await cursor.fetchall()
