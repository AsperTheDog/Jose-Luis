from typing import Any, Optional

from db.repositories.base import BaseRepository


class GlobalStatsRepository(BaseRepository):
    _SUM_COLUMNS = (
        "roulette_money_gained", "roulette_money_lost", "roulette_bets_won", "roulette_bets_lost",
        "dice_money_gained", "dice_money_lost", "dice_bets_won", "dice_bets_lost",
        "slots_money_gained", "slots_money_lost", "slots_bets_won", "slots_bets_lost",
        "cards_money_gained", "cards_money_lost", "cards_bets_won", "cards_bets_lost",
        "blackjack_money_gained", "blackjack_money_lost", "blackjack_hands_won",
        "blackjack_hands_lost", "blackjack_hands_pushed", "blackjack_naturals",
        "money_given", "money_received", "money_spent", "money_obtained",
        "times_asked_allowance", "money_from_allowance", "times_worked", "money_from_work",
        "times_switched_jobs", "drops_claimed", "money_from_drops",
        "crimes_successful", "times_gone_to_jail", "crime_money_gained", "crime_fines_paid",
        "interest_money_gained",
        "times_mined", "times_drank", "money_spent_drinking", "energy_spent",
        "basic_pickaxes_claimed", "materials_mined", "pickaxes_broken", "items_crafted",
        "items_sold", "item_sales_money_gained",
        "hacking_times_hacked_easy", "hacking_times_hacked_normal", "hacking_times_hacked_hard",
        "hacking_times_hacked_very_hard", "hacking_times_failed_timeout", "hacking_times_failed_firewall",
        "hacking_times_failed_lost", "hacking_money_gained", "hacking_time_spent",
        "gacha_throws", "gacha_boosted_throws", "gacha_shards_obtained_2", "gacha_shards_obtained_3",
        "gacha_shards_obtained_4", "gacha_shards_obtained_5", "gacha_units_crafted",
        "gacha_shards_destroyed", "gacha_dust_obtained", "gacha_dust_spent",
        "betting_bets_placed", "betting_bets_won", "betting_bets_lost",
        "betting_money_gained", "betting_money_lost",
        "dungeon_floors_cleared", "dungeon_enemies_defeated", "dungeon_bosses_defeated", "dungeon_gold_earned",
        "dungeon_items_found", "dungeon_prestiges", "dungeon_dust_earned",
        "dungeon_mutations", "dungeon_boss_coins_earned", "dungeon_coins_converted",
        "dungeon_money_converted", "dungeon_deaths", "dungeon_damage_dealt",
        "dungeon_damage_taken", "dungeon_training_sessions", "dungeon_passive_xp", "dungeon_auto_sims",
        "dungeon_anomalies_cleared", "dungeon_rerolls", "dungeon_infusions",
        "dungeon_retreats", "dungeon_echoes",
    )

    _MAX_COLUMNS = (
        "roulette_biggest_bet", "dice_biggest_bet", "slots_biggest_bet", "cards_biggest_bet",
        "blackjack_biggest_bet",
        "biggest_money_gift", "highest_money_accumulated", "biggest_allowance_streak",
        "betting_biggest_bet", "betting_biggest_win",
        "dungeon_highest_floor",
    )

    async def get_user(self, user_id: int) -> Optional[dict[str, Any]]:
        query = "SELECT * FROM user_global_stats WHERE user_id = ?;"
        async with self._db.execute(query, (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def increment(self, user_id: int, column_name: str, amount: int | float = 1) -> None:
        query = f"""INSERT INTO user_global_stats (user_id, {column_name})
                    VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET {column_name} = {column_name} + excluded.{column_name}; """
        await self._db.execute(query, (user_id, amount))
        await self._db.commit()

    async def update_max(self, user_id: int, column_name: str, value: int) -> None:
        query = f"""INSERT INTO user_global_stats (user_id, {column_name})
                    VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET {column_name} = MAX({column_name}, excluded.{column_name});"""
        await self._db.execute(query, (user_id, value))
        await self._db.commit()

    async def fetch_user(self, user_id: int) -> dict:
        async with self._db.execute("SELECT * FROM user_global_stats WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else {}

    async def fetch_aggregate(self) -> dict:
        select_parts = [f"COALESCE(SUM({col}), 0) AS {col}" for col in self._SUM_COLUMNS]
        select_parts += [f"COALESCE(MAX({col}), 0) AS {col}" for col in self._MAX_COLUMNS]
        query = f"SELECT {', '.join(select_parts)} FROM user_global_stats"
        async with self._db.execute(query) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else {}
