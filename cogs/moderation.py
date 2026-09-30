import asyncio
import datetime
import re
from typing import Optional

import discord
from discord import app_commands, permissions
from discord.ext import commands

from db.repositories.merge import MergeReport
from main import JoseLuisBot

MERGE_GROUPS = (
    ("Economía", ("economy_", "horse_bets", "hacking_daily")),
    ("Gacha", ("gacha_",)),
    ("Minería", ("mining_",)),
    ("Mazmorra", ("dungeon_",)),
    ("Waifu", ("waifu_",)),
    ("Estadísticas", ("user_stats", "user_global_stats")),
    ("Recordatorios y moderación", ("reminders", "reminder_subscribers", "quarantine")),
)

HIGHLIGHT_LABELS = {
    "balance": "Choskris",
    "interest": "Intereses sin reclamar",
    "gacha_dust": "Polvo de gacha",
    "dungeon_gold": "Oro de mazmorra",
    "dungeon_dust": "Polvo de mazmorra",
    "boss_coins": "Monedas de jefe",
    "waifu_value": "Valor de waifu",
}


def merge_group_label(table: str) -> str:
    for label, prefixes in MERGE_GROUPS:
        if table.startswith(prefixes):
            return label
    return "Otros"


def merge_summary(counts: dict[str, int]) -> str:
    groups: dict[str, int] = {}
    for table, count in counts.items():
        label = merge_group_label(table)
        groups[label] = groups.get(label, 0) + count
    return "\n".join(f"**{label}:** {count} fila(s)" for label, count in groups.items())


def merge_embed(report: MergeReport, principal: discord.User, secundaria: discord.User) -> discord.Embed:
    embed = discord.Embed(
        title="🧬 Cuentas fusionadas",
        description=f"Todos los datos de {secundaria.mention} se han traspasado a {principal.mention} y la cuenta secundaria se ha borrado.",
        color=discord.Color.dark_green(),
    )
    if report.highlights:
        embed.add_field(
            name="Saldos absorbidos",
            value="\n".join(f"**{HIGHLIGHT_LABELS.get(key, key)}:** {value:,}" for key, value in report.highlights.items()),
            inline=False,
        )
    embed.add_field(name="Filas absorbidas", value=merge_summary(report.absorbed), inline=False)
    if report.notes:
        embed.add_field(name="Avisos", value="\n".join(f"• {note}" for note in report.notes), inline=False)
    embed.add_field(
        name="Permisos",
        value="Los permisos de operador y la lista blanca de canales son por servidor: no se han tocado. Revísalos a mano si la cuenta secundaria tenía alguno.",
        inline=False,
    )
    embed.set_footer(text="Acción irreversible")
    return embed


class MergeAccountsView(discord.ui.View):
    def __init__(self, bot: JoseLuisBot, author_id: int, principal: discord.User, secundaria: discord.User):
        super().__init__(timeout=120)
        self.bot = bot
        self.author_id = author_id
        self.principal = principal
        self.secundaria = secundaria

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Solo quien ejecutó el comando puede confirmar esto.", color=discord.Color.red()),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Fusionar y borrar", style=discord.ButtonStyle.danger, emoji="🧬")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(description="⏳ Fusionando cuentas...", color=discord.Color.orange()),
            view=self,
        )
        try:
            report = await self.bot.db.merger.merge(self.principal.id, self.secundaria.id)
        except Exception as error:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="❌ La fusión ha fallado",
                    description=f"```{error}```\nNo se ha modificado ninguna de las dos cuentas.",
                    color=discord.Color.red(),
                ),
                view=None,
            )
            raise
        self.bot.dispatch("account_merged", report.primary_id, report.secondary_id)
        await interaction.edit_original_response(embed=merge_embed(report, self.principal, self.secundaria), view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(description="❌ Fusión cancelada. No se ha modificado ninguna cuenta.", color=discord.Color.greyple()),
            view=self,
        )


class ModerationCog(commands.Cog):
    moderation_group = app_commands.Group(
        name="moderación",
        description="Herramientas para moderadores"
    )

    def __init__(self, bot: JoseLuisBot):
        self.bot = bot

    @moderation_group.command(name="honeypot", description="Pone el canal actual como honeypot y manda un aviso")
    async def honeypot(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        await self.bot.db.guild.set(interaction.guild.id, "death_channel_id", interaction.channel.id)
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
            name="¿Eres un usuario real?",
            value="Si has entrado aquí por error, simplemente ignora o silencia este canal y ve a disfrutar de los otros 20000 canales que tiene el server.",
            inline=False
        )

        embed.set_footer(text="Sistema de Seguridad Automático • Canal Protegido")
        await interaction.response.send_message(embed=embed)
        return

    @moderation_group.command(name="nohoneypot", description="Quita el canal de honeypot")
    async def nohoneypot(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        channel = self.bot.get_channel(int(await self.bot.db.guild.get(interaction.guild.id, "death_channel_id")))
        if channel is None:
            await interaction.response.send_message("No hay ningún honeypot configurado", ephemeral=True)
            return
        await self.bot.db.guild.set(interaction.guild.id, "death_channel_id", 0)
        await interaction.response.send_message(f"Eliminado el canal honeypot: {interaction.channel.mention}", ephemeral=True)

    @moderation_group.command(name="setadminchannel", description="Establece este canal como el canal de administración")
    async def setadminchannel(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        await self.bot.db.guild.set(interaction.guild.id, "admin_channel_id", interaction.channel.id)
        await interaction.response.send_message("Establecido este canal como canal de administración")

    @moderation_group.command(name="addoperator", description="Añade a un usuario como operador")
    async def addoperator(self, interaction: discord.Interaction, user: discord.Member):
        if await self.bot.filter_owner(interaction): return

        if await self.bot.is_owner(user) or not await self.bot.db.guild.add_operator(interaction.guild.id, user.id):
            await interaction.response.send_message("Esta persona ya es operadora")
            return
        await interaction.response.send_message(f"Añadido {user.mention} como operador")

    @moderation_group.command(name="removeoperator", description="Elimina a un usuario como operador")
    async def removeoperator(self, interaction: discord.Interaction, user: discord.Member):
        if await self.bot.filter_owner(interaction): return

        if await self.bot.is_owner(user):
            await interaction.response.send_message("¿Qué haces, payaso? No puedes quitar como operador al dueño del bot ¿Te crees que esto es una democracia?")
            return

        if not await self.bot.db.guild.remove_operator(interaction.guild.id, user.id):
            await interaction.response.send_message("Esta persona no es operadora")
            return
        await interaction.response.send_message(f"Quitado {user.mention} como operador")

    @moderation_group.command(name="whitelist", description="Añade un canal a la lista blanca")
    async def whitelist(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        if not await self.bot.db.guild.add_to_channel_whitelist(interaction.guild.id, interaction.channel.id):
            await interaction.response.send_message("Este canal ya está en la lista blanca")
            return
        await interaction.response.send_message("Ahora estaré activo en este canal")

    @moderation_group.command(name="unwhitelist", description="Quita un canal de la lista blanca")
    async def unwhitelist(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        if not await self.bot.db.guild.remove_from_channel_whitelist(interaction.guild.id, interaction.channel.id):
            await interaction.response.send_message("Este canal no está en la lista blanca")
            return
        await interaction.response.send_message("Ya no estaré activo en este canal")

    @moderation_group.command(name="operadores", description="Da la lista de operadores")
    async def operators(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        operators = [int(userID) for userID in await self.bot.db.guild.get_operators(interaction.guild.id)]

        users = []
        for userID in operators:
            try:
                users.append(await interaction.guild.fetch_member(userID))
            except discord.NotFound:
                pass

        owner = await interaction.guild.fetch_member(self.bot.owner_id)

        formatted_list = "• " + owner.mention + " (dueño)\n"
        formatted_list += "\n".join(f"• {op.mention}" for op in users)

        embed = discord.Embed( title="Operadores", description=formatted_list, color=discord.Color.blue())
        await interaction.response.send_message(embed=embed)

    @staticmethod
    def _extract_message_id(input_str: str) -> int:
        match = re.search(r'(\d+)/?$', input_str.strip())
        if match:
            return int(match.group(1))
        raise ValueError("ID o enlace de mensaje no válido.")

    @moderation_group.command(name="purgarpormensajes", description="Borra mensajes desde un mensaje base hasta el final o hasta un segundo mensaje.")
    @app_commands.describe(mensaje_inicio="ID o enlace del mensaje más antiguo a partir del cual borrar", mensaje_fin="Opcional: ID o enlace del mensaje más reciente hasta el cual borrar")
    async def purgarpormensajes(self, interaction: discord.Interaction, mensaje_inicio: str, mensaje_fin: str = None):
        if await self.bot.filter_operators(interaction): return
        await interaction.response.defer(ephemeral=True)

        try:
            id_inicio = self._extract_message_id(mensaje_inicio)
            msg_inicio = await interaction.channel.fetch_message(id_inicio)

            after_target = discord.Object(id=msg_inicio.id - 1)

            before_target = None
            if mensaje_fin:
                id_fin = self._extract_message_id(mensaje_fin)
                msg_fin = await interaction.channel.fetch_message(id_fin)
                before_target = discord.Object(id=msg_fin.id + 1)

            deleted = await interaction.channel.purge(after=after_target, before=before_target, oldest_first=True)

            await interaction.followup.send(f"Se han eliminado **{len(deleted)}** mensajes correctamente.", ephemeral=True)

        except discord.NotFound:
            await interaction.followup.send("No se encontró alguno de los mensajes especificados en este canal.", ephemeral=True)
        except ValueError:
            await interaction.followup.send("Formato de ID o enlace de mensaje no válido.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error al ejecutar el borrado: {e}", ephemeral=True)

    @moderation_group.command(name="purgarpornumero", description="Borra una cantidad específica de mensajes recientes.")
    @app_commands.describe(cantidad="Número de mensajes a eliminar")
    async def purgarpornumero(self, interaction: discord.Interaction, cantidad: int):
        if await self.bot.filter_operators(interaction): return
        if cantidad <= 0:
            await interaction.response.send_message("Debes indicar un número mayor a 0.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        deleted = await interaction.channel.purge(limit=cantidad)
        await interaction.followup.send(f"Se han eliminado **{len(deleted)}** mensajes.", ephemeral=True)

    @moderation_group.command(name="purgarporintervalo", description="Borra los mensajes enviados dentro de un intervalo de segundos hacia atrás.")
    @app_commands.describe(segundos="Intervalo en segundos (ej: 600 para borrado de los últimos 10 minutos)")
    async def purgarporintervalo(self, interaction: discord.Interaction, segundos: int):
        if await self.bot.filter_operators(interaction): return
        if segundos <= 0:
            await interaction.response.send_message("El intervalo debe ser mayor a 0 segundos.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        desde = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=segundos)

        deleted = await interaction.channel.purge(after=desde)
        await interaction.followup.send(f"Se han eliminado **{len(deleted)}** mensajes enviados en los últimos **{segundos}** segundos.", ephemeral=True)

    @moderation_group.command(name="decir", description="Hacer que Jose Luis diga algo")
    async def decir(self, interaction: discord.Interaction, message: str, reply_to: Optional[str] = None):
        if await self.bot.filter_operators(interaction): return

        target_message: Optional[discord.Message] = None

        if reply_to:
            msg_id_str = reply_to.strip().split("/")[-1]
            if not msg_id_str.isdigit():
                await interaction.response.send_message("El ID o enlace del mensaje proporcionado no es válido.", ephemeral=True)
                return
            try:
                target_message = await interaction.channel.fetch_message(int(msg_id_str))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                await interaction.response.send_message("No se pudo encontrar el mensaje en este canal.", ephemeral=True)
                return

        if target_message:
            await target_message.reply(message)
        else:
            await interaction.channel.send(message)

        await interaction.response.send_message("Mensaje enviado.", ephemeral=True, delete_after=0.1)

    @moderation_group.command(name="cuarentenar", description="Añade a un usuario a la lista de cuarentena.")
    @app_commands.describe(usuario="El usuario que entrará en cuarentena", razon="Razón opcional de la cuarentena")
    async def cuarentena_agregar(self, interaction: discord.Interaction, usuario: discord.User, razon: str | None = None):
        if await self.bot.filter_operators(interaction): return

        await self.bot.db.quarantine.add_quarantine(usuario.id, razon)

        msg = f"El usuario {usuario.mention} ha sido puesto en cuarentena."
        if razon:
            msg += f"\n**Razón:** {razon}"

        await interaction.response.send_message(msg, ephemeral=True)

    @moderation_group.command(name="descuarentenar", description="Remueve a un usuario de la lista de cuarentena.")
    @app_commands.describe(usuario="El usuario a remover de cuarentena")
    async def cuarentena_quitar(self, interaction: discord.Interaction, usuario: discord.User):
        if await self.bot.filter_operators(interaction): return

        removed = await self.bot.db.quarantine.remove_quarantine(usuario.id)

        if removed:
            await interaction.response.send_message(f"Se ha removido a {usuario.mention} de la cuarentena.", ephemeral=True)
        else:
            await interaction.response.send_message(f"El usuario {usuario.mention} no estaba en cuarentena.", ephemeral=True)

    @moderation_group.command(name="vercuarentena", description="Comprueba si un usuario está en cuarentena.")
    @app_commands.describe(usuario="El usuario a consultar")
    async def cuarentena_verificar(self, interaction: discord.Interaction, usuario: discord.User):
        if await self.bot.filter_operators(interaction): return

        is_in_quarantine = await self.bot.db.quarantine.is_quarantined(usuario.id)

        if is_in_quarantine:
            reason = await self.bot.db.quarantine.get_quarantine_reason(usuario.id)
            msg = f" El usuario {usuario.mention} **está en cuarentena**."
            if reason:
                msg += f"\n**Razón:** {reason}"
            else:
                msg += "\n*Sin razón especificada.*"
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.response.send_message(f" El usuario {usuario.mention} **no está** en cuarentena.", ephemeral=True)

    @moderation_group.command(name="fusionarcuentas", description="Absorbe todos los datos de una cuenta en otra y borra la cuenta secundaria (operadores)")
    @app_commands.describe(principal="Cuenta que se conserva y recibe todos los datos", secundaria="Cuenta que se absorbe y se elimina")
    async def fusionar_cuentas(self, interaction: discord.Interaction, principal: discord.User, secundaria: discord.User):
        if await self.bot.filter_operators(interaction): return

        if principal.id == secundaria.id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ La cuenta principal y la cuenta secundaria son la misma.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        absorbed = await self.bot.db.merger.preview(secundaria.id)

        if not absorbed:
            await interaction.followup.send(
                embed=discord.Embed(description=f"❌ {secundaria.mention} no tiene ningún dato registrado: no hay nada que fusionar.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🧬 Fusionar cuentas",
            description=(
                f"Se traspasarán **{sum(absorbed.values())} filas** de {secundaria.mention} a {principal.mention} "
                "y después se borrará **todo** lo de la cuenta secundaria.\n\n"
                "**Es irreversible:** el progreso de la cuenta secundaria no se puede recuperar. "
                "Su cuenta de Discord no se toca, solo sus datos en el bot."
            ),
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="Datos detectados en la secundaria", value=merge_summary(absorbed), inline=False)
        await interaction.followup.send(embed=embed, view=MergeAccountsView(self.bot, interaction.user.id, principal, secundaria), ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        death_channel_id = int(await self.bot.db.guild.get(message.guild.id, "death_channel_id"))
        if message.channel.id != death_channel_id:
            return

        grace_seconds = await self.bot.db.guild.get(message.guild.id, "death_grace_seconds")
        duration = datetime.timedelta(seconds=grace_seconds)
        unban_deadline = datetime.datetime.now(datetime.timezone.utc) + duration

        admin_channel_id = int(await self.bot.db.guild.get(message.guild.id, "admin_channel_id"))
        admin_channel = message.guild.get_channel(admin_channel_id)

        try:
            await message.author.timeout(duration, reason=f"Escribir en canal de muerte. Tienes {grace_seconds} segundos para contactar a un mod si esto fue por error antes de ser baneado")

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

            msg = await message.channel.send(f"{message.author.mention} ha sucumbido ante mortal poder de Jose Luis...")
            await message.delete()
            await asyncio.sleep(10 * 60)
            await msg.delete()

        except discord.Forbidden:
            print(f"Error de permisos: No se pudo silenciar/banear a {message.author}.")
            await message.author.kick(reason="Escribir en canal de muerte. Debido a falta de permisos en vez de mutearte se te ha kickeado")
            if admin_channel:
                await admin_channel.send(f"El usuario **{message.author}** ({message.author.mention}) ha sido kickeado automáticamente porque no tengo permisos suficientes para mutear o banear (Solo Borja me los puede dar, y tal).")
            await message.channel.send(f"{message.author.mention} ha sucumbido ante el mortal poder de Jose Luis...")
            await message.delete()
        except discord.NotFound:
            print(f"El usuario {message.author} ya no se encuentra en el servidor.")



async def setup(bot: JoseLuisBot):
    await bot.add_cog(ModerationCog(bot))