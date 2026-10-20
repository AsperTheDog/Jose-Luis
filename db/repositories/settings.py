from db.repositories.base import BaseRepository


class SettingsRepository(BaseRepository):
    async def scientific_notation_users(self) -> set[int]:
        async with self._db.execute("SELECT user_id FROM user_settings WHERE scientific_notation = 1") as cursor:
            rows = await cursor.fetchall()
        return {int(row["user_id"]) for row in rows}

    async def set_scientific_notation(self, user_id: int, enabled: bool) -> None:
        await self._db.execute(
            "INSERT INTO user_settings (user_id, scientific_notation) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET scientific_notation = excluded.scientific_notation",
            (user_id, int(enabled)),
        )
        await self._db.commit()
