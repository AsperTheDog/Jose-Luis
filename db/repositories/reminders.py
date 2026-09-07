from typing import Any, Optional

from db.repositories.base import BaseRepository


class ReminderRepository(BaseRepository):
    """reminders and reminder_subscribers."""

    async def create(self, guild_id: int, channel_id: int, author_id: int, note: str, trigger_at: str) -> int:
        cursor = await self._db.execute(
            "INSERT INTO reminders (guild_id, channel_id, author_id, note, trigger_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, channel_id, author_id, note, trigger_at),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def set_message_id(self, reminder_id: int, message_id: int) -> None:
        await self._db.execute("UPDATE reminders SET message_id = ? WHERE id = ?", (message_id, reminder_id))
        await self._db.commit()

    async def get_due(self, now_iso: str) -> list[dict[str, Any]]:
        async with self._db.execute("SELECT * FROM reminders WHERE triggered = 0 AND trigger_at <= ?", (now_iso,)) as cursor:
            rows = await cursor.fetchall()

        due = [dict(row) for row in rows]
        if due:
            ids = [row["id"] for row in due]
            placeholders = ",".join("?" * len(ids))
            await self._db.execute(f"UPDATE reminders SET triggered = 1 WHERE id IN ({placeholders})", ids)
            await self._db.commit()

        return due

    async def get_by_message_id(self, message_id: int) -> Optional[dict[str, Any]]:
        async with self._db.execute("SELECT * FROM reminders WHERE message_id = ?", (message_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def add_subscriber(self, reminder_id: int, user_id: int) -> bool:
        cursor = await self._db.execute(
            "INSERT OR IGNORE INTO reminder_subscribers (reminder_id, user_id) VALUES (?, ?)",
            (reminder_id, user_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_subscribers(self, reminder_id: int) -> list[int]:
        async with self._db.execute("SELECT user_id FROM reminder_subscribers WHERE reminder_id = ?", (reminder_id,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_related_to_user(self, user_id: int) -> list[dict[str, Any]]:
        async with self._db.execute(
            """SELECT * FROM reminders
               WHERE triggered = 0 AND (author_id = ? OR id IN (SELECT reminder_id FROM reminder_subscribers WHERE user_id = ?))
               ORDER BY trigger_at ASC""",
            (user_id, user_id),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
