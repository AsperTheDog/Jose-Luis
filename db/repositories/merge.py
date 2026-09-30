import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Optional

import aiosqlite

from db.repositories.base import BaseRepository
from db.repositories.global_stats import GlobalStatsRepository


@dataclass
class MergeReport:
    primary_id: int
    secondary_id: int
    absorbed: dict[str, int] = field(default_factory=dict)
    highlights: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


IDENTITY_COLUMNS: dict[str, tuple[str, ...]] = {
    "economy_users": ("user_id",),
    "economy_jobs": ("user_id",),
    "economy_balance_log": ("user_id",),
    "gacha_users": ("user_id",),
    "gacha_shards": ("user_id",),
    "gacha_units_owned": ("user_id",),
    "mining_users": ("user_id",),
    "mining_inv_materials": ("user_id",),
    "mining_inv_valuables": ("user_id",),
    "mining_inv_pickaxes": ("user_id",),
    "hacking_daily": ("user_id",),
    "horse_bets": ("user_id",),
    "quarantine": ("user_id",),
    "reminders": ("author_id",),
    "reminder_subscribers": ("user_id",),
    "user_stats": ("user_id",),
    "user_global_stats": ("user_id",),
    "waifu_users": ("user_id",),
    "waifu_blocks": ("blocker_id", "blocked_id"),
    "waifu_gifts": ("user_id",),
    "dungeon_users": ("user_id",),
    "dungeon_inventory": ("user_id",),
    "dungeon_mutations": ("user_id",),
    "dungeon_cosmetics": ("user_id",),
    "dungeon_echoes": ("user_id",),
    "dungeon_log": ("user_id",),
    "dungeon_active_fight": ("user_id",),
    "dungeon_last_battle": ("user_id",),
    "dungeon_automation": ("user_id",),
}


def _sum(table: str, column: str) -> str:
    return f"COALESCE({table}.{column}, 0) + COALESCE(excluded.{column}, 0)"


def _maximum(table: str, column: str) -> str:
    return f"MAX(COALESCE({table}.{column}, 0), COALESCE(excluded.{column}, 0))"


def _latest(table: str, column: str) -> str:
    return (
        f"CASE WHEN {table}.{column} IS NULL THEN excluded.{column} "
        f"WHEN excluded.{column} IS NULL THEN {table}.{column} "
        f"WHEN {table}.{column} >= excluded.{column} THEN {table}.{column} "
        f"ELSE excluded.{column} END"
    )


def _earliest(table: str, column: str) -> str:
    return (
        f"CASE WHEN COALESCE({table}.{column}, '') = '' THEN excluded.{column} "
        f"WHEN COALESCE(excluded.{column}, '') = '' THEN {table}.{column} "
        f"WHEN {table}.{column} <= excluded.{column} THEN {table}.{column} "
        f"ELSE excluded.{column} END"
    )


def _keep(table: str, column: str) -> str:
    return f"CASE WHEN COALESCE({table}.{column}, '') = '' THEN excluded.{column} ELSE {table}.{column} END"


def _pair_of(table: str, driver: str, column: str, fallback: str) -> str:
    return (
        f"CASE WHEN COALESCE(excluded.{driver}, {fallback}) > COALESCE({table}.{driver}, {fallback}) THEN excluded.{column} "
        f"WHEN COALESCE(excluded.{driver}, {fallback}) < COALESCE({table}.{driver}, {fallback}) THEN {table}.{column} "
        f"WHEN COALESCE(excluded.{column}, 0) > COALESCE({table}.{column}, 0) THEN excluded.{column} "
        f"ELSE {table}.{column} END"
    )


def _json(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _merge_levels(primary: Any, secondary: Any) -> dict[str, int]:
    merged = {str(key): int(value) for key, value in _json(primary, {}).items()}
    for key, value in _json(secondary, {}).items():
        merged[str(key)] = max(merged.get(str(key), 0), int(value))
    return merged


def _merge_list(primary: Any, secondary: Any) -> list[str]:
    merged = [str(item) for item in _json(primary, [])]
    for item in _json(secondary, []):
        if str(item) not in merged:
            merged.append(str(item))
    return merged


class MergeRepository(BaseRepository):
    _lock = asyncio.Lock()

    async def preview(self, user_id: int) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table, columns in IDENTITY_COLUMNS.items():
            where = " OR ".join(f"{column} = ?" for column in columns)
            async with self._db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", (user_id,) * len(columns)) as cursor:
                row = await cursor.fetchone()
            if row and int(row[0]) > 0:
                counts[table] = int(row[0])
        return counts

    async def merge(self, primary_id: int, secondary_id: int) -> MergeReport:
        if primary_id == secondary_id:
            raise ValueError("Primary and secondary accounts must be different.")

        async with self._lock:
            connection = await aiosqlite.connect(self._db.path, timeout=30.0)
            connection.row_factory = aiosqlite.Row
            try:
                await connection.execute("PRAGMA busy_timeout = 30000;")
                await connection.execute("BEGIN IMMEDIATE;")
                report = await self._merge_all(connection, primary_id, secondary_id)
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise
            finally:
                await connection.close()
        return report

    async def _merge_all(self, connection: aiosqlite.Connection, primary_id: int, secondary_id: int) -> MergeReport:
        report = MergeReport(primary_id=primary_id, secondary_id=secondary_id)
        report.highlights = await self._highlights(connection, secondary_id)
        report.absorbed = await self._counts(connection, secondary_id)
        await self._merge_economy(connection, primary_id, secondary_id)
        await self._merge_gacha(connection, primary_id, secondary_id)
        await self._merge_mining(connection, primary_id, secondary_id)
        await self._merge_misc(connection, primary_id, secondary_id)
        await self._merge_activity(connection, primary_id, secondary_id)
        await self._merge_global_stats(connection, primary_id, secondary_id)
        await self._merge_waifu(connection, primary_id, secondary_id, report)
        await self._merge_dungeon(connection, primary_id, secondary_id, report)
        await self._sweep(connection, secondary_id)
        return report

    async def _counts(self, connection: aiosqlite.Connection, user_id: int) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table, columns in IDENTITY_COLUMNS.items():
            where = " OR ".join(f"{column} = ?" for column in columns)
            async with connection.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", (user_id,) * len(columns)) as cursor:
                row = await cursor.fetchone()
            if row and int(row[0]) > 0:
                counts[table] = int(row[0])
        return counts

    async def _highlights(self, connection: aiosqlite.Connection, user_id: int) -> dict[str, int]:
        queries = {
            "balance": "SELECT balance FROM economy_users WHERE user_id = ?",
            "interest": "SELECT unclaimed_interest FROM economy_users WHERE user_id = ?",
            "gacha_dust": "SELECT dust FROM gacha_users WHERE user_id = ?",
            "dungeon_gold": "SELECT gold FROM dungeon_users WHERE user_id = ?",
            "dungeon_dust": "SELECT dust FROM dungeon_users WHERE user_id = ?",
            "boss_coins": "SELECT boss_coins FROM dungeon_users WHERE user_id = ?",
            "waifu_value": "SELECT value FROM waifu_users WHERE user_id = ?",
        }
        highlights: dict[str, int] = {}
        for label, query in queries.items():
            async with connection.execute(query, (user_id,)) as cursor:
                row = await cursor.fetchone()
            if row and row[0]:
                highlights[label] = int(row[0])
        return highlights

    async def _upsert(
        self,
        connection: aiosqlite.Connection,
        table: str,
        conflict_keys: tuple[str, ...],
        insert_columns: tuple[str, ...],
        select: tuple[str, ...],
        updates: dict[str, str],
        params: tuple,
        where: str,
        conflict_where: Optional[str] = None,
    ) -> None:
        assignments = ", ".join(f"{column} = {expression}" for column, expression in updates.items())
        conflict = f"DO UPDATE SET {assignments}" if assignments else "DO NOTHING"
        if assignments and conflict_where:
            conflict += f" WHERE {conflict_where}"
        query = (
            f"INSERT INTO {table} ({', '.join(insert_columns)}) "
            f"SELECT {', '.join(select)} FROM {table} WHERE {where} "
            f"ON CONFLICT ({', '.join(conflict_keys)}) {conflict}"
        )
        await connection.execute(query, params)

    async def _merge_economy(self, connection: aiosqlite.Connection, primary_id: int, secondary_id: int) -> None:
        await self._upsert(
            connection,
            table="economy_users",
            conflict_keys=("user_id",),
            insert_columns=("user_id", "balance", "daily_streak", "last_daily", "active_job", "last_job_switch", "last_work", "crime_streak", "jail_until", "unclaimed_interest"),
            select=("?", "balance", "daily_streak", "last_daily", "active_job", "last_job_switch", "last_work", "crime_streak", "jail_until", "unclaimed_interest"),
            updates={
                "balance": _sum("economy_users", "balance"),
                "unclaimed_interest": _sum("economy_users", "unclaimed_interest"),
                "daily_streak": _maximum("economy_users", "daily_streak"),
                "crime_streak": _maximum("economy_users", "crime_streak"),
                "last_daily": _latest("economy_users", "last_daily"),
                "last_job_switch": _latest("economy_users", "last_job_switch"),
                "last_work": _latest("economy_users", "last_work"),
                "jail_until": _latest("economy_users", "jail_until"),
                "active_job": _keep("economy_users", "active_job"),
            },
            params=(primary_id, secondary_id),
            where="user_id = ?",
        )
        await self._upsert(
            connection,
            table="economy_jobs",
            conflict_keys=("user_id", "job_id"),
            insert_columns=("user_id", "job_id", "level", "xp"),
            select=("?", "job_id", "level", "xp"),
            updates={
                "level": _maximum("economy_jobs", "level"),
                "xp": _pair_of("economy_jobs", "level", "xp", "0"),
            },
            params=(primary_id, secondary_id),
            where="user_id = ?",
        )
        await connection.execute("UPDATE economy_balance_log SET user_id = ? WHERE user_id = ?", (primary_id, secondary_id))

    async def _merge_gacha(self, connection: aiosqlite.Connection, primary_id: int, secondary_id: int) -> None:
        await self._upsert(
            connection,
            table="gacha_users",
            conflict_keys=("user_id",),
            insert_columns=("user_id", "dust"),
            select=("?", "dust"),
            updates={"dust": _sum("gacha_users", "dust")},
            params=(primary_id, secondary_id),
            where="user_id = ?",
        )
        for table, unit_column in (("gacha_shards", "unit_id"), ("gacha_units_owned", "unit_id")):
            await self._upsert(
                connection,
                table=table,
                conflict_keys=("user_id", unit_column),
                insert_columns=("user_id", unit_column, "amount"),
                select=("?", unit_column, "amount"),
                updates={"amount": _sum(table, "amount")},
                params=(primary_id, secondary_id),
                where="user_id = ?",
            )

    async def _merge_mining(self, connection: aiosqlite.Connection, primary_id: int, secondary_id: int) -> None:
        await self._upsert(
            connection,
            table="mining_users",
            conflict_keys=("user_id",),
            insert_columns=("user_id", "xp", "level", "energy", "current_depth_id", "refills", "last_basic_pick"),
            select=("?", "xp", "level", "energy", "current_depth_id", "refills", "last_basic_pick"),
            updates={
                "level": _maximum("mining_users", "level"),
                "xp": _pair_of("mining_users", "level", "xp", "0"),
                "energy": "MIN(100, MAX(COALESCE(mining_users.energy, 0), COALESCE(excluded.energy, 0)))",
                "refills": _sum("mining_users", "refills"),
                "last_basic_pick": _latest("mining_users", "last_basic_pick"),
            },
            params=(primary_id, secondary_id),
            where="user_id = ?",
        )
        for table, item_column in (("mining_inv_materials", "material_id"), ("mining_inv_valuables", "valuable_id")):
            await self._upsert(
                connection,
                table=table,
                conflict_keys=("user_id", item_column),
                insert_columns=("user_id", item_column, "amount"),
                select=("?", item_column, "amount"),
                updates={"amount": _sum(table, "amount")},
                params=(primary_id, secondary_id),
                where="user_id = ?",
            )
        await connection.execute("UPDATE mining_inv_pickaxes SET is_equipped = 0 WHERE user_id = ?", (secondary_id,))
        await connection.execute(
            "UPDATE mining_inv_pickaxes SET is_equipped = 1 WHERE user_id = ? AND id = ("
            "SELECT id FROM mining_inv_pickaxes WHERE user_id = ? ORDER BY durability DESC, id LIMIT 1) "
            "AND NOT EXISTS (SELECT 1 FROM mining_inv_pickaxes WHERE user_id = ? AND is_equipped = 1)",
            (secondary_id, secondary_id, primary_id),
        )
        await connection.execute("UPDATE mining_inv_pickaxes SET user_id = ? WHERE user_id = ?", (primary_id, secondary_id))

    async def _merge_misc(self, connection: aiosqlite.Connection, primary_id: int, secondary_id: int) -> None:
        await self._upsert(
            connection,
            table="hacking_daily",
            conflict_keys=("user_id",),
            insert_columns=("user_id", "profit"),
            select=("?", "profit"),
            updates={"profit": _sum("hacking_daily", "profit")},
            params=(primary_id, secondary_id),
            where="user_id = ?",
        )
        await connection.execute("UPDATE horse_bets SET user_id = ? WHERE user_id = ?", (primary_id, secondary_id))
        await self._upsert(
            connection,
            table="quarantine",
            conflict_keys=("user_id",),
            insert_columns=("user_id", "reason"),
            select=("?", "reason"),
            updates={},
            params=(primary_id, secondary_id),
            where="user_id = ?",
        )
        await connection.execute("UPDATE reminders SET author_id = ? WHERE author_id = ?", (primary_id, secondary_id))
        await self._upsert(
            connection,
            table="reminder_subscribers",
            conflict_keys=("reminder_id", "user_id"),
            insert_columns=("reminder_id", "user_id"),
            select=("reminder_id", "?"),
            updates={},
            params=(primary_id, secondary_id),
            where="user_id = ?",
        )

    async def _merge_activity(self, connection: aiosqlite.Connection, primary_id: int, secondary_id: int) -> None:
        await self._upsert(
            connection,
            table="user_stats",
            conflict_keys=("guild_id", "user_id"),
            insert_columns=("guild_id", "user_id", "messages", "xp", "words", "chars", "attachments", "emojis"),
            select=("guild_id", "?", "messages", "xp", "words", "chars", "attachments", "emojis"),
            updates={
                "messages": _sum("user_stats", "messages"),
                "xp": _sum("user_stats", "xp"),
                "words": _sum("user_stats", "words"),
                "chars": _sum("user_stats", "chars"),
                "attachments": _sum("user_stats", "attachments"),
                "emojis": _sum("user_stats", "emojis"),
            },
            params=(primary_id, secondary_id),
            where="user_id = ?",
        )

    async def _merge_global_stats(self, connection: aiosqlite.Connection, primary_id: int, secondary_id: int) -> None:
        columns = ("user_id", *GlobalStatsRepository._SUM_COLUMNS, *GlobalStatsRepository._MAX_COLUMNS)
        updates = {column: _sum("user_global_stats", column) for column in GlobalStatsRepository._SUM_COLUMNS}
        updates.update({column: _maximum("user_global_stats", column) for column in GlobalStatsRepository._MAX_COLUMNS})
        await self._upsert(
            connection,
            table="user_global_stats",
            conflict_keys=("user_id",),
            insert_columns=columns,
            select=("?", *columns[1:]),
            updates=updates,
            params=(primary_id, secondary_id),
            where="user_id = ?",
        )

    async def _merge_waifu(self, connection: aiosqlite.Connection, primary_id: int, secondary_id: int, report: MergeReport) -> None:
        async with connection.execute("SELECT * FROM waifu_users WHERE user_id = ?", (primary_id,)) as cursor:
            primary = await cursor.fetchone()
        async with connection.execute("SELECT * FROM waifu_users WHERE user_id = ?", (secondary_id,)) as cursor:
            secondary = await cursor.fetchone()

        if secondary:
            inherited = secondary["claim"]
            if inherited in (None, primary_id, secondary_id):
                inherited = None
            merged_claim = primary["claim"] if primary else None
            if merged_claim in (None, secondary_id):
                merged_claim = inherited
            elif inherited is not None:
                report.notes.append("La cuenta absorbida tenía una waifu reclamada que no se ha podido traspasar porque la principal ya tenía otra.")
            value = int(primary["value"] if primary else 0) + int(secondary["value"])
            pronoun = primary["pronoun"] if primary else secondary["pronoun"]
            if primary:
                await connection.execute(
                    "UPDATE waifu_users SET value = ?, pronoun = ?, claim = ? WHERE user_id = ?",
                    (value, pronoun, merged_claim, primary_id),
                )
            else:
                await connection.execute(
                    "INSERT INTO waifu_users (user_id, pronoun, value, claim) VALUES (?, ?, ?, ?)",
                    (primary_id, pronoun, value, merged_claim),
                )
            await connection.execute("DELETE FROM waifu_users WHERE user_id = ?", (secondary_id,))

        await connection.execute(
            "UPDATE waifu_users SET claim = CASE WHEN EXISTS(SELECT 1 FROM waifu_users WHERE claim = ?) THEN NULL ELSE ? END "
            "WHERE claim = ? AND user_id != ?",
            (primary_id, primary_id, secondary_id, primary_id),
        )

        await self._upsert(
            connection,
            table="waifu_gifts",
            conflict_keys=("user_id", "item_name"),
            insert_columns=("user_id", "item_name", "amount"),
            select=("?", "item_name", "amount"),
            updates={"amount": _sum("waifu_gifts", "amount")},
            params=(primary_id, secondary_id),
            where="user_id = ?",
        )
        await connection.execute(
            "INSERT OR IGNORE INTO waifu_blocks (blocker_id, blocked_id) "
            "SELECT CASE WHEN blocker_id = ? THEN ? ELSE blocker_id END, CASE WHEN blocked_id = ? THEN ? ELSE blocked_id END "
            "FROM waifu_blocks WHERE blocker_id = ? OR blocked_id = ?",
            (secondary_id, primary_id, secondary_id, primary_id, secondary_id, secondary_id),
        )
        await connection.execute(
            "DELETE FROM waifu_blocks WHERE (blocker_id = ? OR blocked_id = ?) AND blocker_id = blocked_id",
            (primary_id, primary_id),
        )

    async def _merge_dungeon(self, connection: aiosqlite.Connection, primary_id: int, secondary_id: int, report: MergeReport) -> None:
        async with connection.execute("SELECT upgrades, shifts FROM dungeon_users WHERE user_id = ?", (primary_id,)) as cursor:
            primary_json = await cursor.fetchone()
        async with connection.execute("SELECT upgrades, shifts FROM dungeon_users WHERE user_id = ?", (secondary_id,)) as cursor:
            secondary_json = await cursor.fetchone()

        await self._upsert(
            connection,
            table="dungeon_users",
            conflict_keys=("user_id",),
            insert_columns=(
                "user_id", "floor", "highest_floor", "floor_kills", "auto_advance", "level", "xp", "gold", "hp", "max_hp",
                "recovering", "hp_at", "energy", "max_energy", "potions", "active_skill", "dust", "boss_coins", "boss_tier",
                "last_boss_at", "last_boss_floor", "last_alt_at", "conversion_date", "conversion_used", "training_enabled",
                "training_since", "runs", "prestige_anchor",
            ),
            select=(
                "?", "floor", "highest_floor", "floor_kills", "auto_advance", "level", "xp", "gold", "hp", "max_hp",
                "recovering", "hp_at", "energy", "max_energy", "potions", "active_skill", "dust", "boss_coins", "boss_tier",
                "last_boss_at", "last_boss_floor", "last_alt_at", "conversion_date", "conversion_used", "training_enabled",
                "training_since", "runs", "prestige_anchor",
            ),
            updates={
                "floor": _pair_of("dungeon_users", "highest_floor", "floor", "0"),
                "floor_kills": _pair_of("dungeon_users", "highest_floor", "floor_kills", "0"),
                "highest_floor": _maximum("dungeon_users", "highest_floor"),
                "auto_advance": _maximum("dungeon_users", "auto_advance"),
                "level": _maximum("dungeon_users", "level"),
                "xp": _sum("dungeon_users", "xp"),
                "gold": _sum("dungeon_users", "gold"),
                "hp": _maximum("dungeon_users", "hp"),
                "max_hp": _maximum("dungeon_users", "max_hp"),
                "recovering": _maximum("dungeon_users", "recovering"),
                "hp_at": _latest("dungeon_users", "hp_at"),
                "energy": _maximum("dungeon_users", "energy"),
                "max_energy": _maximum("dungeon_users", "max_energy"),
                "potions": _sum("dungeon_users", "potions"),
                "active_skill": _keep("dungeon_users", "active_skill"),
                "dust": _sum("dungeon_users", "dust"),
                "boss_coins": _sum("dungeon_users", "boss_coins"),
                "boss_tier": _maximum("dungeon_users", "boss_tier"),
                "last_boss_at": _latest("dungeon_users", "last_boss_at"),
                "last_boss_floor": _pair_of("dungeon_users", "last_boss_at", "last_boss_floor", "''"),
                "last_alt_at": _latest("dungeon_users", "last_alt_at"),
                "conversion_date": _latest("dungeon_users", "conversion_date"),
                "conversion_used": (
                    "CASE WHEN COALESCE(dungeon_users.conversion_date, '') = COALESCE(excluded.conversion_date, '') "
                    "THEN COALESCE(dungeon_users.conversion_used, 0) + COALESCE(excluded.conversion_used, 0) "
                    "WHEN COALESCE(excluded.conversion_date, '') > COALESCE(dungeon_users.conversion_date, '') THEN excluded.conversion_used "
                    "ELSE dungeon_users.conversion_used END"
                ),
                "training_enabled": _maximum("dungeon_users", "training_enabled"),
                "training_since": (
                    "CASE WHEN COALESCE(dungeon_users.training_enabled, 0) = 1 AND COALESCE(excluded.training_enabled, 0) = 1 "
                    f"THEN {_earliest('dungeon_users', 'training_since')} "
                    "WHEN COALESCE(dungeon_users.training_enabled, 0) = 1 THEN dungeon_users.training_since "
                    "WHEN COALESCE(excluded.training_enabled, 0) = 1 THEN excluded.training_since "
                    "ELSE dungeon_users.training_since END"
                ),
                "runs": _sum("dungeon_users", "runs"),
                "prestige_anchor": _maximum("dungeon_users", "prestige_anchor"),
            },
            params=(primary_id, secondary_id),
            where="user_id = ?",
        )

        if secondary_json:
            upgrades = _merge_levels(primary_json["upgrades"] if primary_json else None, secondary_json["upgrades"])
            shifts = _merge_list(primary_json["shifts"] if primary_json else None, secondary_json["shifts"])
            await connection.execute(
                "INSERT INTO dungeon_users (user_id, upgrades, shifts) VALUES (?, ?, ?) "
                "ON CONFLICT (user_id) DO UPDATE SET upgrades = excluded.upgrades, shifts = excluded.shifts",
                (primary_id, json.dumps(upgrades), json.dumps(shifts)),
            )

        await connection.execute(
            "UPDATE dungeon_inventory SET is_equipped = 0 WHERE user_id = ? AND is_equipped = 1 "
            "AND slot IN (SELECT slot FROM dungeon_inventory WHERE user_id = ? AND is_equipped = 1)",
            (secondary_id, primary_id),
        )
        await connection.execute("UPDATE dungeon_inventory SET user_id = ? WHERE user_id = ?", (primary_id, secondary_id))

        for table in ("dungeon_mutations", "dungeon_echoes"):
            column = "mutation_id" if table == "dungeon_mutations" else "echo_id"
            await self._upsert(
                connection,
                table=table,
                conflict_keys=("user_id", column),
                insert_columns=("user_id", column, "level"),
                select=("?", column, "level"),
                updates={"level": _maximum(table, "level")},
                params=(primary_id, secondary_id),
                where="user_id = ?",
            )

        async with connection.execute(
            "SELECT EXISTS(SELECT 1 FROM dungeon_cosmetics WHERE user_id = ? AND equipped = 1)", (primary_id,)
        ) as cursor:
            row = await cursor.fetchone()
        equipped_conflict = bool(row[0]) if row else False
        if equipped_conflict:
            report.notes.append("La cuenta absorbida tenía cosméticos equipados y se ha conservado la selección de la principal.")
        await connection.execute(
            f"INSERT OR IGNORE INTO dungeon_cosmetics (user_id, cosmetic_id, equipped) "
            f"SELECT ?, cosmetic_id, {'0' if equipped_conflict else 'equipped'} FROM dungeon_cosmetics WHERE user_id = ?",
            (primary_id, secondary_id),
        )
        await connection.execute("UPDATE dungeon_log SET user_id = ? WHERE user_id = ?", (primary_id, secondary_id))

        await self._upsert(
            connection,
            table="dungeon_last_battle",
            conflict_keys=("user_id",),
            insert_columns=("user_id", "stage", "floor", "enemy", "log", "created_at"),
            select=("?", "stage", "floor", "enemy", "log", "created_at"),
            updates={
                "stage": "excluded.stage",
                "floor": "excluded.floor",
                "enemy": "excluded.enemy",
                "log": "excluded.log",
                "created_at": "excluded.created_at",
            },
            params=(primary_id, secondary_id),
            where="user_id = ?",
            conflict_where="COALESCE(excluded.created_at, '') > COALESCE(dungeon_last_battle.created_at, '')",
        )

        async with connection.execute("SELECT COUNT(*) FROM dungeon_active_fight WHERE user_id = ? AND NOT EXISTS(SELECT 1 FROM dungeon_active_fight WHERE user_id = ?)", (secondary_id, primary_id)) as cursor:
            row = await cursor.fetchone()
        moved_fight = bool(row[0]) if row else False
        if moved_fight:
            await connection.execute("UPDATE dungeon_active_fight SET user_id = ? WHERE user_id = ?", (primary_id, secondary_id))
            report.notes.append("Se ha traspasado el combate activo de la cuenta absorbida a la principal.")
        elif await self._exists(connection, "dungeon_active_fight", secondary_id):
            report.notes.append("La cuenta absorbida tenía un combate activo que se ha descartado porque la principal ya estaba en combate.")

        await self._upsert(
            connection,
            table="dungeon_automation",
            conflict_keys=("user_id",),
            insert_columns=("user_id", "enabled", "sims", "last_tick", "last_report"),
            select=("?", "enabled", "sims", "last_tick", "last_report"),
            updates={
                "enabled": _maximum("dungeon_automation", "enabled"),
                "sims": _sum("dungeon_automation", "sims"),
                "last_tick": _latest("dungeon_automation", "last_tick"),
                "last_report": (
                    "CASE WHEN COALESCE(excluded.last_tick, '') > COALESCE(dungeon_automation.last_tick, '') "
                    "THEN excluded.last_report ELSE dungeon_automation.last_report END"
                ),
            },
            params=(primary_id, secondary_id),
            where="user_id = ?",
        )

    async def _exists(self, connection: aiosqlite.Connection, table: str, user_id: int) -> bool:
        async with connection.execute(f"SELECT EXISTS(SELECT 1 FROM {table} WHERE user_id = ?)", (user_id,)) as cursor:
            row = await cursor.fetchone()
        return bool(row[0]) if row else False

    async def _sweep(self, connection: aiosqlite.Connection, secondary_id: int) -> None:
        for table, columns in IDENTITY_COLUMNS.items():
            where = " OR ".join(f"{column} = ?" for column in columns)
            await connection.execute(f"DELETE FROM {table} WHERE {where}", (secondary_id,) * len(columns))
