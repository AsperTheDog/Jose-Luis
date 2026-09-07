from typing import Optional

from db.repositories.base import BaseRepository


class EconomyRepository(BaseRepository):
    """economy_users / economy_jobs: balances, jobs, crime, interest and poker."""

    async def get_job_perk(self, user_job_id: str, perk_name: str, default: float, user_id: Optional[int] = None) -> float:
        def calc_level(job_level: float, val: float) -> float:
            if perk_name == "job_penalty":
                return val
            if val < 0.0:
                return max((-val) * 0.2, (-val) - (-val) * 0.05 * job_level)
            return val + val * 0.1 * job_level

        level = 1.0
        if user_id:
            async with self._db.execute("SELECT level FROM economy_jobs WHERE user_id = ? AND job_id = ?", (user_id, user_job_id)) as cursor:
                row = await cursor.fetchone()
                if row and row[0] is not None:
                    level = float(row[0])

        perks = self._db.job_registry.get(user_job_id, {}).get("perks", {})
        raw_val = perks.get(perk_name)

        if raw_val is not None:
            try:
                return calc_level(level, float(raw_val))
            except (ValueError, TypeError):
                pass

        return calc_level(level, default)

    async def get_active_job(self, user_id: int) -> str | None:
        async with self._db.execute("SELECT active_job FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return row[0]

    async def get_user_job_perk(self, user_id: int, perk_name: str, default: float) -> float:
        job = await self.get_active_job(user_id)
        if job is None:
            return default
        return await self.get_job_perk(job, perk_name, default, user_id)

    async def ensure_user(self, user_id: int) -> None:
        await self._db.execute("INSERT OR IGNORE INTO economy_users (user_id) VALUES (?)", (user_id,))

    async def get_balance(self, user_id: int) -> int:
        await self.ensure_user(user_id)
        async with self._db.execute("SELECT balance FROM economy_users WHERE user_id = ?", (user_id,)) as c:
            return (await c.fetchone())[0]

    async def update_balance(self, user_id: int, amount: int) -> None:
        await self.ensure_user(user_id)
        await self._db.execute("UPDATE economy_users SET balance = MAX(0, balance + ?) WHERE user_id = ?", (int(amount), user_id))
        await self._db.commit()

    async def get_user_data(self, user_id: int) -> dict:
        await self.ensure_user(user_id)
        async with self._db.execute("SELECT * FROM economy_users WHERE user_id = ?", (user_id,)) as c:
            row = await c.fetchone()
            return dict(row) if row else {}

    async def get_job_data(self, user_id: int, job_id: str) -> dict:
        await self.ensure_user(user_id)
        async with self._db.execute("SELECT * FROM economy_jobs WHERE user_id = ? AND job_id = ?", (user_id, job_id)) as c:
            row = await c.fetchone()
            return dict(row) if row else {"level": 1, "xp": 0}

    async def crime_success(self, user_id: int, reward: int) -> None:
        await self.ensure_user(user_id)
        await self._db.execute("UPDATE economy_users SET balance = MAX(0, balance + ?), crime_streak = crime_streak + 1 WHERE user_id = ?", (int(reward), user_id))
        await self._db.commit()

    async def crime_failure(self, user_id: int, penalty: int, jail_until_str: str) -> None:
        await self.ensure_user(user_id)
        await self._db.execute("UPDATE economy_users SET balance = MAX(0, balance - ?), crime_streak = 0, jail_until = ? WHERE user_id = ?", (int(penalty), jail_until_str, user_id))
        await self._db.commit()

    async def transfer_balance(self, sender_id: int, recipient_id: int, amount: int) -> None:
        await self.ensure_user(recipient_id)
        await self._db.execute("UPDATE economy_users SET balance = MAX(0, balance - ?) WHERE user_id = ?", (int(amount), sender_id))
        await self._db.execute("UPDATE economy_users SET balance = MAX(0, balance + ?) WHERE user_id = ?", (int(amount), recipient_id))
        await self._db.commit()

    async def daily_claim(self, user_id: int, payout: int, new_streak: int, timestamp_iso: str) -> None:
        await self._db.execute("UPDATE economy_users SET balance = MAX(0, balance + ?), daily_streak = ?, last_daily = ? WHERE user_id = ?", (int(payout), new_streak, timestamp_iso, user_id))
        await self._db.commit()

    async def get_balance_log(self, user_id: int, limit: int = 10) -> list[dict]:
        await self.ensure_user(user_id)
        async with self._db.execute(
            "SELECT delta, prev_balance, new_balance, created_at FROM economy_balance_log "
            "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, int(limit)),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_work_and_job(self, user_id: int, salary: int, last_work_iso: str, job_id: str, level: int, new_xp: int) -> None:
        await self._db.execute("UPDATE economy_users SET balance = MAX(0, balance + ?), last_work = ? WHERE user_id = ?", (int(salary), last_work_iso, user_id))
        await self._db.execute("INSERT OR REPLACE INTO economy_jobs (user_id, job_id, level, xp) VALUES (?, ?, ?, ?)", (user_id, job_id, level, new_xp))
        await self._db.commit()

    async def update_active_job(self, user_id: int, selected_job_id: str, last_job_switch_iso: str) -> None:
        await self._db.execute("UPDATE economy_users SET active_job = ?, last_job_switch = ? WHERE user_id = ?", (selected_job_id, last_job_switch_iso, user_id))
        await self._db.commit()

    async def claim_interest(self, user_id: int) -> int:
        async with self._db.execute("SELECT unclaimed_interest FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return 0

        unclaimed = row[0]
        if unclaimed <= 0:
            return 0

        await self._db.execute("UPDATE economy_users SET balance = MAX(0, balance + ?), unclaimed_interest = 0 WHERE user_id = ?", (int(unclaimed), user_id))
        await self._db.commit()

        return unclaimed

    async def process_slots_bet(self, user_id: int, bet_amount: int, net_change: int, default_balance: int = 1000) -> tuple[bool, int]:
        async with self._db.execute("SELECT balance FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            balance = default_balance
            await self._db.execute("INSERT INTO economy_users (user_id, balance) VALUES (?, ?)", (user_id, balance))
        else:
            balance = row[0]

        if balance < bet_amount:
            return False, balance

        new_balance = max(0, balance + net_change)
        await self._db.execute("UPDATE economy_users SET balance = ? WHERE user_id = ?", (int(new_balance), user_id))
        await self._db.commit()

        return True, new_balance

    async def get_active_users(self) -> list[tuple[int, int, str | None, int]]:
        async with self._db.execute("SELECT user_id, balance, active_job, unclaimed_interest FROM economy_users WHERE balance > 0") as cursor:
            return await cursor.fetchall()

    async def add_unclaimed_interest(self, user_id: int, daily_interest: int) -> None:
        if daily_interest > 0:
            await self._db.execute("UPDATE economy_users SET unclaimed_interest = unclaimed_interest + ? WHERE user_id = ?", (int(daily_interest), user_id))
            await self._db.commit()

    async def poker_get_balance(self, user_id: int) -> int:
        async with self._db.execute("SELECT balance FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def poker_remove_balance(self, user_id: int, amount: int) -> bool:
        async with self._db.execute("SELECT balance FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()

        if not row or row[0] < amount:
            return False

        new_balance = row[0] - amount
        await self._db.execute("UPDATE economy_users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
        await self._db.commit()
        return True

    async def poker_add_balance(self, user_id: int, amount: int) -> None:
        async with self._db.execute("SELECT balance FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            await self._db.execute("INSERT INTO economy_users (user_id, balance) VALUES (?, ?)", (user_id, amount))
        else:
            new_balance = row[0] + amount
            await self._db.execute("UPDATE economy_users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
        await self._db.commit()
