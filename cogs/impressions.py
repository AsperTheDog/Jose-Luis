import time
import random
from collections import defaultdict
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from impression_scripts.rules import *

from impression_scripts.activity_tracker import ChannelTracker
from impression_scripts.base_rule import EventHook, EventRule
from impression_scripts.rule_db import RuleDB
from main import ScalableBot


class PersonalityEngineCog(commands.Cog):
    impressions_group = app_commands.Group(
        name="interacción",
        description="Comandos para que Jose Luis interactúe"
    )

    def __init__(self, bot: ScalableBot):
        self.bot = bot

        self.ruledb = RuleDB("rules.json")
        self.tracker = ChannelTracker(self.bot.config.get_float("burst_time_window"), self.bot.config.get_int("burst_message_count"))

        self.channel_global_cooldowns: Dict[int, float] = defaultdict(float)
        self.global_cooldown_seconds = self.bot.config.get_float("global_cooldown_seconds")

    @impressions_group.command(name="decir", description="Hacer que Jose Luis diga algo")
    async def decir(self, interaction: discord.Interaction, message: str, reply_to: Optional[str] = None,):
        if await self.bot.filter_operators(interaction): return

        target_message: Optional[discord.Message] = None

        if reply_to:
            msg_id_str = reply_to.strip().split("/")[-1]
            if not msg_id_str.isdigit():
                await interaction.response.send_message("El ID o enlace del mensaje proporcionado no es válido.", ephemeral=True)
                return
            try:
                target_message = await interaction.channel.fetch_message(int(msg_id_str))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                await interaction.response.send_message("No se pudo encontrar el mensaje en este canal.", ephemeral=True)
                return

        if target_message:
            await target_message.reply(message)
        else:
            await interaction.channel.send(message)

        await interaction.response.send_message("Mensaje enviado.", ephemeral=True, delete_after=0.1)


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None or not self.bot.is_channel_whitelisted(message.channel.id):
            return

        is_burst = self.tracker.log_message(message.channel.id)
        active_hook = EventHook.ON_MESSAGE if not is_burst else EventHook.ON_CHAT_BURST
        candidates = self.ruledb.get_eligible_rules(hook=active_hook, context=message, tracker=self.tracker)
        if not candidates and is_burst:
            active_hook = EventHook.ON_MESSAGE
            candidates = self.ruledb.get_eligible_rules(hook=active_hook, context=message, tracker=self.tracker)

        if candidates:
            weights = [rule.weight for rule in candidates]
            winning_rule: EventRule = random.choices(candidates, weights=weights, k=1)[0]
        else:
            return

        self.channel_global_cooldowns[message.channel.id] = time.time()
        if active_hook == EventHook.ON_CHAT_BURST:
            await winning_rule.execute_on_chat_burst(message, tracker=self.tracker)
        else:
            await winning_rule.execute_on_message(message, tracker=self.tracker)


async def setup(bot: ScalableBot):
    await bot.add_cog(PersonalityEngineCog(bot))