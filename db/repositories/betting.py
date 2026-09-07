from db.repositories.base import BaseRepository

BOT_RACE_HOUSE_SEED = 2000


class BettingRepository(BaseRepository):
    """horse_races / horse_bets: daily horse racing and parimutuel payouts."""

    async def create_race(self, race_date: str, horses: list[tuple]) -> None:
        await self._db.executemany(
            "INSERT OR IGNORE INTO horse_races (race_date, horse_id, horse_name, speed, stamina, clutch) VALUES (?, ?, ?, ?, ?, ?)",
            [(race_date, h[0], h[1], h[2], h[3], h[4]) for h in horses]
        )
        await self._db.commit()

    async def get_race(self, race_date: str) -> list[dict]:
        async with self._db.execute("SELECT * FROM horse_races WHERE race_date = ? ORDER BY distance DESC", (race_date,)) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_horse_distance(self, race_date: str, horse_id: int, new_distance: float, finished: bool, finish_time: float) -> None:
        await self._db.execute("UPDATE horse_races SET distance = ?, finished = ?, finish_time = ? WHERE race_date = ? AND horse_id = ?", (new_distance, finished, finish_time, race_date, horse_id))
        await self._db.commit()

    async def place_bet(self, user_id: int, race_date: str, horse_id: int, amount: int) -> bool:
        await self._db.execute("INSERT OR IGNORE INTO economy_users (user_id) VALUES (?)", (user_id,))

        async with self._db.execute("SELECT balance FROM economy_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row or row[0] < amount:
                return False

        await self._db.execute("UPDATE economy_users SET balance = balance - ? WHERE user_id = ?", (int(amount), user_id))

        await self._db.execute("INSERT INTO horse_bets (user_id, race_date, horse_id, bet_amount) VALUES (?, ?, ?, ?)", (user_id, race_date, horse_id, int(amount)))
        await self._db.commit()
        return True

    async def resolve_payouts(self, race_date: str, winning_horse_id: int) -> list[dict]:
        async with self._db.execute("SELECT id, user_id, horse_id, bet_amount FROM horse_bets WHERE race_date = ? AND processed = 0", (race_date,)) as cursor:
            all_bets = await cursor.fetchall()

        if not all_bets:
            return []

        total_player_pool = sum(bet['bet_amount'] for bet in all_bets)
        house_rake = int(total_player_pool * 0.20)
        distributable_pool = (total_player_pool + BOT_RACE_HOUSE_SEED) - house_rake

        winning_bets = [b for b in all_bets if b['horse_id'] == winning_horse_id]
        total_winning_bets_sum = sum(b['bet_amount'] for b in winning_bets)

        payout_results = []

        for bet in all_bets:
            if bet['horse_id'] == winning_horse_id and total_winning_bets_sum > 0:
                share_ratio = bet['bet_amount'] / total_winning_bets_sum
                payout = int(distributable_pool * share_ratio)
                await self._db.execute("UPDATE economy_users SET balance = balance + ? WHERE user_id = ?", (payout, bet['user_id']))
                await self._db.execute("UPDATE horse_bets SET payout = ? WHERE id = ?", (payout, bet['id']))
                payout_results.append({"user_id": bet['user_id'], "won": True, "payout": payout})
            else:
                await self._db.execute("UPDATE horse_bets SET payout = 0 WHERE id = ?", (bet['id'],))
                payout_results.append({"user_id": bet['user_id'], "won": False, "payout": 0})

        await self._db.execute("UPDATE horse_bets SET processed = 1 WHERE race_date = ?", (race_date,))
        await self._db.commit()

        return payout_results

    async def get_user_history(self, user_id: int, limit: int = 5) -> list[dict]:
        query = """
                SELECT b.race_date, b.horse_id, SUM(b.bet_amount) AS bet_amount, SUM(COALESCE(b.payout, 0)) AS payout,
                       b.processed, r.horse_name, r.finished
                FROM horse_bets b LEFT JOIN horse_races r ON b.race_date = r.race_date AND b.horse_id = r.horse_id
                WHERE b.user_id = ? GROUP BY b.race_date, b.horse_id ORDER BY MAX(b.id) DESC LIMIT ?
                """
        async with self._db.execute(query, (user_id, int(limit))) as cursor:
            bets = await cursor.fetchall()

        history = []
        for bet in bets:
            bet_dict = dict(bet)
            if bet_dict['processed'] and bet_dict['finished']:
                async with self._db.execute(
                        """SELECT horse_id FROM horse_races WHERE race_date = ? ORDER BY distance DESC,
                           CASE WHEN finish_time IS NULL THEN 1 ELSE 0 END, finish_time ASC LIMIT 1""",
                        (bet_dict['race_date'],)
                ) as w_cursor:
                    winner_row = await w_cursor.fetchone()

                    if winner_row and winner_row['horse_id'] == bet_dict['horse_id']:
                        bet_dict['result'] = "win"
                    else:
                        bet_dict['result'] = "loss"
            else:
                bet_dict['result'] = "pending"

            history.append(bet_dict)

        return history

    async def get_last_race(self) -> tuple[str | None, list[dict]]:
        async with self._db.execute("SELECT DISTINCT race_date FROM horse_races WHERE finished = 1 ORDER BY race_date DESC LIMIT 1") as cursor:
            row = await cursor.fetchone()
            if not row:
                return None, []
            last_date = row['race_date']

        race = await self.get_race(last_date)
        return last_date, race

    async def get_race_bets_summary(self, race_date: str) -> list[dict]:
        async with self._db.execute("SELECT horse_id, SUM(bet_amount) AS total_bet FROM horse_bets WHERE race_date = ? GROUP BY horse_id", (race_date,)) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_unprocessed_dates(self) -> list[str]:
        async with self._db.execute("SELECT DISTINCT race_date FROM horse_bets WHERE processed = 0 AND race_date < DATE('now')") as cursor:
            rows = await cursor.fetchall()
        return [r['race_date'] for r in rows]
