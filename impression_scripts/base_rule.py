import asyncio
from enum import Enum, auto
from typing import List, Optional
import discord


class EventHook(Enum):
    ON_MESSAGE = auto()
    MINUTELY = auto()
    DAILY = auto()
    ON_CHAT_BURST = auto()


class EventRule:
    EVENT_HOOKS: List[EventHook] = []

    def __init__(self, rule_id: str, weight: float = 1.0, cooldown_seconds: float = 0.0, **kwargs):
        self.rule_id = rule_id
        self.weight = weight
        self.cooldown_seconds = cooldown_seconds

    def check_eligibility(self, context: object, tracker: object) -> bool:
        return False

    async def execute_on_message(self, message: discord.Message, tracker: object) -> None:
        pass

    async def execute_minutely(self, bot: object, tracker: object) -> None:
        pass

    async def execute_daily(self, bot: object, tracker: object) -> None:
        pass

    async def execute_on_chat_burst(self, message: discord.Message, tracker: object) -> None:
        pass