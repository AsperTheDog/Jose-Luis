from database import DBManager


class GuildConfigManager:

    def __init__(self, db: DBManager):
        self.db = db

    from typing import List, Optional

    # Getters
    async def get_admin_channel_id(self, guild_id: int) -> int:
        await self.db.ensure_guild_exists(guild_id)
        async with self.db.db.execute("SELECT admin_channel_id FROM guild_config WHERE guild_id = ?", (guild_id,)) as cursor:
            res = await cursor.fetchone()
            return res[0] if res else 0

    async def get_log_channel_id(self, guild_id: int) -> Optional[int]:
        await self.db.ensure_guild_exists(guild_id)
        async with self.db.db.execute("SELECT log_channel_id FROM guild_config WHERE guild_id = ?", (guild_id,)) as cursor:
            res = await cursor.fetchone()
            return res[0] if res else None

    async def get_death_channel_id(self, guild_id: int) -> int:
        await self.db.ensure_guild_exists(guild_id)
        async with self.db.db.execute("SELECT death_channel_id FROM guild_config WHERE guild_id = ?", (guild_id,)) as cursor:
            res = await cursor.fetchone()
            return res[0] if res else 0

    async def get_death_grace_seconds(self, guild_id: int) -> float:
        await self.db.ensure_guild_exists(guild_id)
        async with self.db.db.execute("SELECT death_grace_seconds FROM guild_config WHERE guild_id = ?", (guild_id,)) as cursor:
            res = await cursor.fetchone()
            return res[0] if res else 60.0

    async def get_global_cooldown_seconds(self, guild_id: int) -> float:
        await self.db.ensure_guild_exists(guild_id)
        async with self.db.db.execute("SELECT global_cooldown_seconds FROM guild_config WHERE guild_id = ?", (guild_id,)) as cursor:
            res = await cursor.fetchone()
            return res[0] if res else 600.0

    async def get_event_mensajes(self, guild_id: int) -> bool:
        await self.db.ensure_guild_exists(guild_id)
        async with self.db.db.execute("SELECT event_mensajes FROM guild_config WHERE guild_id = ?", (guild_id,)) as cursor:
            res = await cursor.fetchone()
            return bool(res[0]) if res else True

    async def get_event_miembros(self, guild_id: int) -> bool:
        await self.db.ensure_guild_exists(guild_id)
        async with self.db.db.execute("SELECT event_miembros FROM guild_config WHERE guild_id = ?", (guild_id,)) as cursor:
            res = await cursor.fetchone()
            return bool(res[0]) if res else True

    async def get_event_moderacion(self, guild_id: int) -> bool:
        await self.db.ensure_guild_exists(guild_id)
        async with self.db.db.execute("SELECT event_moderacion FROM guild_config WHERE guild_id = ?", (guild_id,)) as cursor:
            res = await cursor.fetchone()
            return bool(res[0]) if res else True

    async def get_event_canales(self, guild_id: int) -> bool:
        await self.db.ensure_guild_exists(guild_id)
        async with self.db.db.execute("SELECT event_canales FROM guild_config WHERE guild_id = ?", (guild_id,)) as cursor:
            res = await cursor.fetchone()
            return bool(res[0]) if res else True

    # Setters
    async def set_admin_channel_id(self, guild_id: int, channel_id: int) -> None:
        await self.db.ensure_guild_exists(guild_id)
        await self.db.db.execute("UPDATE guild_config SET admin_channel_id = ? WHERE guild_id = ?", (channel_id, guild_id))
        await self.db.db.commit()

    async def set_log_channel_id(self, guild_id: int, channel_id: Optional[int]) -> None:
        await self.db.ensure_guild_exists(guild_id)
        await self.db.db.execute("UPDATE guild_config SET log_channel_id = ? WHERE guild_id = ?", (channel_id, guild_id))
        await self.db.db.commit()

    async def set_death_channel_id(self, guild_id: int, channel_id: int) -> None:
        await self.db.ensure_guild_exists(guild_id)
        await self.db.db.execute("UPDATE guild_config SET death_channel_id = ? WHERE guild_id = ?", (channel_id, guild_id))
        await self.db.db.commit()

    async def set_death_grace_seconds(self, guild_id: int, seconds: float) -> None:
        await self.db.ensure_guild_exists(guild_id)
        await self.db.db.execute("UPDATE guild_config SET death_grace_seconds = ? WHERE guild_id = ?", (seconds, guild_id))
        await self.db.db.commit()

    async def set_global_cooldown_seconds(self, guild_id: int, seconds: float) -> None:
        await self.db.ensure_guild_exists(guild_id)
        await self.db.db.execute("UPDATE guild_config SET global_cooldown_seconds = ? WHERE guild_id = ?", (seconds, guild_id))
        await self.db.db.commit()

    async def set_event_mensajes(self, guild_id: int, enabled: bool) -> None:
        await self.db.ensure_guild_exists(guild_id)
        await self.db.db.execute("UPDATE guild_config SET event_mensajes = ? WHERE guild_id = ?", (int(enabled), guild_id))
        await self.db.db.commit()

    async def set_event_miembros(self, guild_id: int, enabled: bool) -> None:
        await self.db.ensure_guild_exists(guild_id)
        await self.db.db.execute("UPDATE guild_config SET event_miembros = ? WHERE guild_id = ?", (int(enabled), guild_id))
        await self.db.db.commit()

    async def set_event_moderacion(self, guild_id: int, enabled: bool) -> None:
        await self.db.ensure_guild_exists(guild_id)
        await self.db.db.execute("UPDATE guild_config SET event_moderacion = ? WHERE guild_id = ?", (int(enabled), guild_id))
        await self.db.db.commit()

    async def set_event_canales(self, guild_id: int, enabled: bool) -> None:
        await self.db.ensure_guild_exists(guild_id)
        await self.db.db.execute("UPDATE guild_config SET event_canales = ? WHERE guild_id = ?", (int(enabled), guild_id))
        await self.db.db.commit()

    # Operators
    async def get_operators(self, guild_id: int) -> List[int]:
        await self.db.ensure_guild_exists(guild_id)
        async with self.db.db.execute("SELECT operator_id FROM guild_operators WHERE guild_id = ?", (guild_id,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def add_operator(self, guild_id: int, operator_id: int) -> bool:
        await self.db.ensure_guild_exists(guild_id)
        cursor = await self.db.db.execute("INSERT OR IGNORE INTO guild_operators (guild_id, operator_id) VALUES (?, ?)", (guild_id, operator_id))
        await self.db.db.commit()
        return cursor.rowcount > 0

    async def remove_operator(self, guild_id: int, operator_id: int) -> bool:
        await self.db.ensure_guild_exists(guild_id)
        cursor = await self.db.db.execute("DELETE FROM guild_operators WHERE guild_id = ? AND operator_id = ?", (guild_id, operator_id))
        await self.db.db.commit()
        return cursor.rowcount > 0

    async def is_operator(self, guild_id: int, operator_id: int) -> bool:
        await self.db.ensure_guild_exists(guild_id)
        async with self.db.db.execute("SELECT 1 FROM guild_operators WHERE guild_id = ? AND operator_id = ?", (guild_id, operator_id)) as cursor:
            row = await cursor.fetchone()
            return row is not None

    # Channel Whitelist
    async def get_channel_whitelist(self, guild_id: int) -> List[int]:
        await self.db.ensure_guild_exists(guild_id)
        async with self.db.db.execute("SELECT channel_id FROM guild_channel_whitelist WHERE guild_id = ?", (guild_id,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def add_to_channel_whitelist(self, guild_id: int, channel_id: int) -> bool:
        await self.db.ensure_guild_exists(guild_id)
        cursor = await self.db.db.execute("INSERT OR IGNORE INTO guild_channel_whitelist (guild_id, channel_id) VALUES (?, ?)", (guild_id, channel_id))
        await self.db.db.commit()
        return cursor.rowcount > 0

    async def remove_from_channel_whitelist(self, guild_id: int, channel_id: int) -> bool:
        await self.db.ensure_guild_exists(guild_id)
        cursor = await self.db.db.execute("DELETE FROM guild_channel_whitelist WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id))
        await self.db.db.commit()
        return cursor.rowcount > 0

    async def is_channel_whitelisted(self, guild_id: int, channel_id: int) -> bool:
        await self.db.ensure_guild_exists(guild_id)
        async with self.db.db.execute("SELECT 1 FROM guild_channel_whitelist WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id)) as cursor:
            row = await cursor.fetchone()
            return row is not None