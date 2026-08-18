import discord
import random
import sqlite3
from typing import List, Dict
from discord import app_commands
from discord.ext import commands

from main import JoseLuisBot


class ListasCog(commands.Cog):
    listas_group = app_commands.Group(
        name="frases_chistes",
        description="Comandos para que Jose Luis diga cosas graciosas"
    )

    def __init__(self, bot: JoseLuisBot):
        self.bot = bot
        self.db_path = "bot_data.db"

        self._recent_history: Dict[str, List[str]] = {"frase": [], "chiste": []}

        self._init_sqlite()

    def _init_sqlite(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                           CREATE TABLE IF NOT EXISTS text_lists
                           (
                               id       INTEGER PRIMARY KEY AUTOINCREMENT,
                               category TEXT NOT NULL,
                               content  TEXT NOT NULL,
                               UNIQUE (category, content)
                           )
                           """)
            conn.commit()

    def _pick_random(self, category: str, history_ratio: float = 0.4) -> str:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT content FROM text_lists WHERE category = ?", (category,))
            rows = cursor.fetchall()

        if not rows:
            return "FALLO: No hay nada aquí entre lo que elegir..."

        candidates = [row[0] for row in rows]
        if len(candidates) == 1:
            return candidates[0]

        max_history_len = max(1, min(len(candidates) - 1, int(len(candidates) * history_ratio)))
        history = self._recent_history[category]

        available = [item for item in candidates if item not in history]

        if not available:
            history.clear()
            available = candidates

        chosen = random.choice(available)
        history.append(chosen)

        if len(history) > max_history_len:
            history.pop(0)

        return chosen

    def _add_item(self, category: str, content: str) -> bool:
        content = content.strip()
        if not content:
            return False

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO text_lists (category, content) VALUES (?, ?)",
                    (category, content)
                )
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def _remove_item(self, category: str, content: str) -> bool:
        content = content.strip()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM text_lists WHERE category = ? AND content = ?",
                (category, content)
            )
            deleted = cursor.rowcount > 0
            conn.commit()

        # Si se borró, lo quitamos también del historial reciente para evitar errores
        if deleted and content in self._recent_history[category]:
            self._recent_history[category].remove(content)

        return deleted

    @listas_group.command(name="frase", description="Borja di tu frase!")
    async def frase(self, interaction: discord.Interaction):
        await interaction.response.send_message(self._pick_random("frase"))

    @listas_group.command(name="meterfrase", description="Mete una frase en la lista de frases de borja")
    async def meterfrase(self, interaction: discord.Interaction, frase: str):
        if await self.bot.filter_operators(interaction): return

        if not self._add_item("frase", frase):
            await interaction.response.send_message("Esa frase ya estaba en la lista")
        else:
            await interaction.response.send_message(f"Añadida a la lista: '{frase}'")

    @listas_group.command(name="quitarfrase", description="Quita una frase de la lista de frases de borja")
    async def quitarfrase(self, interaction: discord.Interaction, frase: str):
        if await self.bot.filter_operators(interaction): return

        if not self._remove_item("frase", frase):
            await interaction.response.send_message("Esa frase no está en la lista")
        else:
            await interaction.response.send_message(f"Eliminada de la lista: '{frase}'")

    @listas_group.command(name="recargarfrases", description="Limpia el historial para permitir repeticiones")
    async def recargarfrases(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return
        self._recent_history["frase"].clear()
        # Se añade un mensaje de respuesta para que la interacción no de error en Discord
        await interaction.response.send_message("Historial de frases reseteado.", ephemeral=True)

    @listas_group.command(name="chiste", description="Cuenta un chiste")
    async def chiste(self, interaction: discord.Interaction):
        await interaction.response.send_message(self._pick_random("chiste"))

    @listas_group.command(name="meterchiste", description="Mete un chiste en la lista de chistes")
    async def meterchiste(self, interaction: discord.Interaction, chiste: str):
        if await self.bot.filter_operators(interaction): return

        if not self._add_item("chiste", chiste):
            await interaction.response.send_message("Ese chiste ya estaba en la lista")
        else:
            await interaction.response.send_message(f"Añadido a la lista: '{chiste}'")

    @listas_group.command(name="quitarchiste", description="Quita un chiste de la lista de chistes")
    async def quitarchiste(self, interaction: discord.Interaction, chiste: str):
        if await self.bot.filter_operators(interaction): return

        if not self._remove_item("chiste", chiste):
            await interaction.response.send_message("Ese chiste no está en la lista")
        else:
            await interaction.response.send_message(f"Eliminado de la lista: '{chiste}'")

    @listas_group.command(name="recargarchistes", description="Limpia el historial para permitir repeticiones")
    async def recargarchistes(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return
        self._recent_history["chiste"].clear()
        await interaction.response.send_message("Historial de chistes reseteado.", ephemeral=True)


async def setup(bot: JoseLuisBot):
    await bot.add_cog(ListasCog(bot))