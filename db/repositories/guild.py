from typing import List

from db.repositories.base import BaseRepository

DEFAULT_CONFIG = {
    "admin_channel_id": 0,
    "log_channel_id": 0,
    "debug_channel_id": 0,
    "death_channel_id": 0,
    "death_grace_seconds": 60.0,
    "global_cooldown_seconds": 600.0,
    "event_mensajes": True,
    "event_miembros": True,
    "event_moderacion": True,
    "event_canales": True,
}


class GuildRepository(BaseRepository):
    async def ensure_exists(self, guild_id: int) -> None:
        query = """
                INSERT OR IGNORE INTO guild_config (
                    guild_id, admin_channel_id, log_channel_id, debug_channel_id,
                    death_channel_id, death_grace_seconds, global_cooldown_seconds,
                    event_mensajes, event_miembros, event_moderacion, event_canales
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
        params = (
            guild_id,
            DEFAULT_CONFIG["admin_channel_id"],
            DEFAULT_CONFIG["log_channel_id"],
            DEFAULT_CONFIG["debug_channel_id"],
            DEFAULT_CONFIG["death_channel_id"],
            DEFAULT_CONFIG["death_grace_seconds"],
            DEFAULT_CONFIG["global_cooldown_seconds"],
            int(DEFAULT_CONFIG["event_mensajes"]),
            int(DEFAULT_CONFIG["event_miembros"]),
            int(DEFAULT_CONFIG["event_moderacion"]),
            int(DEFAULT_CONFIG["event_canales"]),
        )
        await self._db.execute(query, params)
        await self._db.commit()

    async def get(self, guild_id: int, column: str):
        if column not in DEFAULT_CONFIG:
            raise ValueError(f"Columna de configuración desconocida: {column}")
        await self.ensure_exists(guild_id)
        async with self._db.execute(
            f"SELECT {column} FROM guild_config WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            res = await cursor.fetchone()
            value = res[0] if res else DEFAULT_CONFIG[column]
        if isinstance(DEFAULT_CONFIG[column], bool):
            return bool(value)
        return value

    async def set(self, guild_id: int, column: str, value) -> None:
        if column not in DEFAULT_CONFIG:
            raise ValueError(f"Columna de configuración desconocida: {column}")
        await self.ensure_exists(guild_id)
        if isinstance(value, bool):
            value = int(value)
        await self._db.execute(
            f"UPDATE guild_config SET {column} = ? WHERE guild_id = ?", (value, guild_id)
        )
        await self._db.commit()

    async def get_operators(self, guild_id: int) -> List[int]:
        await self.ensure_exists(guild_id)
        async with self._db.execute("SELECT operator_id FROM guild_operators WHERE guild_id = ?", (guild_id,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def add_operator(self, guild_id: int, operator_id: int) -> bool:
        await self.ensure_exists(guild_id)
        cursor = await self._db.execute("INSERT OR IGNORE INTO guild_operators (guild_id, operator_id) VALUES (?, ?)", (guild_id, operator_id))
        await self._db.commit()
        return cursor.rowcount > 0

    async def remove_operator(self, guild_id: int, operator_id: int) -> bool:
        await self.ensure_exists(guild_id)
        cursor = await self._db.execute("DELETE FROM guild_operators WHERE guild_id = ? AND operator_id = ?", (guild_id, operator_id))
        await self._db.commit()
        return cursor.rowcount > 0

    async def is_operator(self, guild_id: int, operator_id: int) -> bool:
        await self.ensure_exists(guild_id)
        async with self._db.execute("SELECT 1 FROM guild_operators WHERE guild_id = ? AND operator_id = ?", (guild_id, operator_id)) as cursor:
            row = await cursor.fetchone()
            return row is not None

    async def get_channel_whitelist(self, guild_id: int) -> List[int]:
        await self.ensure_exists(guild_id)
        async with self._db.execute("SELECT channel_id FROM guild_channel_whitelist WHERE guild_id = ?", (guild_id,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def add_to_channel_whitelist(self, guild_id: int, channel_id: int) -> bool:
        await self.ensure_exists(guild_id)
        cursor = await self._db.execute("INSERT OR IGNORE INTO guild_channel_whitelist (guild_id, channel_id) VALUES (?, ?)", (guild_id, channel_id))
        await self._db.commit()
        return cursor.rowcount > 0

    async def remove_from_channel_whitelist(self, guild_id: int, channel_id: int) -> bool:
        await self.ensure_exists(guild_id)
        cursor = await self._db.execute("DELETE FROM guild_channel_whitelist WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id))
        await self._db.commit()
        return cursor.rowcount > 0

    async def is_channel_whitelisted(self, guild_id: int, channel_id: int) -> bool:
        await self.ensure_exists(guild_id)
        async with self._db.execute("SELECT 1 FROM guild_channel_whitelist WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id)) as cursor:
            row = await cursor.fetchone()
            return row is not None
