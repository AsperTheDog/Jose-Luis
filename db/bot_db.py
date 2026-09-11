from typing import Any

from db.connection import Database
from db.repositories import (
    ActivityRepository,
    BettingRepository,
    DungeonRepository,
    EconomyRepository,
    GachaRepository,
    GlobalStatsRepository,
    GuildRepository,
    HackingRepository,
    MiningRepository,
    PhraseRepository,
    QuarantineRepository,
    ReminderRepository,
    TwitchRepository,
    WaifuRepository,
)


class BotDatabase:
    def __init__(self, path: str = "bot_data.db"):
        self.db = Database(path)

        self.guild = GuildRepository(self.db)
        self.stats = GlobalStatsRepository(self.db)
        self.economy = EconomyRepository(self.db)
        self.phrases = PhraseRepository(self.db)
        self.mining = MiningRepository(self.db)
        self.gacha = GachaRepository(self.db)
        self.hacking = HackingRepository(self.db)
        self.waifu = WaifuRepository(self.db)
        self.betting = BettingRepository(self.db)
        self.dungeon = DungeonRepository(self.db)
        self.reminders = ReminderRepository(self.db)
        self.twitch = TwitchRepository(self.db)
        self.activity = ActivityRepository(self.db)
        self.quarantine = QuarantineRepository(self.db)

    async def start(self) -> None:
        await self.db.connect()

    async def close(self) -> None:
        await self.db.close()

    @property
    def job_registry(self) -> dict[str, dict[str, Any]]:
        return self.db.job_registry

    def execute(self, sql: str, parameters=None):
        return self.db.execute(sql, parameters)

    def executescript(self, sql_script: str):
        return self.db.executescript(sql_script)

    async def commit(self) -> None:
        await self.db.commit()
