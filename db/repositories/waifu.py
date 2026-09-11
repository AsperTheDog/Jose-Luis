from typing import Any, Optional

from db.repositories.base import BaseRepository


class WaifuRepository(BaseRepository):
    async def ensure_user(self, user_id: int, default_value: int = 1000) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO waifu_users (user_id, pronoun, value, claim) VALUES (?, 'waifu', ?, NULL)",
            (user_id, default_value),
        )
        await self._db.commit()

    async def get_user(self, user_id: int) -> Optional[dict[str, Any]]:
        await self.ensure_user(user_id)
        async with self._db.execute("SELECT * FROM waifu_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def set_pronoun(self, user_id: int, pronoun: str) -> None:
        await self.ensure_user(user_id)
        await self._db.execute("UPDATE waifu_users SET pronoun = ? WHERE user_id = ?", (pronoun, user_id))
        await self._db.commit()

    async def get_owner(self, user_id: int) -> Optional[dict[str, Any]]:
        async with self._db.execute("SELECT * FROM waifu_users WHERE claim = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def is_affinity_active(self, user_id_1: int, user_id_2: int) -> bool:
        u1 = await self.get_user(user_id_1)
        u2 = await self.get_user(user_id_2)
        if u1 and u2 and u1.get("claim") == user_id_2 and u2.get("claim") == user_id_1:
            return True
        return False

    async def get_effective_value(self, user_id: int, ignore_affinity: bool = False) -> tuple[int, bool]:
        u_data = await self.get_user(user_id)
        if not u_data:
            return 1000, False

        base_val = u_data["value"]
        owner = await self.get_owner(user_id)
        is_affinity = False

        if owner and not ignore_affinity:
            is_affinity = await self.is_affinity_active(user_id, owner["user_id"])

        effective_val = base_val * 2 if is_affinity else base_val
        return effective_val, is_affinity

    async def claim_target(self, claimer_id: int, target_id: int, new_target_value: int) -> None:
        await self.ensure_user(claimer_id)
        await self.ensure_user(target_id)
        await self._db.execute("UPDATE waifu_users SET claim = NULL WHERE claim = ?", (target_id,))
        await self._db.execute("UPDATE waifu_users SET claim = ? WHERE user_id = ?", (target_id, claimer_id))
        await self._db.execute("UPDATE waifu_users SET value = ? WHERE user_id = ?", (new_target_value, target_id))
        await self._db.commit()

    async def divorce(self, claimer_id: int) -> None:
        await self.ensure_user(claimer_id)
        await self._db.execute("UPDATE waifu_users SET claim = NULL WHERE user_id = ?", (claimer_id,))
        await self._db.commit()

    async def force_unclaim(self, waifu_id: int, owner_id: int) -> None:
        await self._db.execute("UPDATE waifu_users SET claim = NULL WHERE user_id = ?", (owner_id,))
        await self._db.execute("INSERT OR IGNORE INTO waifu_blocks (blocker_id, blocked_id) VALUES (?, ?)", (waifu_id, owner_id))
        await self._db.commit()

    async def is_blocked(self, blocker_id: int, blocked_id: int) -> bool:
        async with self._db.execute("SELECT 1 FROM waifu_blocks WHERE blocker_id = ? AND blocked_id = ?", (blocker_id, blocked_id)) as cursor:
            return await cursor.fetchone() is not None

    async def add_block(self, blocker_id: int, blocked_id: int) -> None:
        await self._db.execute("INSERT OR IGNORE INTO waifu_blocks (blocker_id, blocked_id) VALUES (?, ?)", (blocker_id, blocked_id))
        await self._db.commit()

    async def remove_block(self, blocker_id: int, blocked_id: int) -> bool:
        async with self._db.execute("DELETE FROM waifu_blocks WHERE blocker_id = ? AND blocked_id = ?", (blocker_id, blocked_id)) as cursor:
            deleted = cursor.rowcount > 0
            await self._db.commit()
            return deleted

    async def get_blocks(self, blocker_id: int) -> list[int]:
        async with self._db.execute("SELECT blocked_id FROM waifu_blocks WHERE blocker_id = ?", (blocker_id,)) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

    async def add_gift(self, waifu_id: int, item_name: str, cost_per_unit: int, amount: int = 1) -> None:
        await self.ensure_user(waifu_id)
        total_cost = cost_per_unit * amount
        await self._db.execute(
            """INSERT INTO waifu_gifts (user_id, item_name, amount) VALUES (?, ?, ?)
               ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?""",
            (waifu_id, item_name, amount, amount),
        )
        await self._db.execute("UPDATE waifu_users SET value = value + ? WHERE user_id = ?", (total_cost, waifu_id))
        await self._db.commit()

    async def get_gifts(self, user_id: int) -> list[tuple[str, int]]:
        async with self._db.execute("SELECT item_name, amount FROM waifu_gifts WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchall()

    async def get_top_users(self, limit: int = 10) -> list[dict[str, Any]]:
        async with self._db.execute("SELECT * FROM waifu_users") as cursor:
            rows = await cursor.fetchall()
            users = [dict(r) for r in rows]

        results = []
        for u in users:
            eff_val, is_affinity = await self.get_effective_value(u["user_id"])
            results.append({
                "user_id": u["user_id"],
                "pronoun": u.get("pronoun", "waifu"),
                "base_value": u["value"],
                "effective_value": eff_val,
                "is_affinity": is_affinity,
                "claim": u.get("claim"),
            })

        results.sort(key=lambda x: x["effective_value"], reverse=True)
        return results[:limit]
