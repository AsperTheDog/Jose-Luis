import re
from typing import Optional, Tuple
import discord
from discord import app_commands
from discord.ext import commands

from main import JoseLuisBot

EMOJI_REGEX = re.compile(r"<a?:[a-zA-Z0-9_]+:[0-9]+>|[\U00010000-\U0010ffff]")


class StatsCog(commands.Cog):
    stats_group = app_commands.Group(
        name="actividad",
        description="Comandos para mirar las estadísticas de actividad de los jugadores y sus rankings"
    )

    def __init__(self, bot: JoseLuisBot):
        self.bot = bot

    @staticmethod
    def calculate_level_and_progress(xp: int) -> Tuple[int, int, int]:
        level = 1
        xp_needed = 100  # Level 1 requirement

        while xp >= xp_needed:
            xp -= xp_needed
            level += 1
            xp_needed = level * 100

        return level, xp, xp_needed

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        content = message.content or ""
        word_count = len(content.split())
        char_count = len(content)
        attachment_count = len(message.attachments)
        emoji_count = len(EMOJI_REGEX.findall(content))

        xp_gained = 10 + min(word_count, 25)

        if not message.guild:
            print(f"Mensaje enviado sin gremio por {message.author.name} en {message.channel.id}")
            return
        await self.bot.db.activity_update_user_stats(message.guild.id, message.author.id, xp_gained, word_count, char_count, attachment_count, emoji_count)

    @stats_group.command(name="stats", description="Muestra las estadísticas de un usuario")
    @app_commands.describe(user="Usuario a consultar (por defecto tú)")
    async def stats(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        target = user or interaction.user

        row = await self.bot.db.activity_get_user_stats(interaction.guild, interaction.user)
        if not row:
            await interaction.response.send_message(f"**{target.display_name}** aún no tiene estadísticas registradas.", ephemeral=True)
            return

        messages, xp, words, chars, attachments, emojis = row
        level, current_level_xp, next_level_xp = self.calculate_level_and_progress(xp)

        progress_ratio = current_level_xp / next_level_xp
        filled_length = int(progress_ratio * 10)
        bar = "█" * filled_length + "░" * (10 - filled_length)

        embed = discord.Embed(
            title=f"Estadísticas de {target.display_name}",
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(
            name=f"Nivel {level}",
            value=f"`[{bar}]` {current_level_xp}/{next_level_xp} XP (Total: {xp:,})",
            inline=False,
        )

        embed.add_field(name="Mensajes", value=f"`{messages:,}`", inline=True)
        embed.add_field(name="Palabras", value=f"`{words:,}`", inline=True)
        embed.add_field(name="Caracteres", value=f"`{chars:,}`", inline=True)

        embed.add_field(name="Archivos / Img", value=f"`{attachments:,}`", inline=True)
        embed.add_field(name="Emojis Usados", value=f"`{emojis:,}`", inline=True)

        avg_words = round(words / messages, 1) if messages > 0 else 0
        embed.add_field(name="Media Palabras/Msg", value=f"`{avg_words}`", inline=True)

        await interaction.response.send_message(embed=embed)

    @stats_group.command(name="leaderboard", description="Muestra la clasificación del servidor")
    @app_commands.choices(
        metric=[
            app_commands.Choice(name="Nivel / XP", value="xp"),
            app_commands.Choice(name="Mensajes Enviados", value="messages"),
            app_commands.Choice(name="Palabras Habladas", value="words"),
            app_commands.Choice(name="Archivos Adjuntos", value="attachments"),
        ]
    )
    async def leaderboard(self, interaction: discord.Interaction, metric: app_commands.Choice[str]):
        category = metric.value
        title_map = {
            "xp": "Nivel y XP",
            "messages": "Mensajes Enviados",
            "words": "Palabras Habladas",
            "attachments": "Archivos Adjuntos",
        }

        rows = await self.bot.db.activity_get_top_users_by_category(interaction.guild.id, category)

        if not rows:
            await interaction.response.send_message("Aún no hay datos para el leaderboard.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Top 10 - {title_map[category]}",
            color=discord.Color.gold(),
        )

        description = ""
        medals = ["🥇", "🥈", "🥉"]

        for idx, (user_id, value, total_xp) in enumerate(rows, start=1):
            icon = medals[idx - 1] if idx <= 3 else f"`#{idx}`"
            member = interaction.guild.get_member(user_id)
            user_name = member.mention if member else f"Usuario ({user_id})"

            if category == "xp":
                level, _, _ = self.calculate_level_and_progress(total_xp)
                description += f"{icon} {user_name} — **Nivel {level}** ({total_xp:,} XP)\n"
            else:
                description += f"{icon} {user_name} — **{value:,}** {category}\n"

        embed.description = description
        await interaction.response.send_message(embed=embed)


async def setup(bot: JoseLuisBot):
    await bot.add_cog(StatsCog(bot))