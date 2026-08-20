import json
import os
import random
import sqlite3
from typing import Any, Dict, List, Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import GuildConfigManager
from stats import StatsTracker

load_dotenv()


class JoseLuisBot(commands.Bot):
    def __init__(self, twitchClient, twitchSecret):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.moderation = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents
        )
        self.config = GuildConfigManager()
        self.twitchClient = twitchClient
        self.twitchSecret = twitchSecret

        self.job_registry: Dict[str, Dict[str, Any]] = self._load_json("jobs.json")

        self.global_stats = StatsTracker()

    async def setup_hook(self) -> None:
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                cog_name = f"cogs.{filename[:-3]}"
                await self.load_extension(cog_name)
                print(f"Loaded extension: {cog_name}")

        raw_guilds = os.getenv("GUILD_IDS", "")
        test_guilds = [int(g_id.strip()) for g_id in raw_guilds.split(",") if g_id.strip()]

        for test_guild in test_guilds:
            guild = discord.Object(id=test_guild)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"Synced {len(synced)} command(s) instantly to guild ID: {test_guild}")

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user} (ID: {self.user.id})")

    async def is_bot_operator(self, guild_id: int, user: discord.Member | discord.User) -> bool:
        return self.config.is_operator(guild_id, user.id) or await bot.is_owner(user)

    async def filter_operators(self, interaction: discord.Interaction) -> bool:
        if not await self.is_bot_operator(interaction.guild.id, interaction.user):
            await interaction.response.send_message("Esta acción está reservada a operadores (si deberías ser operador, avisa a Asper)", ephemeral=True)
            return True
        return False

    async def filter_owner(self, interaction):
        if not await bot.is_owner(interaction.user):
            await interaction.response.send_message(
                "Esta acción solo la puede hacer el dueño del bot (avisa a Asper si quieres hacer algo)", ephemeral=True)
            return True
        return False

    def is_channel_whitelisted(self, guild_id, channel_id):
        return self.config.is_channel_whitelisted(guild_id, channel_id)

    @staticmethod
    def _load_json(path: str) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON file at {path}: {e}.")
        return None

    @staticmethod
    def get_user_active_job(user_id: int) -> str | None:
        with sqlite3.connect("bot_data.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT active_job FROM economy_users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return row[0]

    def get_user_job_perk(self, user_id: int, perk_name: str, default: float) -> float:
        job = self.get_user_active_job(user_id)
        if job is None:
            return default
        return self.get_job_perk(job, perk_name, default, user_id)

    def get_job_perk(self, user_job_id: str, perk_name: str, default: float, user_id: Optional[int] = None) -> float:
        def calc_level(job_level: float, val: float) -> float:
            if perk_name == "job_penalty":
                return val
            if val < 0.0:
                return max((-val) * 0.2, (-val) - (-val) * 0.05 * job_level)
            return val + val * 0.1 * job_level

        level = 1.0
        if user_id:
            with sqlite3.connect("bot_data.db") as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT level FROM economy_jobs WHERE user_id = ? AND job_id = ?",
                               (user_id, user_job_id))
                row = cursor.fetchone()
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

    @staticmethod
    def get_random_phrase(category: str, tag: Optional[str] = None, add_enter: bool = True) -> str:
        with sqlite3.connect("bot_data.db") as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT phrase FROM economy_phrases WHERE category = ? AND (tag IS NULL OR tag = '') ORDER BY RANDOM() LIMIT 1", (category,))
            no_tag_row = cursor.fetchone()
            no_tag_phrase = no_tag_row[0] if no_tag_row else None

            phrases = [no_tag_phrase]

            if tag:
                cursor.execute("SELECT phrase FROM economy_phrases WHERE category = ? AND tag = ? ORDER BY RANDOM() LIMIT 1", (category, tag))
                tagged_row = cursor.fetchone()
                if tagged_row:
                    if no_tag_phrase is None:
                        return tagged_row[0]
                    phrases.append(tagged_row[0])

            choice = random.choice(phrases)
            if choice is None:
                return ""
            return choice + ("\n" if add_enter else "")

if __name__ == "__main__":
    twitchClient = os.getenv("TWITCH_CLIENT")
    twitchSecret = os.getenv("TWITCH_SECRET")
    bot = JoseLuisBot(twitchClient, twitchSecret)
    token = os.getenv("DISCORD_TOKEN")

    if not token:
        print("Missing DISCORD_TOKEN in environment!")
        exit(1)

    bot.run(token)