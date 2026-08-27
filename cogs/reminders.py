import datetime
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from main import JoseLuisBot

MESSAGE_LINK_RE = re.compile(r"(?:https?://(?:\w+\.)?discord(?:app)?\.com/channels/\d+/\d+/)?(?P<message_id>\d{15,20})/?$")

MESES = [
    app_commands.Choice(name="Enero", value=1),
    app_commands.Choice(name="Febrero", value=2),
    app_commands.Choice(name="Marzo", value=3),
    app_commands.Choice(name="Abril", value=4),
    app_commands.Choice(name="Mayo", value=5),
    app_commands.Choice(name="Junio", value=6),
    app_commands.Choice(name="Julio", value=7),
    app_commands.Choice(name="Agosto", value=8),
    app_commands.Choice(name="Septiembre", value=9),
    app_commands.Choice(name="Octubre", value=10),
    app_commands.Choice(name="Noviembre", value=11),
    app_commands.Choice(name="Diciembre", value=12),
]


class RemindersCog(commands.Cog):
    def __init__(self, bot: JoseLuisBot):
        self.bot = bot
        self.check_reminders_task.start()

    reminder_group = app_commands.Group(
        name="recordatorio",
        description="Comandos para crear y gestionar recordatorios"
    )

    def cog_unload(self):
        self.check_reminders_task.cancel()

    async def _create_reminder(self, interaction: discord.Interaction, trigger_at: datetime.datetime, nota: str) -> None:
        reminder_id = await self.bot.db.reminder_create(
            interaction.guild.id, interaction.channel.id, interaction.user.id, nota, trigger_at.isoformat()
        )

        embed = discord.Embed(
            title="⏰ Recordatorio creado",
            description=nota,
            color=discord.Color.blurple()
        )
        embed.add_field(
            name="Se activará",
            value=f"{discord.utils.format_dt(trigger_at, style='F')} ({discord.utils.format_dt(trigger_at, style='R')})",
            inline=False
        )
        embed.add_field(
            name="¿Quieres que también te avisen a ti?",
            value="Usa `/recordatorio unirse` con el enlace o ID de este mensaje.",
            inline=False
        )

        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        await self.bot.db.reminder_set_message_id(reminder_id, message.id)

    @reminder_group.command(name="en", description="Crea un recordatorio dentro de un tiempo determinado")
    @app_commands.describe(
        nota="Qué quieres que te recuerde",
        dias="Días a esperar",
        horas="Horas a esperar",
        minutos="Minutos a esperar"
    )
    async def remind_in(
        self,
        interaction: discord.Interaction,
        nota: app_commands.Range[str, 1, 300],
        dias: app_commands.Range[int, 0, 365] = 0,
        horas: app_commands.Range[int, 0, 23] = 0,
        minutos: app_commands.Range[int, 0, 59] = 0,
    ):
        delta = datetime.timedelta(days=dias, hours=horas, minutes=minutos)
        if delta.total_seconds() <= 0:
            await interaction.response.send_message("⚠️ Debes indicar una duración mayor que cero.", ephemeral=True)
            return

        trigger_at = datetime.datetime.now(datetime.timezone.utc) + delta
        await self._create_reminder(interaction, trigger_at, nota)

    @reminder_group.command(name="el", description="Crea un recordatorio para una fecha y hora concretas (UTC)")
    @app_commands.describe(
        dia="Día del mes",
        mes="Mes del año",
        anio="Año",
        nota="Qué quieres que te recuerde",
        hora="Hora del día en UTC (0-23)",
        minuto="Minuto de la hora (0-59)"
    )
    @app_commands.choices(mes=MESES)
    async def remind_at(
        self,
        interaction: discord.Interaction,
        dia: app_commands.Range[int, 1, 31],
        mes: app_commands.Choice[int],
        anio: app_commands.Range[int, 2000, 2100],
        nota: app_commands.Range[str, 1, 300],
        hora: app_commands.Range[int, 0, 23] = 9,
        minuto: app_commands.Range[int, 0, 59] = 0,
    ):
        try:
            trigger_at = datetime.datetime(anio, mes.value, dia, hora, minuto, tzinfo=datetime.timezone.utc)
        except ValueError:
            await interaction.response.send_message("⚠️ Esa fecha no es válida.", ephemeral=True)
            return

        if trigger_at <= datetime.datetime.now(datetime.timezone.utc):
            await interaction.response.send_message("⚠️ La fecha debe ser en el futuro.", ephemeral=True)
            return

        await self._create_reminder(interaction, trigger_at, nota)

    async def _resolve_reminder(self, interaction: discord.Interaction, mensaje: str) -> dict | None:
        match = MESSAGE_LINK_RE.search(mensaje.strip())
        if not match:
            await interaction.response.send_message("⚠️ No he podido reconocer ese enlace o ID de mensaje.", ephemeral=True)
            return None

        message_id = int(match.group("message_id"))
        reminder = await self.bot.db.reminder_get_by_message_id(message_id)
        if not reminder:
            await interaction.response.send_message("⚠️ No he encontrado ningún recordatorio asociado a ese mensaje.", ephemeral=True)
            return None

        return reminder

    @reminder_group.command(name="unirse", description="Únete a un recordatorio para que también te avisen cuando se cumpla")
    @app_commands.describe(mensaje="Enlace o ID del mensaje del recordatorio")
    async def remind_join(self, interaction: discord.Interaction, mensaje: str):
        reminder = await self._resolve_reminder(interaction, mensaje)
        if reminder is None:
            return

        if reminder["triggered"]:
            await interaction.response.send_message("⚠️ Ese recordatorio ya se activó.", ephemeral=True)
            return

        if reminder["author_id"] == interaction.user.id:
            await interaction.response.send_message("✅ Ya recibirás el aviso, eres quien creó este recordatorio.", ephemeral=True)
            return

        added = await self.bot.db.reminder_add_subscriber(reminder["id"], interaction.user.id)
        if not added:
            await interaction.response.send_message("⚠️ Ya estabas apuntado a ese recordatorio.", ephemeral=True)
            return

        trigger_at = datetime.datetime.fromisoformat(reminder["trigger_at"])
        await interaction.response.send_message(
            f"🔔 Te avisaré junto al resto cuando se cumpla el recordatorio ({discord.utils.format_dt(trigger_at, style='R')}): *{reminder['note']}*",
            ephemeral=True
        )

    @reminder_group.command(name="lista", description="Muestra tus recordatorios activos, creados por ti o a los que te has unido")
    async def remind_list(self, interaction: discord.Interaction):
        reminders = await self.bot.db.reminder_get_related_to_user(interaction.user.id)
        if not reminders:
            await interaction.response.send_message("No tienes recordatorios activos.", ephemeral=True)
            return

        embed = discord.Embed(title="⏰ Tus recordatorios activos", color=discord.Color.blurple())
        for reminder in reminders:
            trigger_at = datetime.datetime.fromisoformat(reminder["trigger_at"])
            role = "Creado por ti" if reminder["author_id"] == interaction.user.id else "Te has unido"
            embed.add_field(
                name=f"🆔 {reminder['message_id']}",
                value=f"{reminder['note']}\n{discord.utils.format_dt(trigger_at, style='R')} · {role}",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reminder_group.command(name="estado", description="Consulta cuánto falta para un recordatorio y a quién se avisará")
    @app_commands.describe(mensaje="Enlace o ID del mensaje del recordatorio")
    async def remind_status(self, interaction: discord.Interaction, mensaje: str):
        reminder = await self._resolve_reminder(interaction, mensaje)
        if reminder is None:
            return

        subscriber_ids = await self.bot.db.reminder_get_subscribers(reminder["id"])
        mention_ids = dict.fromkeys([reminder["author_id"], *subscriber_ids])
        mentions = ", ".join(f"<@{user_id}>" for user_id in mention_ids)

        trigger_at = datetime.datetime.fromisoformat(reminder["trigger_at"])
        embed = discord.Embed(title="⏰ Estado del recordatorio", description=reminder["note"], color=discord.Color.blurple())

        if reminder["triggered"]:
            embed.add_field(name="Estado", value="Ya se ha activado", inline=False)
        else:
            embed.add_field(
                name="Se activará",
                value=f"{discord.utils.format_dt(trigger_at, style='F')} ({discord.utils.format_dt(trigger_at, style='R')})",
                inline=False
            )

        embed.add_field(name="Se avisará a", value=mentions, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _send_reminder(self, reminder: dict) -> None:
        channel = self.bot.get_channel(reminder["channel_id"])
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(reminder["channel_id"])
            except discord.HTTPException:
                return

        subscriber_ids = await self.bot.db.reminder_get_subscribers(reminder["id"])
        mention_ids = dict.fromkeys([reminder["author_id"], *subscriber_ids])
        mentions = " ".join(f"<@{user_id}>" for user_id in mention_ids)

        embed = discord.Embed(
            title="⏰ ¡Recordatorio!",
            description=reminder["note"],
            color=discord.Color.gold()
        )
        embed.add_field(name="Creado por", value=f"<@{reminder['author_id']}>")

        try:
            await channel.send(content=mentions, embed=embed, allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException as e:
            print(f"No se pudo enviar el recordatorio {reminder['id']}: {e}")

    @tasks.loop(seconds=60)
    async def check_reminders_task(self):
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        due_reminders = await self.bot.db.reminder_get_due(now_iso)
        for reminder in due_reminders:
            await self._send_reminder(reminder)

    @check_reminders_task.before_loop
    async def before_check_reminders(self):
        await self.bot.wait_until_ready()


async def setup(bot: JoseLuisBot):
    await bot.add_cog(RemindersCog(bot))
