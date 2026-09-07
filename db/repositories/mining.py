import datetime
from sqlite3 import Row
from typing import Any

from db.repositories.base import BaseRepository


class MiningRepository(BaseRepository):
    """mining_users and the mining inventory tables (pickaxes, materials, valuables)."""

    async def ensure_user(self, user_id: int) -> None:
        await self._db.execute("INSERT OR IGNORE INTO mining_users (user_id) VALUES (?)", (user_id,))
        await self._db.commit()

    async def change_depth(self, user_id: int, selected_level: str) -> None:
        await self.ensure_user(user_id)
        await self._db.execute("UPDATE mining_users SET current_depth_id = ? WHERE user_id = ?", (selected_level, user_id))
        await self._db.commit()

    async def get_user_status(self, user_id: int) -> tuple[Any, Any, Any, Any, Row | None]:
        await self.ensure_user(user_id)
        async with self._db.execute("SELECT energy, current_depth_id, xp, level FROM mining_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            energy, depth_id, current_xp, user_lvl = row
        async with self._db.execute("SELECT id, pickaxe_id, durability FROM mining_inv_pickaxes WHERE user_id = ? AND is_equipped = 1", (user_id,)) as cursor:
            equipped_pick = await cursor.fetchone()

        return energy, depth_id, current_xp, user_lvl, equipped_pick

    async def deduct_energy(self, user_id: int, energy_cost: int) -> None:
        await self.ensure_user(user_id)
        await self._db.execute("UPDATE mining_users SET energy = energy - ? WHERE user_id = ?", (energy_cost, user_id))
        await self._db.commit()

    async def record_mine_action(self, user_id: int, energy_cost: int, db_pick_id: int, new_durability: int, dropped_material: str, total_yield: int, new_xp: int, new_level: int) -> None:
        await self.ensure_user(user_id)
        await self._db.execute("UPDATE mining_users SET energy = energy - ?, xp = ?, level = ? WHERE user_id = ?", (energy_cost, new_xp, new_level, user_id))

        if new_durability <= 0:
            await self._db.execute("DELETE FROM mining_inv_pickaxes WHERE id = ?", (db_pick_id,))
        else:
            await self._db.execute("UPDATE mining_inv_pickaxes SET durability = ? WHERE id = ?", (new_durability, db_pick_id))

        await self._db.execute("""INSERT INTO mining_inv_materials (user_id, material_id, amount)
                                 VALUES (?, ?, ?)
                                 ON CONFLICT(user_id, material_id) DO UPDATE SET amount = amount + ?
                                 """, (user_id, dropped_material, total_yield, total_yield))

        await self._db.commit()

    async def get_refill_data(self, user_id: int) -> tuple[Any, Any, Any, Any]:
        await self.ensure_user(user_id)
        async with self._db.execute("SELECT energy, level, refills FROM mining_users WHERE user_id = ?", (user_id,)) as cursor:
            energy, user_lvl, refills = await cursor.fetchone()

        async with self._db.execute("SELECT balance FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            balance = (await cursor.fetchone())[0]

        return energy, user_lvl, refills, balance

    async def apply_refill(self, user_id: int, new_energy: int, new_balance: int) -> None:
        await self._db.execute("UPDATE mining_users SET energy = ?, refills = refills + 1 WHERE user_id = ?", (new_energy, user_id))
        await self._db.execute("UPDATE economy_users SET balance = ? WHERE user_id = ?", (int(new_balance), user_id))
        await self._db.commit()

    async def get_last_basic_pick(self, user_id: int) -> datetime.datetime | None:
        await self.ensure_user(user_id)
        async with self._db.execute("SELECT last_basic_pick FROM mining_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                return datetime.datetime.fromisoformat(row[0])
            return None

    async def claim_basic_pickaxe(self, user_id: int, pick_id: str, max_dur: int) -> None:
        await self.ensure_user(user_id)
        async with self._db.execute("SELECT COUNT(*) FROM mining_inv_pickaxes WHERE user_id = ? AND is_equipped = 1", (user_id,)) as cursor:
            row = await cursor.fetchone()
            has_equipped = row[0] > 0 if row else False

        is_equipped = 0 if has_equipped else 1

        now = datetime.datetime.now()
        await self._db.execute("UPDATE mining_users SET last_basic_pick = ? WHERE user_id = ?", (now.isoformat(), user_id))
        await self._db.execute("INSERT INTO mining_inv_pickaxes (user_id, pickaxe_id, durability, is_equipped) VALUES (?, ?, ?, ?)", (user_id, pick_id, max_dur, is_equipped))
        await self._db.commit()

    async def get_user_pickaxes(self, user_id: int) -> list[tuple]:
        await self.ensure_user(user_id)
        async with self._db.execute("SELECT id, pickaxe_id, durability, is_equipped FROM mining_inv_pickaxes WHERE user_id = ? ORDER BY id", (user_id,)) as cursor:
            return await cursor.fetchall()

    async def equip_pickaxe(self, user_id: int, target_db_id: int) -> None:
        await self.ensure_user(user_id)
        await self._db.execute("UPDATE mining_inv_pickaxes SET is_equipped = 0 WHERE user_id = ?", (user_id,))
        await self._db.execute("UPDATE mining_inv_pickaxes SET is_equipped = 1 WHERE id = ?", (target_db_id,))
        await self._db.commit()

    async def get_user_inventory(self, user_id: int) -> dict[str, int]:
        await self.ensure_user(user_id)
        async with self._db.execute("SELECT material_id, amount FROM mining_inv_materials WHERE user_id = ?", (user_id,)) as cursor:
            return dict(await cursor.fetchall())

    async def craft_item(self, user_id: int, ingredients: dict[str, int], result_id: str, item_type: str, amount: int, max_durability: int | None = None) -> None:
        await self.ensure_user(user_id)
        for mat_id, req_amount in ingredients.items():
            await self._db.execute("UPDATE mining_inv_materials SET amount = amount - ? WHERE user_id = ? AND material_id = ?", (req_amount * amount, user_id, mat_id))

        await self._db.execute("DELETE FROM mining_inv_materials WHERE amount <= 0 AND user_id = ?", (user_id,))

        if item_type == "pickaxe":
            for _ in range(amount):
                await self._db.execute("INSERT INTO mining_inv_pickaxes (user_id, pickaxe_id, durability) VALUES (?, ?, ?)", (user_id, result_id, max_durability))
        else:
            await self._db.execute("""INSERT INTO mining_inv_valuables (user_id, valuable_id, amount)
                                        VALUES (?, ?, ?)
                                        ON CONFLICT(user_id, valuable_id) DO UPDATE SET amount = amount + ?
                                  """, (user_id, result_id, amount, amount))
        await self._db.commit()

    async def get_user_valuables(self, user_id: int) -> list[tuple[str, int]]:
        async with self._db.execute("SELECT valuable_id, amount FROM mining_inv_valuables WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchall()

    async def sell_all_valuables(self, user_id: int, total_earnings: int) -> None:
        await self._db.execute("DELETE FROM mining_inv_valuables WHERE user_id = ?", (user_id,))
        await self._db.execute("UPDATE economy_users SET balance = MAX(0, balance + ?) WHERE user_id = ?", (int(total_earnings), user_id))
        await self._db.commit()

    async def get_full_profile(self, user_id: int) -> dict[str, Any]:
        await self.ensure_user(user_id)
        async with self._db.execute("SELECT xp, level, energy, current_depth_id FROM mining_users WHERE user_id = ?", (user_id,)) as cursor:
            user_row = await cursor.fetchone()

        async with self._db.execute("SELECT material_id, amount FROM mining_inv_materials WHERE user_id = ?", (user_id,)) as cursor:
            materials = await cursor.fetchall()

        async with self._db.execute("SELECT valuable_id, amount FROM mining_inv_valuables WHERE user_id = ?", (user_id,)) as cursor:
            valuables = await cursor.fetchall()

        async with self._db.execute("SELECT pickaxe_id, durability FROM mining_inv_pickaxes WHERE user_id = ? AND is_equipped = 1", (user_id,)) as cursor:
            equipped_pick = await cursor.fetchone()

        return {
            "user": user_row,
            "materials": dict(materials),
            "valuables": dict(valuables),
            "equipped_pick": equipped_pick,
        }

    async def reset_all_energy(self) -> None:
        await self._db.execute("UPDATE mining_users SET energy = 100, refills = 0")
        await self._db.commit()
