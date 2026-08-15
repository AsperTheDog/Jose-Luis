import discord
from discord import app_commands
from discord.ext import commands

from main import ScalableBot


class ListasCog(commands.Cog):
    listas_group = app_commands.Group(
        name="frases_chistes",
        description="Comandos para que Jose Luis diga cosas graciosas"
    )

    def __init__(self, bot: ScalableBot):
        self.bot = bot

    @listas_group.command(name="frase", description="Borja di tu frase!")
    async def frase(self, interaction: discord.Interaction):
        await interaction.response.send_message(self.bot.borjaFrases.pick_random())

    @listas_group.command(name="meterfrase", description="Mete una frase en la lista de frases de borja")
    async def meterfrase(self, interaction: discord.Interaction, frase: str):
        if await self.bot.filter_operators(interaction): return

        if not self.bot.borjaFrases.add(frase):
            await interaction.response.send_message("Esa frase ya estaba en la lista")
        else:
            await interaction.response.send_message(f"Añadida a la lista: '{frase}'")

    @listas_group.command(name="quitarfrase", description="Quita una frase de la lista de frases de borja")
    async def quitarfrase(self, interaction: discord.Interaction, frase: str):
        if await self.bot.filter_operators(interaction): return

        if not self.bot.borjaFrases.remove(frase):
            await interaction.response.send_message("Esa frase no está en la lista")
        else:
            await interaction.response.send_message(f"Eliminada de la lista: '{frase}'")

    @listas_group.command(name="recargarfrases", description="Mete una frase en la lista de frases de borja")
    async def recargarfrases(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return
        self.bot.borjaFrases._load_from_disk()

    @listas_group.command(name="chiste", description="Cuenta un chiste")
    async def chiste(self, interaction: discord.Interaction):
        await interaction.response.send_message(self.bot.chistes.pick_random())

    @listas_group.command(name="meterchiste", description="Mete una frase en la lista de chistes")
    async def meterchiste(self, interaction: discord.Interaction, chiste: str):
        if await self.bot.filter_operators(interaction): return

        if not self.bot.chistes.add(chiste):
            await interaction.response.send_message("Ese chiste ya estaba en la lista")
        else:
            await interaction.response.send_message(f"Añadido a la lista: '{chiste}'")

    @listas_group.command(name="quitarchiste", description="Quita una frase de la lista de chistes")
    async def quitarchiste(self, interaction: discord.Interaction, chiste: str):
        if await self.bot.filter_operators(interaction): return

        if not self.bot.chistes.remove(chiste):
            await interaction.response.send_message("Ese chiste no está en la lista")
        else:
            await interaction.response.send_message(f"Eliminado de la lista: '{chiste}'")

    @listas_group.command(name="recargarchistes", description="Mete una frase en la lista de chistes")
    async def recargarchistes(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return
        self.bot.chistes._load_from_disk()


async def setup(bot: ScalableBot):
    await bot.add_cog(ListasCog(bot))