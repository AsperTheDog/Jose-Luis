import datetime
import json
import os
import random
from sqlite3 import Row
from typing import Optional, Dict, Any, List

import aiosqlite

DEFAULT_CONFIG = {
        "admin_channel_id": 0,
        "log_channel_id": 0,
        "death_channel_id": 0,
        "death_grace_seconds": 60.0,
        "global_cooldown_seconds": 600.0,
        "event_mensajes": True,
        "event_miembros": True,
        "event_moderacion": True,
        "event_canales": True,
    }

class DBManager:
    def __init__(self):
        self.db_path = "bot_data.db"
        self.db: aiosqlite.Connection = None

        self.job_registry: Dict[str, Dict[str, Any]] = self._load_json("jobs.json")

    async def close(self):
        if self.db:
            await self.db.close()

    async def start_db(self):
        self.db = await aiosqlite.connect(self.db_path, timeout=30.0)
        await self.db.execute("PRAGMA journal_mode=WAL;")
        await self.db.execute("PRAGMA busy_timeout=5000;")
        await self.init_tables()

    @staticmethod
    def _load_json(path: str) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON file at {path}: {e}.")
        return None

    async def init_tables(self) -> None:
        folder_path = "queries/init"
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        sql_files = sorted([f for f in os.listdir(folder_path) if f.endswith(".sql")])
        for file_name in sql_files:
            file_path = os.path.join(folder_path, file_name)
            with open(file_path, "r", encoding="utf-8") as f:
                sql_script = f.read()
            await self.db.executescript(sql_script)
        await self.db.commit()

    async def get_user_global_stats(self, user_id: int) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM user_global_stats WHERE user_id = ?;"
        self.db.row_factory = aiosqlite.Row
        async with self.db.execute(query, (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def increment_stat(self, user_id: int, column_name: str, amount: int = 1) -> None:
        query = f"""INSERT INTO user_global_stats (user_id, {column_name})
                    VALUES (?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        {column_name} = {column_name} + excluded.{column_name}; """
        await self.db.execute(query, (user_id, amount))
        await self.db.commit()

    async def update_max_stat(self, user_id: int, column_name: str, value: int) -> None:
        query = f"""INSERT INTO user_global_stats (user_id, {column_name})
                    VALUES (?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        {column_name} = MAX({column_name}, excluded.{column_name});"""
        await self.db.execute(query, (user_id, value))
        await self.db.commit()

    async def ensure_guild_exists(self, guild_id: int) -> None:
        query = """
                INSERT OR IGNORE INTO guild_config (
                    guild_id, admin_channel_id, log_channel_id, death_channel_id,
                    death_grace_seconds, global_cooldown_seconds,
                   event_mensajes, event_miembros, event_moderacion, event_canales
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
        params = (
            guild_id,
            DEFAULT_CONFIG["admin_channel_id"],
            DEFAULT_CONFIG["log_channel_id"],
            DEFAULT_CONFIG["death_channel_id"],
            DEFAULT_CONFIG["death_grace_seconds"],
            DEFAULT_CONFIG["global_cooldown_seconds"],
            int(DEFAULT_CONFIG["event_mensajes"]),
            int(DEFAULT_CONFIG["event_miembros"]),
            int(DEFAULT_CONFIG["event_moderacion"]),
            int(DEFAULT_CONFIG["event_canales"]),
        )

        await self.db.execute(query, params)
        await self.db.commit()

    async def get_job_perk(self, user_job_id: str, perk_name: str, default: float, user_id: Optional[int] = None) -> float:
        def calc_level(job_level: float, val: float) -> float:
            if perk_name == "job_penalty":
                return val
            if val < 0.0:
                return max((-val) * 0.2, (-val) - (-val) * 0.05 * job_level)
            return val + val * 0.1 * job_level

        level = 1.0
        if user_id:
            async with self.db.execute("SELECT level FROM economy_jobs WHERE user_id = ? AND job_id = ?", (user_id, user_job_id)) as cursor:
                row = await cursor.fetchone()
                if row and row[0] is not None:
                    level = float(row[0])

        perks = self.job_registry.get(user_job_id, {}).get("perks", {})
        raw_val = perks.get(perk_name)

        if raw_val is not None:
            try:
                return calc_level(level, float(raw_val))
            except (ValueError, TypeError):
                pass

        return calc_level(level, default)

    async def get_user_active_job(self, user_id: int) -> str | None:
        async with self.db.execute("SELECT active_job FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return row[0]

    async def get_user_job_perk(self, user_id: int, perk_name: str, default: float) -> float:
        job = await self.get_user_active_job(user_id)
        if job is None:
            return default
        return await self.get_job_perk(job, perk_name, default, user_id)

    async def global_fetch_user_stats(self, user_id: int) -> dict:
        self.db.row_factory = aiosqlite.Row
        async with self.db.execute("SELECT * FROM user_global_stats WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else {}

    async def global_get_random_phrase(self, category: str, tag: Optional[str] = None, add_enter: bool = True) -> str:
        async with self.db.execute("SELECT phrase FROM economy_phrases WHERE category = ? AND (tag IS NULL OR tag = '') ORDER BY RANDOM() LIMIT 1", (category,)) as cursor:
            no_tag_row = await cursor.fetchone()
            no_tag_phrase = no_tag_row[0] if no_tag_row else None

        phrases = [no_tag_phrase]

        if tag:
            async with self.db.execute("SELECT phrase FROM economy_phrases WHERE category = ? AND tag = ? ORDER BY RANDOM() LIMIT 1", (category, tag)) as cursor:
                tagged_row = await cursor.fetchone()
                if tagged_row:
                    if no_tag_phrase is None:
                        return tagged_row[0]
                    phrases.append(tagged_row[0])

        choice = random.choice(phrases)
        if choice is None:
            return ""
        return choice + ("\n" if add_enter else "")

    async def economy_ensure_user(self, user_id: int):
        await self.db.execute("INSERT OR IGNORE INTO economy_users (user_id) VALUES (?)", (user_id,))

    async def economy_get_balance(self, user_id: int) -> int:
        await self.economy_ensure_user(user_id)
        async with self.db.execute("SELECT balance FROM economy_users WHERE user_id = ?", (user_id,)) as c:
            return (await c.fetchone())[0]

    async def economy_update_balance(self, user_id: int, amount: int):
        await self.economy_ensure_user(user_id)
        await self.db.execute("UPDATE economy_users SET balance = MAX(0, balance + ?) WHERE user_id = ?", (int(amount), user_id))
        await self.db.commit()

    async def economy_get_user_data(self, user_id: int) -> dict:
        await self.economy_ensure_user(user_id)
        self.db.row_factory = aiosqlite.Row
        async with self.db.execute("SELECT * FROM economy_users WHERE user_id = ?", (user_id,)) as c:
            row = await c.fetchone()
            return dict(row) if row else {}

    async def economy_get_job_data(self, user_id: int, job_id: str) -> dict:
        await self.economy_ensure_user(user_id)
        self.db.row_factory = aiosqlite.Row
        async with self.db.execute("SELECT * FROM economy_jobs WHERE user_id = ? AND job_id = ?", (user_id, job_id)) as c:
            row = await c.fetchone()
            return dict(row) if row else {"level": 1, "xp": 0}

    async def economy_crime_success(self, user_id: int, reward: int) -> None:
        await self.economy_ensure_user(user_id)
        await self.db.execute("UPDATE economy_users SET balance = MAX(0, balance + ?), crime_streak = crime_streak + 1 WHERE user_id = ?", (int(reward), user_id))
        await self.db.commit()

    async def economy_crime_failure(self, user_id: int, penalty: int, jail_until_str: str) -> None:
        await self.economy_ensure_user(user_id)
        await self.db.execute("UPDATE economy_users SET balance = MAX(0, balance - ?), crime_streak = 0, jail_until = ? WHERE user_id = ?", (int(penalty), jail_until_str, user_id))
        await self.db.commit()

    async def economy_transfer_balance(self, sender_id: int, recipient_id: int, amount: int) -> None:
        await self.economy_ensure_user(recipient_id)
        await self.db.execute("UPDATE economy_users SET balance = MAX(0, balance - ?) WHERE user_id = ?", (int(amount), sender_id))
        await self.db.execute("UPDATE economy_users SET balance = MAX(0, balance + ?) WHERE user_id = ?", (int(amount), recipient_id))
        await self.db.commit()

    async def economy_daily_claim(self, user_id: int, payout: int, new_streak: int, timestamp_iso: str) -> None:
        await self.db.execute("UPDATE economy_users SET balance = MAX(0, balance + ?), daily_streak = ?, last_daily = ? WHERE user_id = ?", (int(payout), new_streak, timestamp_iso, user_id))
        await self.db.commit()

    async def economy_add_phrase(self, phrase: str, category: str, tag: str) -> None:
        await self.db.execute("INSERT INTO economy_phrases (phrase, category, tag) VALUES (?, ?, ?)", (phrase, category, tag))
        await self.db.commit()

    async def economy_get_balance_log(self, user_id: int, limit: int = 10) -> list[dict]:
        await self.economy_ensure_user(user_id)
        self.db.row_factory = aiosqlite.Row
        async with self.db.execute(
            "SELECT delta, prev_balance, new_balance, created_at FROM economy_balance_log "
            "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, int(limit)),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def economy_update_work_and_job(self, user_id: int, salary: int, last_work_iso: str, job_id: str, level: int, new_xp: int) -> None:
        await self.db.execute("UPDATE economy_users SET balance = MAX(0, balance + ?), last_work = ? WHERE user_id = ?", (int(salary), last_work_iso, user_id))
        await self.db.execute("INSERT OR REPLACE INTO economy_jobs (user_id, job_id, level, xp) VALUES (?, ?, ?, ?)", (user_id, job_id, level, new_xp))
        await self.db.commit()

    async def economy_update_active_job(self, user_id: int, selected_job_id: str, last_job_switch_iso: str) -> None:
        await self.db.execute("UPDATE economy_users SET active_job = ?, last_job_switch = ? WHERE user_id = ?", (selected_job_id, last_job_switch_iso, user_id))
        await self.db.commit()

    async def economy_claim_interest(self, user_id: int) -> int:
        async with self.db.execute("SELECT unclaimed_interest FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return 0

        unclaimed = row[0]
        if unclaimed <= 0:
            return 0

        await self.db.execute("UPDATE economy_users SET balance = MAX(0, balance + ?), unclaimed_interest = 0 WHERE user_id = ?", (int(unclaimed), user_id))
        await self.db.commit()

        return unclaimed

    async def economy_process_slots_bet(self, user_id: int, bet_amount: int, net_change: int, default_balance: int = 1000) -> tuple[bool, int]:
        async with self.db.execute("SELECT balance FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            balance = default_balance
            await self.db.execute("INSERT INTO economy_users (user_id, balance) VALUES (?, ?)", (user_id, balance))
        else:
            balance = row[0]

        if balance < bet_amount:
            return False, balance

        new_balance = max(0, balance + net_change)
        await self.db.execute("UPDATE economy_users SET balance = ? WHERE user_id = ?", (int(new_balance), user_id))
        await self.db.commit()

        return True, new_balance

    async def economy_get_active_users(self) -> list[tuple[int, int, str | None, int]]:
        async with self.db.execute("SELECT user_id, balance, active_job, unclaimed_interest FROM economy_users WHERE balance > 0") as cursor:
            return await cursor.fetchall()

    async def economy_add_unclaimed_interest(self, user_id: int, daily_interest: int) -> None:
        if daily_interest > 0:
            await self.db.execute("UPDATE economy_users SET unclaimed_interest = unclaimed_interest + ? WHERE user_id = ?", (int(daily_interest), user_id))
            await self.db.commit()

    async def phrases_pick_random(self, category: str, history_ratio: float) -> List[str] | None:
        async with self.db.execute("SELECT content FROM text_lists WHERE category = ?", (category,)) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            return None

        candidates = [row[0] for row in rows]
        return candidates

    async def phrases_add_new(self, category: str, content: str) -> bool:
        try:
            await self.db.execute("INSERT INTO text_lists (category, content) VALUES (?, ?)", (category, content))
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def phrases_remove(self, category: str, content: str) -> bool:
        cursor = await self.db.execute("DELETE FROM text_lists WHERE category = ? AND content = ?", (category, content))
        deleted = cursor.rowcount > 0
        await self.db.commit()
        return deleted

    async def mining_ensure_user(self, user_id: int) -> None:
        await self.db.execute("INSERT OR IGNORE INTO mining_users (user_id) VALUES (?)", (user_id,), )
        await self.db.commit()

    async def mining_change_depth(self, user_id: int, selected_level: str) -> None:
        await self.mining_ensure_user(user_id)
        await self.db.execute("UPDATE mining_users SET current_depth_id = ? WHERE user_id = ?", (selected_level, user_id))
        await self.db.commit()

    async def mining_get_user_status(self, user_id: int) -> tuple[Any, Any, Any, Any, Row | None]:
        await self.mining_ensure_user(user_id)
        async with self.db.execute("SELECT energy, current_depth_id, xp, level FROM mining_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            energy, depth_id, current_xp, user_lvl = row
        async with self.db.execute("SELECT id, pickaxe_id, durability FROM mining_inv_pickaxes WHERE user_id = ? AND is_equipped = 1",(user_id,)) as cursor:
            equipped_pick = await cursor.fetchone()

        return energy, depth_id, current_xp, user_lvl, equipped_pick

    async def mining_deduct_energy(self, user_id: int, energy_cost: int) -> None:
        await self.mining_ensure_user(user_id)
        await self.db.execute("UPDATE mining_users SET energy = energy - ? WHERE user_id = ?", (energy_cost, user_id))
        await self.db.commit()

    async def mining_record_mine_action(self, user_id: int, energy_cost: int, db_pick_id: int, new_durability: int, dropped_material: str, total_yield: int, new_xp: int, new_level: int) -> None:
        await self.mining_ensure_user(user_id)
        await self.db.execute("UPDATE mining_users SET energy = energy - ?, xp = ?, level = ? WHERE user_id = ?", (energy_cost, new_xp, new_level, user_id))

        if new_durability <= 0:
            await self.db.execute("DELETE FROM mining_inv_pickaxes WHERE id = ?", (db_pick_id,))
        else:
            await self.db.execute("UPDATE mining_inv_pickaxes SET durability = ? WHERE id = ?",(new_durability, db_pick_id))

        await self.db.execute("""INSERT INTO mining_inv_materials (user_id, material_id, amount)
                                 VALUES (?, ?, ?)
                                 ON CONFLICT(user_id, material_id) DO UPDATE SET amount = amount + ?
                                 """, (user_id, dropped_material, total_yield, total_yield), )

        await self.db.commit()

    async def mining_get_refill_data(self, user_id: int) -> tuple[Any, Any, Any, Any]:
        await self.mining_ensure_user(user_id)
        async with self.db.execute("SELECT energy, level, refills FROM mining_users WHERE user_id = ?", (user_id,)) as cursor:
            energy, user_lvl, refills = await cursor.fetchone()

        async with self.db.execute("SELECT balance FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            balance = (await cursor.fetchone())[0]

        return energy, user_lvl, refills, balance

    async def mining_apply_refill(self, user_id: int, new_energy: int, new_balance: int) -> None:
        await self.db.execute("UPDATE mining_users SET energy = ?, refills = refills + 1 WHERE user_id = ?", (new_energy, user_id))
        await self.db.execute("UPDATE economy_users SET balance = ? WHERE user_id = ?", (int(new_balance), user_id))
        await self.db.commit()

    async def mining_get_last_basic_pick(self, user_id: int) -> datetime.datetime | None:
        async with self.db.execute("SELECT last_basic_pick FROM mining_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                return datetime.datetime.fromisoformat(row[0])
            return None

    async def mining_claim_basic_pickaxe(self, user_id: int, pick_id: str, max_dur: int):
        await self.mining_ensure_user(user_id)
        async with self.db.execute("SELECT COUNT(*) FROM mining_inv_pickaxes WHERE user_id = ? AND is_equipped = 1", (user_id,)) as cursor:
            row = await cursor.fetchone()
            has_equipped = row[0] > 0 if row else False

        is_equipped = 0 if has_equipped else 1

        now = datetime.datetime.now()
        await self.db.execute("UPDATE mining_users SET last_basic_pick = ? WHERE user_id = ?", (now.isoformat(), user_id))
        await self.db.execute("INSERT INTO mining_inv_pickaxes (user_id, pickaxe_id, durability, is_equipped) VALUES (?, ?, ?, ?)", (user_id, pick_id, max_dur, is_equipped))
        await self.db.commit()

    async def mining_get_user_pickaxes(self, user_id: int) -> list[tuple]:
        await self.mining_ensure_user(user_id)
        async with self.db.execute("SELECT id, pickaxe_id, durability, is_equipped FROM mining_inv_pickaxes WHERE user_id = ? ORDER BY id", (user_id,)) as cursor:
            return await cursor.fetchall()

    async def mining_equip_pickaxe(self, user_id: int, target_db_id: int) -> None:
        await self.mining_ensure_user(user_id)
        await self.db.execute("UPDATE mining_inv_pickaxes SET is_equipped = 0 WHERE user_id = ?", (user_id,), )
        await self.db.execute("UPDATE mining_inv_pickaxes SET is_equipped = 1 WHERE id = ?", (target_db_id,), )
        await self.db.commit()

    async def mining_get_user_inventory(self, user_id: int) -> dict[str, int]:
        await self.mining_ensure_user(user_id)
        async with self.db.execute("SELECT material_id, amount FROM mining_inv_materials WHERE user_id = ?", (user_id,)) as cursor:
            return dict(await cursor.fetchall())

    async def mining_craft_item(self, user_id: int, ingredients: dict[str, int], result_id: str, item_type: str, amount: int, max_durability: int | None = None) -> None:
        await self.mining_ensure_user(user_id)
        for mat_id, req_amount in ingredients.items():
            await self.db.execute("UPDATE mining_inv_materials SET amount = amount - ? WHERE user_id = ? AND material_id = ?", (req_amount * amount, user_id, mat_id))

        await self.db.execute("DELETE FROM mining_inv_materials WHERE amount <= 0 AND user_id = ?", (user_id,))


        if item_type == "pickaxe":
            for _ in range(amount):
                await self.db.execute("INSERT INTO mining_inv_pickaxes (user_id, pickaxe_id, durability) VALUES (?, ?, ?)", (user_id, result_id, max_durability))
        else:
            await self.db.execute("""INSERT INTO mining_inv_valuables (user_id, valuable_id, amount)
                                        VALUES (?, ?, ?)
                                        ON CONFLICT(user_id, valuable_id) DO UPDATE SET amount = amount + ?
                                  """, (user_id, result_id, amount, amount))
        await self.db.commit()

    async def mining_get_user_valuables(self, user_id: int) -> list[tuple[str, int]]:
        async with self.db.execute("SELECT valuable_id, amount FROM mining_inv_valuables WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchall()

    async def mining_sell_all_valuables(self, user_id: int, total_earnings: int) -> None:
        await self.db.execute("DELETE FROM mining_inv_valuables WHERE user_id = ?", (user_id,))
        await self.db.execute("UPDATE economy_users SET balance = MAX(0, balance + ?) WHERE user_id = ?", (int(total_earnings), user_id))
        await self.db.commit()

    async def mining_get_full_profile(self, user_id: int) -> dict[str, Any]:
        async with self.db.execute("SELECT energy, current_depth_id FROM mining_users WHERE user_id = ?", (user_id,)) as cursor:
            user_row = await cursor.fetchone()

        async with self.db.execute("SELECT material_id, amount FROM mining_inv_materials WHERE user_id = ?", (user_id,)) as cursor:
            materials = await cursor.fetchall()

        async with self.db.execute("SELECT valuable_id, amount FROM mining_inv_valuables WHERE user_id = ?", (user_id,)) as cursor:
            valuables = await cursor.fetchall()

        async with self.db.execute("SELECT pickaxe_id, durability FROM mining_inv_pickaxes WHERE user_id = ? AND is_equipped = 1", (user_id,)) as cursor:
            equipped_pick = await cursor.fetchone()

        return {
            "user": user_row,
            "materials": dict(materials),
            "valuables": dict(valuables),
            "equipped_pick": equipped_pick,
        }

    async def mining_reset_all_energy(self) -> None:
        await self.db.execute("UPDATE mining_users SET energy = 100, refills = 0")
        await self.db.commit()

    async def twitch_get_tracked_streamers(self) -> list[str]:
        async with self.db.execute("SELECT DISTINCT twitch_username FROM tracked_streamers") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def twitch_get_streamer_destinations(self, twitch_user: str) -> list[tuple[int, str | None, int]]:
        async with self.db.execute("SELECT channel_id, kick_username, everyone FROM tracked_streamers WHERE twitch_username = ?", (twitch_user,)) as cursor:
            return await cursor.fetchall()

    async def twitch_add_or_update_tracked_streamer(self, guild_id: int, channel_id: int, twitch_user: str, kick_user: str | None, at_everyone: int) -> None:
        await self.db.execute("""INSERT INTO tracked_streamers (guild_id, channel_id, twitch_username, kick_username, everyone)
                                 VALUES (?, ?, ?, ?, ?)
                                 ON CONFLICT(guild_id, twitch_username) 
                                 DO UPDATE SET channel_id = excluded.channel_id, kick_username = excluded.kick_username
                                 """, (guild_id, channel_id, twitch_user, kick_user, at_everyone), )
        await self.db.commit()

    async def twitch_remove_tracked_streamer(self, guild_id: int, twitch_user: str) -> bool:
        async with self.db.execute("DELETE FROM tracked_streamers WHERE guild_id = ? AND twitch_username = ?", (guild_id, twitch_user)) as cursor:
            await self.db.commit()
            return cursor.rowcount > 0

    async def twitch_get_guild_tracked_streamers(self, guild_id: int) -> list[tuple[str, str | None, int]]:
        async with self.db.execute("SELECT twitch_username, kick_username, channel_id FROM tracked_streamers WHERE guild_id = ?", (guild_id,)) as cursor:
            return await cursor.fetchall()

    async def activity_update_user_stats(self, guild_id: int, user_id: int, xp_gained: int, word_count: int, char_count: int, attachment_count: int, emoji_count: int, ) -> None:
        await self.db.execute("""INSERT INTO user_stats (guild_id, user_id, messages, xp, words, chars, attachments, emojis) 
                                 VALUES (?, ?, 1, ?, ?, ?, ?, ?) ON CONFLICT(guild_id, user_id) DO UPDATE SET messages = messages + 1, xp = xp + excluded.xp,
                                                         words = words + excluded.words, chars = chars + excluded.chars,
                                                         attachments = attachments + excluded.attachments, emojis = emojis + excluded.emojis
            """, (guild_id, user_id, xp_gained, word_count, char_count, attachment_count, emoji_count))
        await self.db.commit()

    async def activity_get_user_stats(self, guild_id: int, user_id: int) -> tuple | None:
        async with self.db.execute("SELECT messages, xp, words, chars, attachments, emojis FROM user_stats WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cursor:
            return await cursor.fetchone()

    async def activity_get_top_users_by_category(self, guild_id: int, category: str) -> list[tuple[int, int, int]]:
        allowed_categories = {"messages", "xp", "words", "chars", "attachments", "emojis"}
        if category not in allowed_categories:
            raise ValueError(f"Invalid category: {category}")

        async with self.db.execute(f"""SELECT user_id, {category}, xp FROM user_stats
                                       WHERE guild_id = ? ORDER BY {category} DESC
                                       LIMIT 10""", (guild_id,)) as cursor:
            return await cursor.fetchall()

    async def poker_get_balance(self, user_id: int) -> int:
        async with self.db.execute("SELECT balance FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def poker_remove_balance(self, user_id: int, amount: int) -> bool:
        async with self.db.execute("SELECT balance FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()

        if not row or row[0] < amount:
            return False

        new_balance = row[0] - amount
        await self.db.execute("UPDATE economy_users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
        await self.db.commit()
        return True

    async def poker_add_balance(self, user_id: int, amount: int) -> None:
        async with self.db.execute("SELECT balance FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            await self.db.execute("INSERT INTO economy_users (user_id, balance) VALUES (?, ?)", (user_id, amount))
        else:
            new_balance = row[0] + amount
            await self.db.execute("UPDATE economy_users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
        await self.db.commit()