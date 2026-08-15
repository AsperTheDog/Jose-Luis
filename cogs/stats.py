import asyncio
import re
import sqlite3
from typing import Optional, Tuple
import discord
from discord import app_commands
from discord.ext import commands

DB_PATH = "user_stats.db"

EMOJI_REGEX = re.compile(r"<a?:[a-zA-Z0-9_]+:[0-9]+>|[\U00010000-\U0010ffff]")


class StatsCog(commands.Cog):
    stats_group = app_commands.Group(
        name="estadísticas",
        description="Comandos para mirar las estadísticas de jugadores y los rankings"
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._init_db()

    @staticmethod
    def _init_db():
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_stats (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    messages INTEGER DEFAULT 0,
                    xp INTEGER DEFAULT 0,
                    words INTEGER DEFAULT 0,
                    chars INTEGER DEFAULT 0,
                    attachments INTEGER DEFAULT 0,
                    emojis INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            conn.commit()

    @staticmethod
    async def _db_execute(query: str, params: tuple = ()) -> None:
        def query_runner():
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()

        await asyncio.to_thread(query_runner)

    @staticmethod
    async def _db_fetchone(query: str, params: tuple = ()) -> Optional[tuple]:
        def query_runner():
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchone()

        return await asyncio.to_thread(query_runner)

    @staticmethod
    async def _db_fetchall(query: str, params: tuple = ()) -> list:
        def query_runner():
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchall()

        return await asyncio.to_thread(query_runner)

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
        if not message.guild:
            return

        content = message.content or ""
        word_count = len(content.split())
        char_count = len(content)
        attachment_count = len(message.attachments)
        emoji_count = len(EMOJI_REGEX.findall(content))

        xp_gained = 10 + min(word_count, 25)

        query = """
            INSERT INTO user_stats (guild_id, user_id, messages, xp, words, chars, attachments, emojis)
            VALUES (?, ?, 1, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                messages = messages + 1,
                xp = xp + excluded.xp,
                words = words + excluded.words,
                chars = chars + excluded.chars,
                attachments = attachments + excluded.attachments,
                emojis = emojis + excluded.emojis
        """
        params = (
            message.guild.id,
            message.author.id,
            xp_gained,
            word_count,
            char_count,
            attachment_count,
            emoji_count,
        )
        await self._db_execute(query, params)

    @stats_group.command(name="stats", description="Muestra las estadísticas de un usuario")
    @app_commands.describe(user="Usuario a consultar (por defecto tú)")
    async def stats(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        target = user or interaction.user

        row = await self._db_fetchone(
            "SELECT messages, xp, words, chars, attachments, emojis FROM user_stats WHERE guild_id = ? AND user_id = ?",
            (interaction.guild_id, target.id),
        )

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

        query = f"""
            SELECT user_id, {category}, xp FROM user_stats
            WHERE guild_id = ?
            ORDER BY {category} DESC
            LIMIT 10
        """
        rows = await self._db_fetchall(query, (interaction.guild_id,))

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


async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCog(bot))