from db.repositories.base import BaseRepository


class ActivityRepository(BaseRepository):
    """user_stats: per-guild message/activity counters."""

    async def update_user_stats(self, guild_id: int, user_id: int, xp_gained: int, word_count: int, char_count: int, attachment_count: int, emoji_count: int) -> None:
        await self._db.execute("""INSERT INTO user_stats (guild_id, user_id, messages, xp, words, chars, attachments, emojis)
                                 VALUES (?, ?, 1, ?, ?, ?, ?, ?) ON CONFLICT(guild_id, user_id) DO UPDATE SET messages = messages + 1, xp = xp + excluded.xp,
                                                         words = words + excluded.words, chars = chars + excluded.chars,
                                                         attachments = attachments + excluded.attachments, emojis = emojis + excluded.emojis
            """, (guild_id, user_id, xp_gained, word_count, char_count, attachment_count, emoji_count))
        await self._db.commit()

    async def get_user_stats(self, guild_id: int, user_id: int) -> tuple | None:
        async with self._db.execute("SELECT messages, xp, words, chars, attachments, emojis FROM user_stats WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cursor:
            return await cursor.fetchone()

    async def get_top_users_by_category(self, guild_id: int, category: str) -> list[tuple[int, int, int]]:
        allowed_categories = {"messages", "xp", "words", "chars", "attachments", "emojis"}
        if category not in allowed_categories:
            raise ValueError(f"Invalid category: {category}")

        async with self._db.execute(f"""SELECT user_id, {category}, xp FROM user_stats
                                       WHERE guild_id = ? ORDER BY {category} DESC
                                       LIMIT 10""", (guild_id,)) as cursor:
            return await cursor.fetchall()
