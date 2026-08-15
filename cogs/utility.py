import discord
from discord import app_commands
from discord.ext import commands

from main import ScalableBot


class UtilityCog(commands.Cog):
    utility_group = app_commands.Group(
        name="utilidades",
        description="Comandos con distintas utilidades"
    )

    def __init__(self, bot: ScalableBot):
        self.bot = bot

    @utility_group.command(name="ping", description="Prueba la latencia del bot")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"Pong! *{round(self.bot.latency * 1000)}ms*")

    @utility_group.command(name="apagar", description="Apagar el bot (se va a reiniciar)")
    async def shutdown(self, interaction: discord.Interaction):
        if await self.bot.filter_owner(interaction): return

        await interaction.response.send_message("Shutting down...", ephemeral=True)
        await interaction.client.close()

    @utility_group.command(name="dumpconfig", description="Dumps the contents of config.cfg")
    async def dumpconfig(self, interaction: discord.Interaction):
        if await self.bot.filter_owner(interaction): return

        try:
            with open("config.cfg", "r", encoding="utf-8") as f:
                content = f.read()

            if len(content) > 1900:
                await interaction.response.send_message("Config file is too long for a message, sending as file:", file=discord.File("config.cfg"))
            else:
                await interaction.response.send_message(f"```ini\n{content}\n```")

        except FileNotFoundError:
            await interaction.response.send_message("`config.cfg` was not found.", ephemeral=True)

async def setup(bot: ScalableBot):
    await bot.add_cog(UtilityCog(bot))