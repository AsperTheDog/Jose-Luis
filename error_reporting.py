import io
import json
import traceback
from typing import Optional, Tuple

import discord

MAX_TRACEBACK_EMBED_CHARS = 3000
MAX_FIELD_CHARS = 1024
MAX_DESCRIPTION_CHARS = 4096


def format_exception(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def describe_arguments(interaction: discord.Interaction) -> Optional[str]:
    data = interaction.data
    if not isinstance(data, dict):
        return None

    options = data.get("options")
    if options:
        try:
            return json.dumps(options, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return repr(options)

    target_id = data.get("target_id")
    if target_id:
        return f"target_id={target_id}"
    return None


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _describe_user(user: Optional[discord.abc.User]) -> str:
    if user is None:
        return "Desconocido"
    return f"{user} (`{user.id}`)"


def _describe_guild(guild: Optional[discord.Guild]) -> str:
    if guild is None:
        return "DM / Desconocido"
    return f"{guild.name} (`{guild.id}`)"


def _describe_channel(channel: Optional[discord.abc.Messageable]) -> str:
    if channel is None:
        return "Desconocido"
    mention = getattr(channel, "mention", None)
    name = getattr(channel, "name", None)
    label = mention or (f"#{name}" if name else str(channel))
    return f"{label} (`{getattr(channel, 'id', '?')}`)"


def build_error_payload(
    *,
    source: str,
    command_name: str,
    error: BaseException,
    traceback_text: str,
    user: Optional[discord.abc.User] = None,
    guild: Optional[discord.Guild] = None,
    channel: Optional[discord.abc.Messageable] = None,
    arguments: Optional[str] = None,
) -> Tuple[discord.Embed, Optional[discord.File]]:
    summary = f"{type(error).__name__}: {error}"
    body = _clip(traceback_text, MAX_TRACEBACK_EMBED_CHARS)

    embed = discord.Embed(
        title="Excepción no controlada en un comando",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow(),
        description=_clip(f"**{summary}**\n```py\n{body}\n```", MAX_DESCRIPTION_CHARS),
    )
    embed.add_field(name="Comando", value=_clip(f"`{command_name}` ({source})", MAX_FIELD_CHARS), inline=True)
    embed.add_field(name="Usuario", value=_clip(_describe_user(user), MAX_FIELD_CHARS), inline=True)
    embed.add_field(name="Servidor", value=_clip(_describe_guild(guild), MAX_FIELD_CHARS), inline=True)
    embed.add_field(name="Canal", value=_clip(_describe_channel(channel), MAX_FIELD_CHARS), inline=True)
    if arguments:
        safe_arguments = arguments.replace("```", "'''")
        embed.add_field(name="Argumentos", value=_clip(f"```\n{safe_arguments}\n```", MAX_FIELD_CHARS), inline=False)

    file = None
    if len(traceback_text) > MAX_TRACEBACK_EMBED_CHARS:
        file = discord.File(io.BytesIO(traceback_text.encode("utf-8")), filename="traceback.txt")

    return embed, file
