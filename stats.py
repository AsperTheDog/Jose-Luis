from db.repositories.global_stats import GlobalStatsRepository


class StatsTracker:
    def __init__(self, stats: GlobalStatsRepository):
        self.stats = stats

    async def _register_bet_win(self, user_id: int, prefix: str, won_column: str, money_gained: int, bet_amount: int) -> None:
        await self.stats.increment(user_id, f"{prefix}_money_gained", money_gained)
        await self.register_money_obtained(user_id, money_gained)
        await self.stats.increment(user_id, won_column, 1)
        await self.stats.increment(user_id, f"{prefix}_money_lost", bet_amount)
        await self.stats.update_max(user_id, f"{prefix}_biggest_bet", bet_amount)
        await self.register_money_spent(user_id, bet_amount)

    async def _register_bet_loss(self, user_id: int, prefix: str, lost_column: str, bet_amount: int) -> None:
        await self.stats.increment(user_id, f"{prefix}_money_lost", bet_amount)
        await self.stats.increment(user_id, lost_column, 1)
        await self.stats.update_max(user_id, f"{prefix}_biggest_bet", bet_amount)
        await self.register_money_spent(user_id, bet_amount)

    async def register_roulette_win(self, user_id: int, money_gained: int, bet_amount: int) -> None:
        await self._register_bet_win(user_id, "roulette", "roulette_bets_won", money_gained, bet_amount)

    async def register_roulette_loss(self, user_id: int, bet_amount: int) -> None:
        await self._register_bet_loss(user_id, "roulette", "roulette_bets_lost", bet_amount)

    async def register_dice_win(self, user_id: int, money_gained: int, bet_amount: int) -> None:
        await self._register_bet_win(user_id, "dice", "dice_bets_won", money_gained, bet_amount)

    async def register_dice_loss(self, user_id: int, bet_amount: int) -> None:
        await self._register_bet_loss(user_id, "dice", "dice_bets_lost", bet_amount)

    async def register_slots_win(self, user_id: int, money_gained: int, bet_amount: int) -> None:
        await self._register_bet_win(user_id, "slots", "slots_bets_won", money_gained, bet_amount)

    async def register_slots_loss(self, user_id: int, bet_amount: int) -> None:
        await self._register_bet_loss(user_id, "slots", "slots_bets_lost", bet_amount)

    async def register_cards_win(self, user_id: int, money_gained: int, bet_amount: int) -> None:
        await self._register_bet_win(user_id, "cards", "cards_bets_won", money_gained, bet_amount)

    async def register_cards_loss(self, user_id: int, bet_amount: int) -> None:
        await self._register_bet_loss(user_id, "cards", "cards_bets_lost", bet_amount)

    async def register_money_gift_give(self, user_id: int, amount: int) -> None:
        await self.stats.increment(user_id, "money_given", amount)
        await self.stats.update_max(user_id, "biggest_money_gift", amount)
        await self.register_money_spent(user_id, amount)

    async def register_money_gift_receive(self, user_id: int, amount: int) -> None:
        await self.stats.increment(user_id, "money_received", amount)
        await self.register_money_obtained(user_id, amount)

    async def register_wallet_update(self, user_id: int, current_balance: int) -> None:
        await self.stats.update_max(user_id, "highest_money_accumulated", current_balance)

    async def register_money_spent(self, user_id: int, amount: int = 1) -> None:
        await self.stats.increment(user_id, "money_spent", amount)

    async def register_money_obtained(self, user_id: int, amount: int = 1) -> None:
        await self.stats.increment(user_id, "money_obtained", amount)

    async def register_allowance_claim(self, user_id: int, amount: int, streak: int) -> None:
        await self.stats.increment(user_id, "times_asked_allowance", 1)
        await self.stats.increment(user_id, "money_from_allowance", amount)
        await self.stats.update_max(user_id, "biggest_allowance_streak", streak)
        await self.register_money_obtained(user_id, amount)

    async def register_work(self, user_id: int, amount: int) -> None:
        await self.stats.increment(user_id, "times_worked", 1)
        await self.stats.increment(user_id, "money_from_work", amount)
        await self.register_money_obtained(user_id, amount)

    async def register_job_switch(self, user_id: int) -> None:
        await self.stats.increment(user_id, "times_switched_jobs", 1)

    async def register_successful_crime(self, user_id: int, money_gained: int) -> None:
        await self.stats.increment(user_id, "crimes_successful", 1)
        await self.stats.increment(user_id, "crime_money_gained", money_gained)
        await self.register_money_obtained(user_id, money_gained)

    async def register_jail_sentence(self, user_id: int, fine_paid: int) -> None:
        await self.stats.increment(user_id, "times_gone_to_jail", 1)
        await self.stats.increment(user_id, "crime_fines_paid", fine_paid)
        await self.register_money_spent(user_id, fine_paid)

    async def register_interest_payout(self, user_id: int, amount: int) -> None:
        await self.stats.increment(user_id, "interest_money_gained", amount)
        await self.register_money_obtained(user_id, amount)

    async def register_drop_obtained(self, user_id: int, amount: int) -> None:
        await self.stats.increment(user_id, "drops_claimed", 1)
        await self.stats.increment(user_id, "money_from_drops", amount)
        await self.register_money_obtained(user_id, amount)

    async def register_mine_action(self, user_id: int, energy_used: int, materials_gained: int) -> None:
        await self.stats.increment(user_id, "times_mined", 1)
        await self.stats.increment(user_id, "energy_spent", energy_used)
        await self.stats.increment(user_id, "materials_mined", materials_gained)

    async def register_drink_action(self, user_id: int, cost: int) -> None:
        await self.stats.increment(user_id, "times_drank", 1)
        await self.stats.increment(user_id, "money_spent_drinking", cost)
        await self.register_money_spent(user_id, cost)

    async def register_basic_pickaxe_claim(self, user_id: int) -> None:
        await self.stats.increment(user_id, "basic_pickaxes_claimed", 1)

    async def register_pickaxe_broken(self, user_id: int) -> None:
        await self.stats.increment(user_id, "pickaxes_broken", 1)

    async def register_item_crafted(self, user_id: int, amount: int) -> None:
        await self.stats.increment(user_id, "items_crafted", amount)

    async def register_item_sale(self, user_id: int, items_sold_count: int, money_gained: int) -> None:
        await self.stats.increment(user_id, "items_sold", items_sold_count)
        await self.stats.increment(user_id, "item_sales_money_gained", money_gained)
        await self.register_money_obtained(user_id, money_gained)

    async def register_hack_win(self, user_id: int, difficulty: str, money_gained: int, time_spent: float) -> None:
        valid_difficulties = ["easy", "normal", "hard", "very_hard"]
        diff_key = difficulty.lower().replace(" ", "")

        if diff_key in valid_difficulties:
            await self.stats.increment(user_id, f"hacking_times_hacked_{diff_key}", 1)

        await self.stats.increment(user_id, "hacking_time_spent", time_spent)

        if money_gained > 0:
            await self.stats.increment(user_id, "hacking_money_gained", money_gained)
            await self.register_money_obtained(user_id, money_gained)

    async def register_hack_loss(self, user_id: int, reason: str, time_spent: float) -> None:
        valid_reasons = {
            "timeout": "hacking_times_failed_timeout",
            "firewall": "hacking_times_failed_firewall",
            "lost": "hacking_times_failed_lost"
        }

        column_name = valid_reasons.get(reason.lower())
        if column_name:
            await self.stats.increment(user_id, column_name, 1)

        await self.stats.increment(user_id, "hacking_time_spent", time_spent)

    async def register_gacha_throw(self, user_id: int, times: int, cost: int, boosted: bool) -> None:
        await self.stats.increment(user_id, "gacha_throws", times)
        await self.register_money_spent(user_id, cost)
        if boosted:
            await self.stats.increment(user_id, "gacha_boosted_throws", times)

    async def register_gacha_shard_obtained(self, user_id: int, rarity: int) -> None:
        valid_rarities = {2, 3, 4, 5}
        if rarity in valid_rarities:
            await self.stats.increment(user_id, f"gacha_shards_obtained_{rarity}", 1)

    async def register_gacha_unit_crafted(self, user_id: int, amount: int = 1) -> None:
        await self.stats.increment(user_id, "gacha_units_crafted", amount)

    async def register_gacha_shard_destroyed(self, user_id: int, amount: int, dust_gained: int) -> None:
        await self.stats.increment(user_id, "gacha_shards_destroyed", amount)
        await self.stats.increment(user_id, "gacha_dust_obtained", dust_gained)

    async def register_gacha_dust_spent(self, user_id: int, amount: int) -> None:
        await self.stats.increment(user_id, "gacha_dust_spent", amount)

    async def register_blackjack_win(self, user_id: int, money_gained: int, bet_amount: int, natural: bool = False) -> None:
        await self._register_bet_win(user_id, "blackjack", "blackjack_hands_won", money_gained, bet_amount)
        if natural:
            await self.stats.increment(user_id, "blackjack_naturals", 1)

    async def register_blackjack_loss(self, user_id: int, bet_amount: int) -> None:
        await self._register_bet_loss(user_id, "blackjack", "blackjack_hands_lost", bet_amount)

    async def register_blackjack_push(self, user_id: int, bet_amount: int) -> None:
        await self.stats.increment(user_id, "blackjack_hands_pushed", 1)
        await self.stats.update_max(user_id, "blackjack_biggest_bet", bet_amount)

    async def register_bet_placed(self, user_id: int, amount: int) -> None:
        await self.stats.increment(user_id, "betting_bets_placed", 1)
        await self.stats.increment(user_id, "betting_money_lost", amount)
        await self.stats.update_max(user_id, "betting_biggest_bet", amount)
        await self.register_money_spent(user_id, amount)

    async def register_bet_won(self, user_id: int, payout: int) -> None:
        await self.stats.increment(user_id, "betting_bets_won", 1)
        await self.stats.increment(user_id, "betting_money_gained", payout)
        await self.stats.update_max(user_id, "betting_biggest_win", payout)
        await self.register_money_obtained(user_id, payout)

    async def register_bet_lost(self, user_id: int) -> None:
        await self.stats.increment(user_id, "betting_bets_lost", 1)

    async def register_dungeon_kill(self, user_id: int) -> None:
        await self.stats.increment(user_id, "dungeon_enemies_defeated", 1)

    async def register_dungeon_loot(self, user_id: int, gold: int, items: int = 0) -> None:
        await self.stats.increment(user_id, "dungeon_gold_earned", gold)
        if items:
            await self.stats.increment(user_id, "dungeon_items_found", items)

    async def register_dungeon_floor_cleared(self, user_id: int) -> None:
        await self.stats.increment(user_id, "dungeon_floors_cleared", 1)

    async def register_dungeon_depth(self, user_id: int, floor: int) -> None:
        if floor > 0:
            await self.stats.update_max(user_id, "dungeon_highest_floor", floor)

    async def register_dungeon_boss(self, user_id: int, tier: int, coins: int) -> None:
        await self.stats.increment(user_id, "dungeon_bosses_defeated", 1)
        await self.stats.increment(user_id, "dungeon_boss_coins_earned", coins)
        await self.stats.update_max(user_id, "dungeon_highest_floor", tier * 10)

    async def register_dungeon_combat(self, user_id: int, damage_dealt: int, damage_taken: int) -> None:
        if damage_dealt:
            await self.stats.increment(user_id, "dungeon_damage_dealt", damage_dealt)
        if damage_taken:
            await self.stats.increment(user_id, "dungeon_damage_taken", damage_taken)

    async def register_dungeon_death(self, user_id: int) -> None:
        await self.stats.increment(user_id, "dungeon_deaths", 1)

    async def register_dungeon_prestige(self, user_id: int, dust: int) -> None:
        await self.stats.increment(user_id, "dungeon_prestiges", 1)
        await self.stats.increment(user_id, "dungeon_dust_earned", dust)

    async def register_dungeon_dust(self, user_id: int, dust: int) -> None:
        if dust:
            await self.stats.increment(user_id, "dungeon_dust_earned", dust)

    async def register_dungeon_mutation(self, user_id: int) -> None:
        await self.stats.increment(user_id, "dungeon_mutations", 1)

    async def register_dungeon_conversion(self, user_id: int, coins: int, money: int) -> None:
        await self.stats.increment(user_id, "dungeon_coins_converted", coins)
        await self.stats.increment(user_id, "dungeon_money_converted", money)
        await self.register_money_obtained(user_id, money)

    async def register_dungeon_item_found(self, user_id: int, amount: int = 1) -> None:
        await self.stats.increment(user_id, "dungeon_items_found", amount)

    async def register_dungeon_training(self, user_id: int, sessions: int = 1) -> None:
        await self.stats.increment(user_id, "dungeon_training_sessions", sessions)

    async def register_dungeon_passive_xp(self, user_id: int, amount: int) -> None:
        if amount > 0:
            await self.stats.increment(user_id, "dungeon_passive_xp", amount)

    async def register_dungeon_auto_sim(self, user_id: int, floors: int) -> None:
        if floors:
            await self.stats.increment(user_id, "dungeon_auto_sims", floors)

    async def register_dungeon_anomaly(self, user_id: int) -> None:
        await self.stats.increment(user_id, "dungeon_anomalies_cleared", 1)

    async def register_dungeon_reroll(self, user_id: int, sockets: int = 1) -> None:
        await self.stats.increment(user_id, "dungeon_rerolls", sockets)

    async def register_dungeon_infusion(self, user_id: int) -> None:
        await self.stats.increment(user_id, "dungeon_infusions", 1)

    async def register_dungeon_retreat(self, user_id: int) -> None:
        await self.stats.increment(user_id, "dungeon_retreats", 1)

    async def register_dungeon_echo(self, user_id: int, amount: int = 1) -> None:
        await self.stats.increment(user_id, "dungeon_echoes", amount)
