import time
import random
from collections import defaultdict
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

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
        self.ruledb = RuleDB(db_path="bot_data.db", config_path="rules.json")
        self.tracker = ChannelTracker(self.bot.config.get_float("burst_time_window"), self.bot.config.get_int("burst_message_count"))

        self.channel_global_cooldowns: Dict[int, float] = defaultdict(float)
        self.global_cooldown_seconds = self.bot.config.get_float("global_cooldown_seconds")

        self.minutely_loop.start()

    def cog_unload(self):
        self.minutely_loop.cancel()

    @impressions_group.command(name="decir", description="Hacer que Jose Luis diga algo")
    async def decir(self, interaction: discord.Interaction, message: str, reply_to: Optional[str] = None):
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

        now = time.time()
        if (now - self.channel_global_cooldowns[message.channel.id]) < self.global_cooldown_seconds:
            return

        is_burst = self.tracker.log_message(message.channel.id)
        active_hook = EventHook.ON_CHAT_BURST if is_burst else EventHook.ON_MESSAGE
        candidates = await self.ruledb.get_eligible_rules(hook=active_hook, context=message, tracker=self.tracker)

        if not candidates and is_burst:
            active_hook = EventHook.ON_MESSAGE
            candidates = await self.ruledb.get_eligible_rules(hook=active_hook, context=message, tracker=self.tracker)

        if not candidates:
            return

        weights = [rule.weight for rule in candidates]
        winning_rule: EventRule = random.choices(candidates, weights=weights, k=1)[0]

        self.channel_global_cooldowns[message.channel.id] = now
        await self.ruledb.update_rule_cooldown(message.channel.id, winning_rule.rule_id)

        if active_hook == EventHook.ON_CHAT_BURST:
            await winning_rule.execute_on_chat_burst(message, tracker=self.tracker)
        else:
            await winning_rule.execute_on_message(message, tracker=self.tracker)

    @tasks.loop(minutes=1.0)
    async def minutely_loop(self):
        await self.bot.wait_until_ready()
        now_struct = time.localtime()

        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                if not self.bot.is_channel_whitelisted(channel.id):
                    continue

                minutely_rules = await self.ruledb.get_eligible_rules(hook=EventHook.MINUTELY, context=channel)
                for rule in minutely_rules:
                    await rule.execute_minutely(self.bot, channel)
                    await self.ruledb.update_rule_cooldown(channel.id, rule.rule_id)

                if now_struct.tm_hour == 0 and now_struct.tm_min == 0:
                    daily_rules = await self.ruledb.get_eligible_rules(hook=EventHook.DAILY, context=channel)
                    for rule in daily_rules:
                        await rule.execute_daily(self.bot, channel)
                        await self.ruledb.update_rule_cooldown(channel.id, rule.rule_id)


async def setup(bot: ScalableBot):
    await bot.add_cog(PersonalityEngineCog(bot))