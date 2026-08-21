from database import DBManager


class StatsTracker:
    def __init__(self, db: DBManager):
        self.db = db

    async def register_roulette_win(self, user_id: int, money_gained: int, bet_amount: int) -> None:
        await self.db.increment_stat(user_id, "roulette_money_gained", money_gained)
        await self.register_money_obtained(user_id, money_gained)
        await self.db.increment_stat(user_id, "roulette_bets_won", 1)
        await self.db.increment_stat(user_id, "roulette_money_lost", bet_amount)
        await self.db.update_max_stat(user_id, "roulette_biggest_bet", bet_amount)
        await self.register_money_spent(user_id, bet_amount)

    async def register_roulette_loss(self, user_id: int, bet_amount: int) -> None:
        await self.db.increment_stat(user_id, "roulette_money_lost", bet_amount)
        await self.db.increment_stat(user_id, "roulette_bets_lost", 1)
        await self.db.update_max_stat(user_id, "roulette_biggest_bet", bet_amount)
        await self.register_money_spent(user_id, bet_amount)

    async def register_dice_win(self, user_id: int, money_gained: int, bet_amount: int) -> None:
        await self.db.increment_stat(user_id, "dice_money_gained", money_gained)
        await self.register_money_obtained(user_id, money_gained)
        await self.db.increment_stat(user_id, "dice_bets_won", 1)
        await self.db.increment_stat(user_id, "dice_money_lost", bet_amount)
        await self.db.update_max_stat(user_id, "dice_biggest_bet", bet_amount)
        await self.register_money_spent(user_id, bet_amount)

    async def register_dice_loss(self, user_id: int, bet_amount: int) -> None:
        await self.db.increment_stat(user_id, "dice_money_lost", bet_amount)
        await self.db.increment_stat(user_id, "dice_bets_lost", 1)
        await self.db.update_max_stat(user_id, "dice_biggest_bet", bet_amount)
        await self.register_money_spent(user_id, bet_amount)

    async def register_slots_win(self, user_id: int, money_gained: int, bet_amount: int) -> None:
        await self.db.increment_stat(user_id, "slots_money_gained", money_gained)
        await self.register_money_obtained(user_id, money_gained)
        await self.db.increment_stat(user_id, "slots_bets_won", 1)
        await self.db.increment_stat(user_id, "slots_money_lost", bet_amount)
        await self.db.update_max_stat(user_id, "slots_biggest_bet", bet_amount)
        await self.register_money_spent(user_id, bet_amount)

    async def register_slots_loss(self, user_id: int, bet_amount: int) -> None:
        await self.db.increment_stat(user_id, "slots_money_lost", bet_amount)
        await self.db.increment_stat(user_id, "slots_bets_lost", 1)
        await self.db.update_max_stat(user_id, "slots_biggest_bet", bet_amount)
        await self.register_money_spent(user_id, bet_amount)

    async def register_money_gift_give(self, user_id: int, amount: int) -> None:
        await self.db.increment_stat(user_id, "money_given", amount)
        await self.db.update_max_stat(user_id, "biggest_money_gift", amount)
        await self.register_money_spent(user_id, amount)

    async def register_money_gift_receive(self, user_id: int, amount: int) -> None:
        await self.db.increment_stat(user_id, "money_received", amount)
        await self.register_money_obtained(user_id, amount)

    async def register_wallet_update(self, user_id: int, current_balance: int) -> None:
        await self.db.update_max_stat(user_id, "highest_money_accumulated", current_balance)

    async def register_money_spent(self, user_id: int, amount: int = 1) -> None:
        await self.db.increment_stat(user_id, "money_spent", amount)

    async def register_money_obtained(self, user_id: int, amount: int = 1) -> None:
        await self.db.increment_stat(user_id, "money_obtained", amount)

    async def register_allowance_claim(self, user_id: int, amount: int, streak: int) -> None:
        await self.db.increment_stat(user_id, "times_asked_allowance", 1)
        await self.db.increment_stat(user_id, "money_from_allowance", amount)
        await self.db.update_max_stat(user_id, "biggest_allowance_streak", streak)
        await self.register_money_obtained(user_id, amount)

    async def register_work(self, user_id: int, amount: int) -> None:
        await self.db.increment_stat(user_id, "times_worked", 1)
        await self.db.increment_stat(user_id, "money_from_work", amount)
        await self.register_money_obtained(user_id, amount)

    async def register_job_switch(self, user_id: int) -> None:
        await self.db.increment_stat(user_id, "times_switched_jobs", 1)

    async def register_successful_crime(self, user_id: int, money_gained: int) -> None:
        await self.db.increment_stat(user_id, "crimes_successful", 1)
        await self.db.increment_stat(user_id, "crime_money_gained", money_gained)
        await self.register_money_obtained(user_id, money_gained)

    async def register_jail_sentence(self, user_id: int, fine_paid: int) -> None:
        await self.db.increment_stat(user_id, "times_gone_to_jail", 1)
        await self.db.increment_stat(user_id, "crime_fines_paid", fine_paid)
        await self.register_money_spent(user_id, fine_paid)

    async def register_interest_payout(self, user_id: int, amount: int) -> None:
        await self.db.increment_stat(user_id, "interest_money_gained", amount)
        await self.register_money_obtained(user_id, amount)

    async def register_drop_obtained(self, user_id: int, amount: int) -> None:
        await self.db.increment_stat(user_id, "drops_claimed", 1)
        await self.db.increment_stat(user_id, "money_from_drops", amount)
        await self.register_money_obtained(user_id, amount)

    async def register_mine_action(self, user_id: int, energy_used: int, materials_gained: int) -> None:
        await self.db.increment_stat(user_id, "times_mined", 1)
        await self.db.increment_stat(user_id, "energy_spent", energy_used)
        await self.db.increment_stat(user_id, "materials_mined", materials_gained)

    async def register_drink_action(self, user_id: int, cost: int) -> None:
        await self.db.increment_stat(user_id, "times_drank", 1)
        await self.db.increment_stat(user_id, "money_spent_drinking", cost)
        await self.register_money_spent(user_id, cost)

    async def register_basic_pickaxe_claim(self, user_id: int) -> None:
        await self.db.increment_stat(user_id, "basic_pickaxes_claimed", 1)

    async def register_pickaxe_broken(self, user_id: int) -> None:
        await self.db.increment_stat(user_id, "pickaxes_broken", 1)

    async def register_item_crafted(self, user_id: int, amount: int) -> None:
        await self.db.increment_stat(user_id, "items_crafted", amount)

    async def register_item_sale(self, user_id: int, items_sold_count: int, money_gained: int) -> None:
        await self.db.increment_stat(user_id, "items_sold", items_sold_count)
        await self.db.increment_stat(user_id, "item_sales_money_gained", money_gained)
        await self.register_money_obtained(user_id, money_gained)

