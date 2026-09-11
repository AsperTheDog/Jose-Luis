from db.repositories.base import BaseRepository


class QuarantineRepository(BaseRepository):
    async def is_quarantined(self, user_id: int) -> bool:
        async with self._db.execute("SELECT 1 FROM quarantine WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

    async def add_quarantine(self, user_id: int, reason: str | None = None) -> None:
        await self._db.execute(
            "INSERT INTO quarantine (user_id, reason) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET reason = excluded.reason",
            (user_id, reason)
        )
        await self._db.commit()

    async def remove_quarantine(self, user_id: int) -> bool:
        async with self._db.execute("DELETE FROM quarantine WHERE user_id = ?", (user_id,)) as cursor:
            deleted = cursor.rowcount > 0
            await self._db.commit()
            return deleted

    async def get_quarantine_reason(self, user_id: int) -> str | None:
        async with self._db.execute("SELECT reason FROM quarantine WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
