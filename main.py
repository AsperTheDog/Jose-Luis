import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from db import BotDatabase
from stats import StatsTracker

load_dotenv()

class JoseLuisBot(commands.Bot):
    def __init__(self, twitch_client, twitch_secret):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.moderation = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents
        )
        self.db = BotDatabase()
        asyncio.run(self.db.start())

        self.twitch_client = twitch_client
        self.twitch_secret = twitch_secret

        self.global_stats = StatsTracker(self.db.stats)

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
        return await self.db.guild.is_operator(guild_id, user.id) or await self.is_owner(user)

    async def filter_operators(self, interaction: discord.Interaction) -> bool:
        if not await self.is_bot_operator(interaction.guild.id, interaction.user):
            await interaction.response.send_message("Esta acción está reservada a operadores (si deberías ser operador, avisa a Asper)", ephemeral=True)
            return True
        return False

    async def filter_owner(self, interaction):
        if not await self.is_owner(interaction.user):
            await interaction.response.send_message("Esta acción solo la puede hacer el dueño del bot (avisa a Asper si quieres hacer algo)", ephemeral=True)
            return True
        return False

if __name__ == "__main__":
    twitch_client = os.getenv("TWITCH_CLIENT")
    twitch_secret = os.getenv("TWITCH_SECRET")
    bot = JoseLuisBot(twitch_client, twitch_secret)
    token = os.getenv("DISCORD_TOKEN")

    if not token:
        print("Missing DISCORD_TOKEN in environment!")
        exit(1)

    bot.run(token)