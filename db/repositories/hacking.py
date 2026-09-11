from db.repositories.base import BaseRepository


class HackingRepository(BaseRepository):
    async def add_win(self, user_id: int, profit: int) -> None:
        await self._db.execute(
            """INSERT INTO hacking_daily (user_id, profit) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET profit = profit + excluded.profit""", (user_id, profit))
        await self._db.commit()

    async def is_over_threshold(self, user_id: int, threshold: int) -> bool:
        async with self._db.execute("SELECT profit from hacking_daily WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] > threshold if row else False

    async def reset_daily(self) -> None:
        await self._db.execute("UPDATE hacking_daily SET profit = 0")
        await self._db.commit()
