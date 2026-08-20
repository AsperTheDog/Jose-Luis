import sqlite3
from typing import Dict, Any, Optional

class StatsTracker:
    def __init__(self):
        self.db_path = "bot_data.db"
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_global_stats (
                        user_id BIGINT PRIMARY KEY,
                        
                        -- Roulette
                        roulette_money_gained BIGINT DEFAULT 0,
                        roulette_money_lost BIGINT DEFAULT 0,
                        roulette_bets_won BIGINT DEFAULT 0,
                        roulette_bets_lost BIGINT DEFAULT 0,
                        roulette_biggest_bet BIGINT DEFAULT 0,
                        
                        -- Dice
                        dice_money_gained BIGINT DEFAULT 0,
                        dice_money_lost BIGINT DEFAULT 0,
                        dice_bets_won BIGINT DEFAULT 0,
                        dice_bets_lost BIGINT DEFAULT 0,
                        dice_biggest_bet BIGINT DEFAULT 0,
                        
                        -- Slots
                        slots_money_gained BIGINT DEFAULT 0,
                        slots_money_lost BIGINT DEFAULT 0,
                        slots_bets_won BIGINT DEFAULT 0,
                        slots_bets_lost BIGINT DEFAULT 0,
                        slots_biggest_bet BIGINT DEFAULT 0,
                        
                        -- Economy & Transfers
                        money_given BIGINT DEFAULT 0,
                        money_received BIGINT DEFAULT 0,
                        biggest_money_gift BIGINT DEFAULT 0,
                        highest_money_accumulated BIGINT DEFAULT 0,
                        money_spent BIGINT DEFAULT 0,
                        money_obtained BIGINT DEFAULT 0,
                        times_asked_allowance BIGINT DEFAULT 0,
                        money_from_allowance BIGINT DEFAULT 0,
                        biggest_allowance_streak BIGINT DEFAULT 0,
                        times_worked BIGINT DEFAULT 0,
                        money_from_work BIGINT DEFAULT 0,
                        times_switched_jobs BIGINT DEFAULT 0,
                        drops_claimed  BIGINT DEFAULT 0,
                        money_from_drops BIGINT DEFAULT 0,
                        
                        -- Crimes & Jail
                        crimes_successful BIGINT DEFAULT 0,
                        times_gone_to_jail BIGINT DEFAULT 0,
                        crime_money_gained BIGINT DEFAULT 0,
                        crime_fines_paid BIGINT DEFAULT 0,
                        interest_money_gained BIGINT DEFAULT 0,
                        
                        -- Mining & Crafting
                        times_mined BIGINT DEFAULT 0,
                        times_drank BIGINT DEFAULT 0,
                        money_spent_drinking BIGINT DEFAULT 0,
                        energy_spent BIGINT DEFAULT 0,
                        basic_pickaxes_claimed BIGINT DEFAULT 0,
                        materials_mined BIGINT DEFAULT 0,
                        pickaxes_broken BIGINT DEFAULT 0,
                        items_crafted BIGINT DEFAULT 0,
                        items_sold BIGINT DEFAULT 0,
                        item_sales_money_gained BIGINT DEFAULT 0
                    );
                    """)
            conn.commit()

    def _increment_stat(self, user_id: int, column_name: str, amount: int = 1) -> None:
        query = f"""
            INSERT INTO user_global_stats (user_id, {column_name})
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                {column_name} = {column_name} + excluded.{column_name};
        """
        with sqlite3.connect(self.db_path) as db:
            db.execute(query, (user_id, amount))
            db.commit()

    def _update_max_stat(self, user_id: int, column_name: str, value: int) -> None:
        query = f"""
            INSERT INTO user_global_stats (user_id, {column_name})
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                {column_name} = MAX({column_name}, excluded.{column_name});
        """
        with sqlite3.connect(self.db_path) as db:
            db.execute(query, (user_id, value))
            db.commit()

    def register_roulette_win(self, user_id: int, money_gained: int, bet_amount: int) -> None:
        self._increment_stat(user_id, "roulette_money_gained", money_gained)
        self.register_money_obtained(user_id, money_gained)
        self._increment_stat(user_id, "roulette_bets_won", 1)
        self._increment_stat(user_id, "roulette_money_lost", bet_amount)
        self._update_max_stat(user_id, "roulette_biggest_bet", bet_amount)
        self.register_money_spent(user_id, bet_amount)

    def register_roulette_loss(self, user_id: int, bet_amount: int) -> None:
        self._increment_stat(user_id, "roulette_money_lost", bet_amount)
        self._increment_stat(user_id, "roulette_bets_lost", 1)
        self._update_max_stat(user_id, "roulette_biggest_bet", bet_amount)
        self.register_money_spent(user_id, bet_amount)

    def register_dice_win(self, user_id: int, money_gained: int, bet_amount: int) -> None:
        self._increment_stat(user_id, "dice_money_gained", money_gained)
        self.register_money_obtained(user_id, money_gained)
        self._increment_stat(user_id, "dice_bets_won", 1)
        self._increment_stat(user_id, "dice_money_lost", bet_amount)
        self._update_max_stat(user_id, "dice_biggest_bet", bet_amount)
        self.register_money_spent(user_id, bet_amount)

    def register_dice_loss(self, user_id: int, bet_amount: int) -> None:
        self._increment_stat(user_id, "dice_money_lost", bet_amount)
        self._increment_stat(user_id, "dice_bets_lost", 1)
        self._update_max_stat(user_id, "dice_biggest_bet", bet_amount)
        self.register_money_spent(user_id, bet_amount)

    def register_slots_win(self, user_id: int, money_gained: int, bet_amount: int) -> None:
        self._increment_stat(user_id, "slots_money_gained", money_gained)
        self.register_money_obtained(user_id, money_gained)
        self._increment_stat(user_id, "slots_bets_won", 1)
        self._increment_stat(user_id, "slots_money_lost", bet_amount)
        self._update_max_stat(user_id, "slots_biggest_bet", bet_amount)
        self.register_money_spent(user_id, bet_amount)

    def register_slots_loss(self, user_id: int, bet_amount: int) -> None:
        self._increment_stat(user_id, "slots_money_lost", bet_amount)
        self._increment_stat(user_id, "slots_bets_lost", 1)
        self._update_max_stat(user_id, "slots_biggest_bet", bet_amount)
        self.register_money_spent(user_id, bet_amount)

    def register_money_gift_give(self, user_id: int, amount: int) -> None:
        self._increment_stat(user_id, "money_given", amount)
        self._update_max_stat(user_id, "biggest_money_gift", amount)
        self.register_money_spent(user_id, amount)

    def register_money_gift_receive(self, user_id: int, amount: int) -> None:
        self._increment_stat(user_id, "money_received", amount)
        self.register_money_obtained(user_id, amount)

    def register_wallet_update(self, user_id: int, current_balance: int) -> None:
        self._update_max_stat(user_id, "highest_money_accumulated", current_balance)

    def register_money_spent(self, user_id: int, amount: int = 1) -> None:
        self._increment_stat(user_id, "money_spent", amount)

    def register_money_obtained(self, user_id: int, amount: int = 1) -> None:
        self._increment_stat(user_id, "money_obtained", amount)

    def register_allowance_claim(self, user_id: int, amount: int, streak: int) -> None:
        self._increment_stat(user_id, "times_asked_allowance", 1)
        self._increment_stat(user_id, "money_from_allowance", amount)
        self._update_max_stat(user_id, "biggest_allowance_streak", streak)
        self.register_money_obtained(user_id, amount)

    def register_work(self, user_id: int, amount: int) -> None:
        self._increment_stat(user_id, "times_worked", 1)
        self._increment_stat(user_id, "money_from_work", amount)
        self.register_money_obtained(user_id, amount)

    def register_job_switch(self, user_id: int) -> None:
        self._increment_stat(user_id, "times_switched_jobs", 1)

    def register_successful_crime(self, user_id: int, money_gained: int) -> None:
        self._increment_stat(user_id, "crimes_successful", 1)
        self._increment_stat(user_id, "crime_money_gained", money_gained)
        self.register_money_obtained(user_id, money_gained)

    def register_jail_sentence(self, user_id: int, fine_paid: int) -> None:
        self._increment_stat(user_id, "times_gone_to_jail", 1)
        self._increment_stat(user_id, "crime_fines_paid", fine_paid)
        self.register_money_spent(user_id, fine_paid)

    def register_interest_payout(self, user_id: int, amount: int) -> None:
        self._increment_stat(user_id, "interest_money_gained", amount)
        self.register_money_obtained(user_id, amount)

    def register_drop_obtained(self, user_id: int, amount: int) -> None:
        self._increment_stat(user_id, "drops_claimed", 1)
        self._increment_stat(user_id, "money_from_drops", amount)
        self.register_money_obtained(user_id, amount)

    def register_mine_action(self, user_id: int, energy_used: int, materials_gained: int) -> None:
        self._increment_stat(user_id, "times_mined", 1)
        self._increment_stat(user_id, "energy_spent", energy_used)
        self._increment_stat(user_id, "materials_mined", materials_gained)

    def register_drink_action(self, user_id: int, cost: int) -> None:
        self._increment_stat(user_id, "times_drank", 1)
        self._increment_stat(user_id, "money_spent_drinking", cost)
        self.register_money_spent(user_id, cost)

    def register_basic_pickaxe_claim(self, user_id: int) -> None:
        self._increment_stat(user_id, "basic_pickaxes_claimed", 1)

    def register_pickaxe_broken(self, user_id: int) -> None:
        self._increment_stat(user_id, "pickaxes_broken", 1)

    def register_item_crafted(self, user_id: int) -> None:
        self._increment_stat(user_id, "items_crafted", 1)

    def register_item_sale(self, user_id: int, items_sold_count: int, money_gained: int) -> None:
        self._increment_stat(user_id, "items_sold", items_sold_count)
        self._increment_stat(user_id, "item_sales_money_gained", money_gained)
        self.register_money_obtained(user_id, money_gained)

    def get_user_global_stats(self, user_id: int) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM user_global_stats WHERE user_id = ?;"
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = db.cursor()
            cursor.execute(query, (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None