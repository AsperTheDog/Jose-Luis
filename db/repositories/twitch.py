from db.repositories.base import BaseRepository


class TwitchRepository(BaseRepository):
    async def get_tracked_streamers(self) -> list[str]:
        async with self._db.execute("SELECT DISTINCT twitch_username FROM tracked_streamers") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_streamer_destinations(self, twitch_user: str) -> list[tuple[int, str | None, int]]:
        async with self._db.execute("SELECT channel_id, kick_username, everyone FROM tracked_streamers WHERE twitch_username = ?", (twitch_user,)) as cursor:
            return await cursor.fetchall()

    async def add_or_update_tracked_streamer(self, guild_id: int, channel_id: int, twitch_user: str, kick_user: str | None, at_everyone: int) -> None:
        await self._db.execute("""INSERT INTO tracked_streamers (guild_id, channel_id, twitch_username, kick_username, everyone)
                                 VALUES (?, ?, ?, ?, ?)
                                 ON CONFLICT(guild_id, twitch_username)
                                 DO UPDATE SET channel_id = excluded.channel_id, kick_username = excluded.kick_username
                                 """, (guild_id, channel_id, twitch_user, kick_user, at_everyone))
        await self._db.commit()

    async def remove_tracked_streamer(self, guild_id: int, twitch_user: str) -> bool:
        async with self._db.execute("DELETE FROM tracked_streamers WHERE guild_id = ? AND twitch_username = ?", (guild_id, twitch_user)) as cursor:
            await self._db.commit()
            return cursor.rowcount > 0

    async def get_guild_tracked_streamers(self, guild_id: int) -> list[tuple[str, str | None, int]]:
        async with self._db.execute("SELECT twitch_username, kick_username, channel_id FROM tracked_streamers WHERE guild_id = ?", (guild_id,)) as cursor:
            return await cursor.fetchall()
