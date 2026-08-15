import asyncio
import datetime

import discord
from discord import app_commands, permissions
from discord.ext import commands

from main import ScalableBot


class ModerationCog(commands.Cog):
    moderation_group = app_commands.Group(
        name="moderación",
        description="Herramientas para moderadores"
    )

    def __init__(self, bot: ScalableBot):
        self.bot = bot

    @moderation_group.command(name="honeypot", description="Pone el canal actual como honeypot y manda un aviso")
    async def honeypot(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        self.bot.config.set("death_channel_id", interaction.channel.id)
        embed = discord.Embed(
            title="⚠️ ¡CANAL TRAMPA! ⚠️",
            description=(
                "**¡NO ESCRIBAS EN ESTE CANAL BAJO NINGÚN CONCEPTO!**\n\n"
                "Este canal está diseñado exclusivamente como trampa para **detectar y mutear automáticamente a bots de spam** "
                "que envían mensajes masivos en todos los canales del servidor."
            ),
            color=discord.Color.red()
        )

        embed.add_field(
            name=":borjapMie2: ¿Eres un usuario real?",
            value="Si has entrado aquí por error, simplemente ignora o silencia este canal y ve a disfrutar de los otros 20000 canales que tiene el server.",
            inline=False
        )

        embed.set_footer(text="Sistema de Seguridad Automático • Canal Protegido")
        await interaction.response.send_message(embed=embed)
        return

    @moderation_group.command(name="nohoneypot", description="Quita el canal de honeypot")
    async def nohoneypot(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        channel = self.bot.get_channel(int(self.bot.config.get("death_channel_id")))
        if channel is None:
            await interaction.response.send_message("No hay ningún honeypot configurado", ephemeral=True)
            return
        self.bot.config.set("death_channel_id", None)
        await interaction.response.send_message("Eliminado el canal honeypot: ", ephemeral=True)

    @moderation_group.command(name="setadminchannel", description="Establece este canal como el canal de administración")
    async def setadminchannel(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        self.bot.config.set("admin_channel_id", interaction.channel.id)
        await interaction.response.send_message("Establecido este canal como canal de administración")

    @moderation_group.command(name="addoperator", description="Añade a un usuario como operador")
    async def addoperator(self, interaction: discord.Interaction, user: discord.Member):
        if await self.bot.filter_owner(interaction): return

        if await self.bot.is_owner(interaction.user) or not self.bot.config.add_to_list("operators", user.id):
            await interaction.response.send_message("Esta persona ya es operadora")
            return
        await interaction.response.send_message(f"Añadido {user.mention} como operador")

    @moderation_group.command(name="removeoperator", description="Elimina a un usuario como operador")
    async def removeoperator(self, interaction: discord.Interaction, user: discord.Member):
        if await self.bot.filter_owner(interaction): return

        if await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("¿Qué haces, payaso? No puedes quitar como operador al dueño del bot ¿Te crees que esto es una democracia?")
            return

        if not self.bot.config.remove_from_list("operators", user.id):
            await interaction.response.send_message("Esta persona no es operadora")
            return
        await interaction.response.send_message(f"Quitado {user.mention} como operador")

    @moderation_group.command(name="whitelist", description="Añade un canal a la lista blanca")
    async def whitelist(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        if not self.bot.config.add_to_list("channel_whitelist", interaction.channel.id):
            await interaction.response.send_message("Este canal ya está en la lista blanca")
            return
        await interaction.response.send_message("Ahora estaré activo en este canal")

    @moderation_group.command(name="unwhitelist", description="Quita un canal de la lista blanca")
    async def unwhitelist(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        if not self.bot.config.remove_from_list("channel_whitelist", interaction.channel.id):
            await interaction.response.send_message("Este canal no está en la lista blanca")
            return
        await interaction.response.send_message("Ya no estaré activo en este canal")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        death_channel_id = int(self.bot.config.get("death_channel_id"))
        if message.channel.id != death_channel_id:
            return

        grace_seconds = self.bot.config.get_float("death_grace_seconds", fallback=60)
        duration = datetime.timedelta(seconds=grace_seconds)
        unban_deadline = datetime.datetime.now(datetime.timezone.utc) + duration

        try:
            await message.author.timeout(duration, reason=f"Escribir en canal de muerte. Tienes {grace_seconds} segundos para contactar a un mod si esto fue por error antes de ser baneado")
            await message.delete()

            admin_channel_id = int(self.bot.config.get("admin_channel_id"))
            admin_channel = message.guild.get_channel(admin_channel_id)

            if admin_channel:
                rel_time = discord.utils.format_dt(unban_deadline, style="R")
                await admin_channel.send(
                    f"**Atención Mods:** El usuario {message.author.mention} ha escrito en el canal de muerte.\n"
                    f"Ha sido muteado y será baneado automáticamente {rel_time} a menos que le retiréis el timeout."
                )

            await asyncio.sleep(grace_seconds)
            member = await message.guild.fetch_member(message.author.id)

            if member and member.is_timed_out():
                await member.ban(reason="Canal de muerte. Ban automático, si esto fue por error por favor contacta con un moderador")
                if admin_channel:
                    await admin_channel.send(f"El usuario **{member}** ({member.mention}) ha sido baneado automáticamente.")

        except discord.Forbidden:
            print(f"Error de permisos: No se pudo silenciar/banear a {message.author}.")
        except discord.NotFound:
            print(f"El usuario {message.author} ya no se encuentra en el servidor.")



async def setup(bot: ScalableBot):
    await bot.add_cog(ModerationCog(bot))