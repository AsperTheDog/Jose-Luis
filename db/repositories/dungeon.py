import json
from typing import Any, Optional

from db.repositories.base import BaseRepository

USER_FIELDS = {
    "floor",
    "highest_floor",
    "floor_kills",
    "auto_advance",
    "level",
    "xp",
    "gold",
    "hp",
    "max_hp",
    "energy",
    "max_energy",
    "potions",
    "active_skill",
    "dust",
    "boss_coins",
    "boss_tier",
    "last_boss_at",
    "last_boss_floor",
    "upgrades",
    "shifts",
    "alt_floor",
    "last_alt_at",
    "conversion_date",
    "conversion_used",
    "training_enabled",
    "training_since",
    "runs",
}


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


class DungeonRepository(BaseRepository):
    async def ensure_user(self, user_id: int) -> None:
        await self._db.execute("INSERT OR IGNORE INTO dungeon_users (user_id, potions) VALUES (?, 3)", (user_id,))
        await self._db.commit()

    async def get_user(self, user_id: int) -> dict:
        await self.ensure_user(user_id)
        async with self._db.execute("SELECT * FROM dungeon_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else {}

    async def update_user(self, user_id: int, **fields) -> None:
        await self.ensure_user(user_id)
        updates = {name: value for name, value in fields.items() if name in USER_FIELDS}
        if not updates:
            return
        assignments = ", ".join(f"{name} = ?" for name in updates)
        await self._db.execute(f"UPDATE dungeon_users SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (*updates.values(), user_id))
        await self._db.commit()

    async def add_gold(self, user_id: int, amount: int) -> int:
        await self.ensure_user(user_id)
        await self._db.execute("UPDATE dungeon_users SET gold = MAX(0, gold + ?), updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (int(amount), user_id))
        await self._db.commit()
        return await self.get_gold(user_id)

    async def get_gold(self, user_id: int) -> int:
        async with self._db.execute("SELECT gold FROM dungeon_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def spend_gold(self, user_id: int, amount: int) -> bool:
        await self.ensure_user(user_id)
        cursor = await self._db.execute("UPDATE dungeon_users SET gold = gold - ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND gold >= ?", (int(amount), user_id, int(amount)))
        await self._db.commit()
        return cursor.rowcount > 0

    async def add_dust(self, user_id: int, amount: int) -> None:
        await self.ensure_user(user_id)
        await self._db.execute("UPDATE dungeon_users SET dust = MAX(0, dust + ?), updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (int(amount), user_id))
        await self._db.commit()

    async def add_boss_coins(self, user_id: int, amount: int) -> None:
        await self.ensure_user(user_id)
        await self._db.execute("UPDATE dungeon_users SET boss_coins = MAX(0, boss_coins + ?), updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (int(amount), user_id))
        await self._db.commit()

    async def spend_boss_coins(self, user_id: int, amount: int) -> bool:
        await self.ensure_user(user_id)
        cursor = await self._db.execute("UPDATE dungeon_users SET boss_coins = boss_coins - ?, updated_at = CURRENT_TIMESTAMP " "WHERE user_id = ? AND boss_coins >= ?", (int(amount), user_id, int(amount)))
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_inventory(self, user_id: int) -> list[dict]:
        await self.ensure_user(user_id)
        async with self._db.execute("SELECT * FROM dungeon_inventory WHERE user_id = ? ORDER BY is_equipped DESC, acquired_at DESC", (user_id,),) as cursor:
            rows = await cursor.fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["stats"] = _loads(item.get("stats"), {})
            item["sockets"] = _loads(item.get("sockets"), [])
            items.append(item)
        return items

    async def add_item(self, user_id: int, item: dict) -> None:
        await self.ensure_user(user_id)
        await self._db.execute(
            "INSERT INTO dungeon_inventory (item_uid, user_id, name, slot, rarity, stats, sockets, is_equipped, floor_found) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (
                item["item_uid"],
                user_id,
                item["name"],
                item["slot"],
                item["rarity"],
                _dumps(item.get("stats", {})),
                _dumps(item.get("sockets", [])),
                int(item.get("floor_found", 1)),
            ),
        )
        await self._db.commit()

    async def equip_item(self, user_id: int, item_uid: str) -> bool:
        async with self._db.execute("SELECT slot FROM dungeon_inventory WHERE user_id = ? AND item_uid = ?", (user_id, item_uid)) as cursor:
            row = await cursor.fetchone()
        if not row:
            return False
        slot = row[0]
        await self._db.execute("UPDATE dungeon_inventory SET is_equipped = 0 WHERE user_id = ? AND slot = ?", (user_id, slot))
        await self._db.execute("UPDATE dungeon_inventory SET is_equipped = 1 WHERE user_id = ? AND item_uid = ?", (user_id, item_uid))
        await self._db.commit()
        return True

    async def unequip_item(self, user_id: int, item_uid: str) -> bool:
        cursor = await self._db.execute("UPDATE dungeon_inventory SET is_equipped = 0 WHERE user_id = ? AND item_uid = ?", (user_id, item_uid))
        await self._db.commit()
        return cursor.rowcount > 0

    async def delete_item(self, user_id: int, item_uid: str) -> bool:
        cursor = await self._db.execute("DELETE FROM dungeon_inventory WHERE user_id = ? AND item_uid = ?", (user_id, item_uid))
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_item(self, user_id: int, item_uid: str) -> Optional[dict]:
        async with self._db.execute("SELECT * FROM dungeon_inventory WHERE user_id = ? AND item_uid = ?", (user_id, item_uid)) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        item = dict(row)
        item["stats"] = _loads(item.get("stats"), {})
        item["sockets"] = _loads(item.get("sockets"), [])
        return item

    async def set_item_sockets(self, user_id: int, item_uid: str, sockets: list[dict]) -> None:
        await self._db.execute("UPDATE dungeon_inventory SET sockets = ? WHERE user_id = ? AND item_uid = ?", (_dumps(sockets), user_id, item_uid))
        await self._db.commit()

    async def delete_inventory(self, user_id: int) -> None:
        await self._db.execute("DELETE FROM dungeon_inventory WHERE user_id = ?", (user_id,))
        await self._db.commit()

    async def equipped_items(self, user_id: int) -> list[dict]:
        return [item for item in await self.get_inventory(user_id) if item.get("is_equipped")]

    async def get_mutations(self, user_id: int) -> dict[str, int]:
        async with self._db.execute("SELECT mutation_id, level FROM dungeon_mutations WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
        return {row[0]: int(row[1]) for row in rows}

    async def set_mutation(self, user_id: int, mutation_id: str, level: int) -> None:
        await self._db.execute("INSERT INTO dungeon_mutations (user_id, mutation_id, level) VALUES (?, ?, ?) " "ON CONFLICT(user_id, mutation_id) DO UPDATE SET level = excluded.level", (user_id, mutation_id, int(level)))
        await self._db.commit()

    async def get_echoes(self, user_id: int) -> dict[str, int]:
        async with self._db.execute("SELECT echo_id, level FROM dungeon_echoes WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
        return {row[0]: int(row[1]) for row in rows}

    async def set_echo(self, user_id: int, echo_id: str, level: int) -> None:
        await self._db.execute("INSERT INTO dungeon_echoes (user_id, echo_id, level) VALUES (?, ?, ?) " "ON CONFLICT(user_id, echo_id) DO UPDATE SET level = excluded.level", (user_id, echo_id, int(level)))
        await self._db.commit()

    async def get_fight(self, user_id: int) -> Optional[dict]:
        async with self._db.execute("SELECT state FROM dungeon_active_fight WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        return _loads(row[0], None)

    async def save_fight(self, user_id: int, state: dict) -> None:
        await self._db.execute("INSERT INTO dungeon_active_fight (user_id, state, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) " "ON CONFLICT(user_id) DO UPDATE SET state = excluded.state, updated_at = CURRENT_TIMESTAMP", (user_id, _dumps(state)))
        await self._db.commit()

    async def clear_fight(self, user_id: int) -> None:
        await self._db.execute("DELETE FROM dungeon_active_fight WHERE user_id = ?", (user_id,))
        await self._db.commit()

    async def get_cosmetics(self, user_id: int) -> dict[str, int]:
        async with self._db.execute("SELECT cosmetic_id, equipped FROM dungeon_cosmetics WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
        return {row[0]: int(row[1]) for row in rows}

    async def add_cosmetic(self, user_id: int, cosmetic_id: str) -> bool:
        cursor = await self._db.execute("INSERT OR IGNORE INTO dungeon_cosmetics (user_id, cosmetic_id, equipped) VALUES (?, ?, 0)", (user_id, cosmetic_id))
        await self._db.commit()
        return cursor.rowcount > 0

    async def equip_cosmetic(self, user_id: int, cosmetic_id: str, group: list[str]) -> None:
        placeholders = ",".join("?" for _ in group)
        await self._db.execute(f"UPDATE dungeon_cosmetics SET equipped = 0 WHERE user_id = ? AND cosmetic_id IN ({placeholders})", (user_id, *group))
        await self._db.execute("UPDATE dungeon_cosmetics SET equipped = 1 WHERE user_id = ? AND cosmetic_id = ?", (user_id, cosmetic_id))
        await self._db.commit()

    async def add_log(self, user_id: int, kind: str, message: str) -> None:
        await self._db.execute("INSERT INTO dungeon_log (user_id, kind, message) VALUES (?, ?, ?)", (user_id, kind, message))
        await self._db.commit()

    async def recent_log(self, user_id: int, limit: int = 15) -> list[dict]:
        async with self._db.execute("SELECT kind, message, created_at FROM dungeon_log WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, int(limit)),) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_automation(self, user_id: int) -> dict:
        async with self._db.execute("SELECT * FROM dungeon_automation WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else {"user_id": user_id, "enabled": 0, "sims": 0, "last_tick": None, "last_report": None}

    async def set_automation(self, user_id: int, **fields) -> None:
        await self._db.execute("INSERT OR IGNORE INTO dungeon_automation (user_id) VALUES (?)", (user_id,))
        allowed = {"enabled", "sims", "last_tick", "last_report"}
        updates = {name: value for name, value in fields.items() if name in allowed}
        if not updates:
            await self._db.commit()
            return
        assignments = ", ".join(f"{name} = ?" for name in updates)
        await self._db.execute(f"UPDATE dungeon_automation SET {assignments} WHERE user_id = ?", (*updates.values(), user_id))
        await self._db.commit()

    async def automation_users(self) -> list[dict]:
        async with self._db.execute("SELECT * FROM dungeon_automation WHERE enabled = 1") as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]