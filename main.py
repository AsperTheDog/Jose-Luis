import asyncio
import logging
import os
import sys
import traceback

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from db import BotDatabase
from error_reporting import build_error_payload, describe_arguments, format_exception
from stats import StatsTracker

load_dotenv()


def _unwrap_command_exception(error: BaseException) -> BaseException | None:
    original = getattr(error, "original", None)
    if isinstance(original, BaseException):
        return original

    cause = error.__cause__
    if isinstance(cause, BaseException) and not isinstance(cause, app_commands.AppCommandError):
        return cause
    return None

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
        self.tree.on_error = self.on_app_command_error

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

    async def process_commands(self, message: discord.Message) -> None:
        return

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

    async def _get_debug_channel(self, guild: discord.Guild) -> discord.abc.Messageable | None:
        try:
            channel_id = await self.db.guild.get(guild.id, "debug_channel_id")
        except Exception as error:
            print(f"[Error] No se pudo leer el canal de debug del servidor {guild.id}: {error}", file=sys.stderr)
            return None

        if not channel_id:
            return None

        channel = guild.get_channel_or_thread(channel_id)
        if channel is not None:
            return channel

        try:
            return await self.fetch_channel(channel_id)
        except discord.HTTPException as error:
            print(f"[Error] No se pudo obtener el canal de debug {channel_id}: {error}", file=sys.stderr)
            return None

    def _log_command_exception(self, error: BaseException, source: str, command_name: str) -> None:
        print(f"[Error] El comando {source} '{command_name}' lanzó una excepción no controlada:", file=sys.stderr)
        traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)

    async def report_exception(
        self,
        error: BaseException,
        *,
        source: str,
        command_name: str,
        guild: discord.Guild | None,
        user: discord.abc.User | None,
        channel: discord.abc.Messageable | None,
        arguments: str | None = None,
    ) -> None:
        traceback_text = format_exception(error)
        self._log_command_exception(error, source, command_name)

        if guild is None:
            return

        target = await self._get_debug_channel(guild)
        if target is None:
            return

        embed, file = build_error_payload(
            source=source,
            command_name=command_name,
            error=error,
            traceback_text=traceback_text,
            user=user,
            guild=guild,
            channel=channel,
            arguments=arguments,
        )
        try:
            await target.send(embed=embed, file=file)
        except discord.HTTPException as send_error:
            print(f"[Error] No se pudo enviar el error al canal de debug {getattr(target, 'id', '?')}: {send_error}", file=sys.stderr)

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = _unwrap_command_exception(error)
        if original is None:
            logging.getLogger("discord").error("Ignoring exception in app command", exc_info=error)
            return

        command = interaction.command
        name = getattr(command, "qualified_name", None) or getattr(command, "name", None) or "desconocido"
        source = "menú contextual" if isinstance(command, app_commands.ContextMenu) else "slash"

        await self.report_exception(
            original,
            source=source,
            command_name=name,
            guild=interaction.guild,
            user=interaction.user,
            channel=interaction.channel,
            arguments=describe_arguments(interaction),
        )

if __name__ == "__main__":
    twitch_client = os.getenv("TWITCH_CLIENT")
    twitch_secret = os.getenv("TWITCH_SECRET")
    bot = JoseLuisBot(twitch_client, twitch_secret)
    token = os.getenv("DISCORD_TOKEN")

    if not token:
        print("Missing DISCORD_TOKEN in environment!")
        exit(1)

    bot.run(token)