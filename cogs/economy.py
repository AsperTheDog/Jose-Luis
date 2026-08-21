import math

import discord
import random
import datetime
from discord import app_commands
from discord.ext import commands, tasks
from typing import Optional

from database import DBManager
from main import JoseLuisBot
from stats import StatsTracker

SYMBOLS = {
    "🍒": {"weight": 45, "payout_3": 3.0, "payout_2": 0.5},
    "🍋": {"weight": 28, "payout_3": 5.0, "payout_2": 1.0},
    "🔔": {"weight": 15, "payout_3": 12.0, "payout_2": 1.2},
    "💎": {"weight": 8,  "payout_3": 30.0, "payout_2": 2.0},
    "7️⃣": {"weight": 4,  "payout_3": 100.0, "payout_2": 4.0},
}

class DropView(discord.ui.View):
    def __init__(self, amount: int, db: DBManager, global_stats: StatsTracker):
        super().__init__(timeout=60)
        self.amount = amount
        self.db = db
        self.claimed = False
        self.global_stats = global_stats

    @discord.ui.button(label="¡Reclamar Botín!", style=discord.ButtonStyle.success, emoji="💰")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.claimed:
            await interaction.response.send_message("¡Alguien se te adelantó!", ephemeral=True)
            return

        self.claimed = True
        self.stop()

        drop_boost = await self.db.get_user_job_perk(interaction.user.id, "drop_boost", 0.0)
        final_amount = int(self.amount * (1 + drop_boost))

        await self.db.economy_update_balance(interaction.user.id, final_amount)
        await self.global_stats.register_drop_obtained(interaction.user.id, final_amount)

        for item in self.children:
            item.disabled = True

        text = f"🎉 ¡{interaction.user.mention} ha sido el más rápido y se ha llevado **{final_amount}** choskris!"
        if drop_boost > 0.0:
            final_boost = self.amount * drop_boost
            text += f" (+{final_boost}!)"

        current_balance = await self.db.economy_get_balance(interaction.user.id)
        text += f"\n💰 Saldo actual: **{current_balance}**"
        await interaction.response.edit_message(content=text, view=self, delete_after=10)


class JobSelectView(discord.ui.View):
    def __init__(self, bot, user_id: int, job_registry: dict, db_path: str):
        super().__init__(timeout=60.0)
        self.bot = bot
        self.user_id = user_id
        self.job_registry = job_registry
        self.db_path = db_path

        options = []
        for job_id, j_data in self.job_registry.items():
            options.append(
                discord.SelectOption(
                    label=j_data["nombre"],
                    value=job_id,
                    description=j_data["desc"][:100],
                    emoji=j_data.get("emoji"),
                )
            )

        self.job_select = discord.ui.Select(
            placeholder="Selecciona un trabajo...",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.job_select.callback = self.select_callback
        self.add_item(self.job_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("No puedes interactuar con el menú de otra persona.", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        selected_job_id = self.job_select.values[0]

        user_data = await self.bot.db.economy_get_user_data(self.user_id)

        if user_data.get("last_job_switch"):
            last_switch = datetime.datetime.fromisoformat(user_data["last_job_switch"])
            now = datetime.datetime.now(datetime.timezone.utc)
            time_allowed = last_switch + datetime.timedelta(days=3)
            if now < time_allowed:
                phrase = await self.bot.db.global_get_random_phrase("job_obtain_fail", "fast")

                for item in self.children:
                    item.disabled = True

                time_dialog = discord.utils.format_dt(time_allowed, "R")
                await interaction.followup.edit_message(
                    message_id=interaction.message.id,
                    content=f"{phrase}Debes esperar para cambiar de nuevo.\nPodrás cambiar de trabajo {time_dialog}",
                    embed=None,
                    view=None
                )
                self.stop()
                return

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        await self.bot.db.economy_update_active_job(self.user_id, selected_job_id, now_iso)
        await self.bot.global_stats.register_job_switch(self.user_id)

        j_data = self.job_registry[selected_job_id]
        phrase = await self.bot.db.global_get_random_phrase("job_obtain_success", selected_job_id)

        for item in self.children:
            item.disabled = True

        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            content=(
                f"{phrase}¡Contratado! Ahora trabajas como"
                f" **{j_data['nombre']}** {j_data['emoji']}."
            ),
            embed=None,
            view=None
        )
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content="Selección de empleo cancelada.", view=self
        )
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception:
            pass


class EconomyCog(commands.Cog):
    def __init__(self, bot: JoseLuisBot):
        self.bot = bot
        self.db_path = "bot_data.db"
        self.daily_interest_task.start()

        self.last_drop_time = {}

    economy_group = app_commands.Group(
        name="choskris",
        description="Comandos para ganar choskris"
    )

    def cog_unload(self):
        self.daily_interest_task.cancel()

    @staticmethod
    def _check_jail(jail_until: str) -> bool:
        if not jail_until:
            return False
        return datetime.datetime.fromisoformat(jail_until) > datetime.datetime.now(datetime.timezone.utc)

    @economy_group.command(name="perfil", description="Muestra tu saldo, estado de empleo, rachas y situación legal.")
    @app_commands.describe(usuario="El usuario del que quieres ver el perfil (opcional)")
    async def perfil(self, interaction: discord.Interaction, usuario: Optional[discord.User] = None):
        await interaction.response.defer()

        target_user = usuario or interaction.user
        if target_user.bot:
            await interaction.followup.send("Los bots no tienen cuenta bancaria.", ephemeral=True)
            return

        user_data = await self.bot.db.economy_get_user_data(target_user.id)
        now = datetime.datetime.now(datetime.timezone.utc)

        active_job_id = user_data.get('active_job')
        if active_job_id and active_job_id in self.bot.db.job_registry:
            job_info = self.bot.db.job_registry[active_job_id]
            job_stats = await self.bot.db.economy_get_job_data(target_user.id, active_job_id)

            level = job_stats['level']
            xp = job_stats['xp']
            xp_needed = level * 100

            progress_pct = min(1.0, xp / xp_needed)
            filled_blocks = int(progress_pct * 8)
            bar = "█" * filled_blocks + "░" * (8 - filled_blocks)

            trabajo_val = (
                f"{job_info['emoji']} *{job_info['nombre']}* (Nivel {level})\n"
                f"`[{bar}]` {xp}/{xp_needed} XP"
            )

        else:
            trabajo_val = "❌ *Desempleado* (Usa `/buscartrabajo`)"

        in_jail = self._check_jail(user_data['jail_until'])
        if in_jail:
            jail_until = datetime.datetime.fromisoformat(user_data['jail_until'])
            time_dialog = discord.utils.format_dt(jail_until, "R")
            estado_legal = f"🔒 *Encarcelado* (Libre {time_dialog})"
        else:
            estado_legal = "🟢 *Ciudadano Libre*"

        embed = discord.Embed(title=f"💳 Perfil Económico de {target_user.display_name}", color=0xe74c3c if in_jail else 0x2ecc71)
        embed.set_thumbnail(url=target_user.display_avatar.url)
        embed.add_field(name="💰 Finanzas", value=f"**Saldo:** `{user_data['balance']:,}` choskris", inline=False)
        embed.add_field(name="💼 Carrera Profesional", value=trabajo_val, inline=True)
        embed.add_field(name="⚖️ Situación Legal", value=estado_legal, inline=True)
        embed.add_field(name="🔥 Rachas Activas", value=f"📆 *Paga Diaria:* {user_data['daily_streak']} días\n🥷 *Racha Criminal:* {user_data['crime_streak']} éxitos", inline=False)
        phrase = await self.bot.db.global_get_random_phrase("profile", "quote", False)
        embed.set_footer(text=f"'{phrase}' - {target_user.display_name}")
        await interaction.followup.send(embed=embed)

    @economy_group.command(name="buscartrabajo", description="Muestra la lista de trabajos y te permite cambiarte a uno.")
    async def buscartrabajo(self, interaction: discord.Interaction):
        await interaction.response.defer()

        embed = discord.Embed(
            title="🏢 Agencia de Empleo",
            description=(
                "Selecciona la profesión a la que deseas cambiarte en el menú"
                " desplegable.\n*Nota: Solo puedes cambiar de empleo una vez cada"
                " 3 días.*"
            ),
            color=0x3498DB,
        )

        for j_id, j_data in self.bot.db.job_registry.items():
            stats = await self.bot.db.economy_get_job_data(
                interaction.user.id, j_id
            )
            embed.add_field(
                name=f"{j_data['emoji']} {j_data['nombre']}",
                value=f"{j_data['desc']}\n*Nivel Actual: {stats['level']}*",
                inline=False,
            )

        view = JobSelectView(
            bot=self.bot,
            user_id=interaction.user.id,
            job_registry=self.bot.db.job_registry,
            db_path=self.db_path,
        )

        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg

    @economy_group.command(name="trabajar", description="Trabaja en tu empleo activo para ganar choskris y experiencia.")
    async def trabajar(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_data = await self.bot.db.economy_get_user_data(interaction.user.id)

        active_job = user_data['active_job']
        if not active_job or active_job not in self.bot.db.job_registry:
            await interaction.followup.send("No tienes un trabajo. Usa `/buscartrabajo` para buscar uno.")
            return

        now = datetime.datetime.now(datetime.timezone.utc)
        if user_data['last_work']:
            last_work = datetime.datetime.fromisoformat(user_data['last_work'])
            reduction = await self.bot.db.get_user_job_perk(interaction.user.id, "cooldown_reduction_pct", 0.0)
            reduction_flat = await self.bot.db.get_user_job_perk(interaction.user.id, "work_cooldown_seconds", 0.0)
            if now < last_work + datetime.timedelta(hours=12 * (1.0 - reduction)):
                time_cooldown = datetime.timedelta(hours=12 * (1.0 - reduction)) - datetime.timedelta(seconds=reduction_flat)
                next_time = last_work + time_cooldown
                time_dialog = discord.utils.format_dt(next_time, "R")
                text = f"Ya has trabajado hoy. Vuelve {time_dialog}."
                if reduction > 0.0:
                    time_reduced = datetime.timedelta(hours=12 - 12 * (1.0 - reduction)) + datetime.timedelta(seconds=reduction_flat)
                    text += f" (-{time_reduced.seconds // 3600}h {(time_reduced.seconds // 60) % 60}m!)"
                await interaction.followup.send(content=text)
                return

        job_stats = await self.bot.db.economy_get_job_data(interaction.user.id, active_job)
        level = job_stats['level']
        xp = job_stats['xp']

        xp_gained = random.randint(20, 35)
        new_xp = xp + xp_gained
        xp_needed = level * 100

        leveled_up = False
        if new_xp >= xp_needed:
            level += 1
            new_xp -= xp_needed
            leveled_up = True

        bonus = await self.bot.db.get_user_job_perk(interaction.user.id, "flat_work_bonus", 0.0)
        penalty = await self.bot.db.get_user_job_perk(interaction.user.id, "job_penalty", 0.0)
        salary = random.randint(150, 250) + (level * 20) + bonus
        salary *= 1 - penalty
        salary = int(salary)

        await self.bot.db.economy_update_work_and_job(interaction.user.id, salary, now.isoformat(), active_job, level, new_xp)

        await self.bot.global_stats.register_work(interaction.user.id, salary)
        j_data = self.bot.db.job_registry[active_job]
        phrase = await self.bot.db.global_get_random_phrase("job_work", active_job)
        if salary == 0.0:
            msg = f"{phrase}💼 Has holgazaneado como **{j_data['nombre']}** por lo que no has ganado choskris. (+{xp_gained} XP)"
        else:
            msg = f"{phrase}💼 Has trabajado duro como **{j_data['nombre']}** y ganado **{int(salary)}** choskris. (+{xp_gained} XP)"
            if bonus > 0.0:
                msg += f" (+{bonus} bonus de trabajo!)"
            if leveled_up:
                msg += f"\n⭐ **¡SUBIDA DE NIVEL!** Tu nivel en {j_data['nombre']} es ahora **{level}**."

        current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
        msg += f"\n💰 Saldo actual: **{current_balance}**"
        await interaction.followup.send(msg)

    @economy_group.command(name="allowence", description="Reclama tu choskris diario.")
    async def paga(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_data = await self.bot.db.economy_get_user_data(interaction.user.id)
        now = datetime.datetime.now(datetime.timezone.utc)

        streak = user_data['daily_streak']
        if user_data['last_daily']:
            last_daily = datetime.datetime.fromisoformat(user_data['last_daily'])
            delta = now - last_daily
            if delta < datetime.timedelta(hours=24):
                phrase = await self.bot.db.global_get_random_phrase("allowance", "fail")
                next_time = last_daily + datetime.timedelta(hours=24)
                time_dialog = discord.utils.format_dt(next_time, "R")
                await interaction.followup.send(f"{phrase}Aún no puedes reclamar tu paga. Vuelve {time_dialog}.")
                return
            elif delta > datetime.timedelta(hours=48):
                streak = 0

        base_paga = 200
        streak_bonus = min(streak * 25, 500)

        job_boost = await self.bot.db.get_user_job_perk(interaction.user.id, "passive_daily_income", 0.0)
        final_paga = int((base_paga + streak_bonus) * (1 + job_boost))

        await self.bot.db.economy_daily_claim(interaction.user.id, final_paga, streak, now.isoformat())
        await self.bot.global_stats.register_allowance_claim(interaction.user.id, final_paga, streak)
        phrase = await self.bot.db.global_get_random_phrase("allowance", "success")
        msg = f"{phrase}💸Could you give me an allowence?\n Has obtenido **{final_paga}** choskris.\n🔥 Racha diaria: **{streak + 1}** días."

        if job_boost > 0.0:
            msg += f" *(+{int(job_boost * 100)}%!)*"

        current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
        msg += f"\n💰 Saldo actual: **{current_balance}**"
        await interaction.followup.send(msg)

    @economy_group.command(name="ruleta", description="Juega a la ruleta. Puedes apostar a color, a número, o a ambos (ej. 0 Verde o 17 Negro).")
    @app_commands.describe(
        apuesta="Cantidad de choskris a apostar",
        color="Color al que quieres apostar (Rojo, Negro o Verde)",
        numero="Número específico al que quieres apostar (0 a 36)"
    )
    @app_commands.choices(color=[
        app_commands.Choice(name="🔴 Rojo", value="rojo"),
        app_commands.Choice(name="⚫ Negro", value="negro"),
        app_commands.Choice(name="🟢 Verde", value="verde")
    ])
    async def spin(self, interaction: discord.Interaction, apuesta: int, color: Optional[str] = None, numero: Optional[int] = None):
        await interaction.response.defer()

        phrase = await self.bot.db.global_get_random_phrase("gamble", "error")
        if apuesta <= 0:
            await interaction.followup.send(f"{phrase}La apuesta debe ser mayor a 0.")
            return

        if color is None and numero is None:
            await interaction.followup.send(f"{phrase}Debes elegir al menos una opción: un color, un número, o ambos.")
            return

        if numero is not None and not (0 <= numero <= 36):
            await interaction.followup.send(f"{phrase}El número debe estar entre 0 y 36.")
            return

        user_data = await self.bot.db.economy_get_user_data(interaction.user.id)
        if user_data['balance'] < apuesta:
            await interaction.followup.send(f"{phrase}No tienes suficiente choskris para esta apuesta.")
            return

        is_let_it_ride = (numero == 17 and color == "negro")

        resultado_num = random.randint(0, 36)
        es_rojo = resultado_num in [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]

        if resultado_num == 0:
            resultado_color = "verde"
            color_emoji = "🟢 Verde"
        elif es_rojo:
            resultado_color = "rojo"
            color_emoji = "🔴 Rojo"
        else:
            resultado_color = "negro"
            color_emoji = "⚫ Negro"

        acerto_color = (color is not None and color == resultado_color)
        acerto_numero = (numero is not None and numero == resultado_num)

        multiplier = 0
        pago_descripcion = ""

        if color is not None and numero is not None:
            if acerto_color and acerto_numero:
                multiplier = 70
                pago_descripcion = "¡Pleno Combinado!"
        elif numero is not None:
            if acerto_numero:
                multiplier = 36
                pago_descripcion = "¡Pleno al Número!"
        elif color is not None:
            if acerto_color:
                if color == "verde":
                    multiplier = 36
                    pago_descripcion = "¡Acierto en Verde!"
                else:
                    multiplier = 2
                    pago_descripcion = "¡Acierto de Color!"

        prefix_msg = "**¡LET IT RIDE!**\n" if is_let_it_ride else ""

        if multiplier > 0:
            prize = apuesta * multiplier
            await self.bot.db.economy_update_balance(interaction.user.id, prize - apuesta)
            await self.bot.global_stats.register_roulette_win(interaction.user.id, prize, apuesta)

            phrase = await self.bot.db.global_get_random_phrase("spin", "success")
            await interaction.followup.send(
                f"{prefix_msg}{phrase}🎰 La bola cayó en **{resultado_num} {color_emoji}**.\n"
                f"🎉 **{pago_descripcion}** Has ganado **{int(prize)}** choskris."
            )
        else:
            phrase = await self.bot.db.global_get_random_phrase("spin", "fail")
            cashback_pct = await self.bot.db.get_user_job_perk(interaction.user.id, "gambling_cashback", 0.0)
            loss = int(apuesta * (1 - cashback_pct))
            await self.bot.db.economy_update_balance(interaction.user.id, -loss)
            await self.bot.global_stats.register_roulette_loss(interaction.user.id, apuesta)

            msg = f"{prefix_msg}{phrase}🎰 La bola cayó en **{resultado_num} {color_emoji}**.\n❌ Perdiste **{apuesta}** choskris."
            if cashback_pct > 0:
                msg += f" (-**{apuesta - loss}** cashback)"

            current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
            msg += f"\n💰 Saldo actual: **{current_balance}**"
            await interaction.followup.send(msg)

    @economy_group.command(name="dados", description="Lanza dos dados de 6 caras. Apuesta a suma exacta, alta/baja/7 o par/impar.")
    @app_commands.describe(
        apuesta="Cantidad de choskris a apostar",
        modalidad="Tipo de apuesta (Alta/Baja/7, Par/Impar o Suma Exacta)",
        suma_exacta="Si elegiste 'Suma Exacta', especifica el número objetivo (2 al 12)"
    )
    @app_commands.choices(modalidad=[
        app_commands.Choice(name="Baja (2-6) - Paga 2x", value="baja"),
        app_commands.Choice(name="Siete Exacto (7) - Paga 5x", value="siete"),
        app_commands.Choice(name="Alta (8-12) - Paga 2x", value="alta"),
        app_commands.Choice(name="Par - Paga 2x", value="par"),
        app_commands.Choice(name="Impar - Paga 2x", value="impar"),
        app_commands.Choice(name="Suma Exacta (Especificar número abajo)", value="exacta")
    ])
    async def dice(self, interaction: discord.Interaction, apuesta: int, modalidad: str, suma_exacta: Optional[int] = None):
        await interaction.response.defer()

        phrase = await self.bot.db.global_get_random_phrase("gamble", "error")
        if apuesta <= 0:
            await interaction.followup.send(f"{phrase}La apuesta debe ser mayor a 0.")
            return

        if modalidad == "exacta":
            if suma_exacta is None or not (2 <= suma_exacta <= 12):
                await interaction.followup.send(f"{phrase}Para la modalidad 'Suma Exacta', debes indicar un número entre 2 y 12 en el campo `suma_exacta`.")
                return

        user_data = await self.bot.db.economy_get_user_data(interaction.user.id)
        if user_data['balance'] < apuesta:
            await interaction.followup.send(f"{phrase}No tienes suficiente choskris para esta apuesta.")
            return

        dado1 = random.randint(1, 6)
        dado2 = random.randint(1, 6)
        total = dado1 + dado2

        dice_emojis = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
        d1_str = dice_emojis[dado1]
        d2_str = dice_emojis[dado2]

        multiplier = 0
        pago_descripcion = ""

        if modalidad == "exacta":
            if total == suma_exacta:
                payout_table = {2: 30, 12: 30, 3: 15, 11: 15, 4: 10, 10: 10, 5: 7, 9: 7, 6: 5, 8: 5, 7: 5}
                multiplier = payout_table.get(suma_exacta, 5)
                pago_descripcion = f"¡Acierto exacto de **{suma_exacta}**!"

        elif modalidad == "baja" and 2 <= total <= 6:
            multiplier = 2
            pago_descripcion = "¡Acierto en Baja (2-6)!"

        elif modalidad == "alta" and 8 <= total <= 12:
            multiplier = 2
            pago_descripcion = "¡Acierto en Alta (8-12)!"

        elif modalidad == "siete" and total == 7:
            multiplier = 5
            pago_descripcion = "¡Acierto en Siete Exacto (7)!"

        elif modalidad == "par" and total % 2 == 0:
            multiplier = 2
            pago_descripcion = "¡Acierto en Par!"

        elif modalidad == "impar" and total % 2 != 0:
            multiplier = 2
            pago_descripcion = "¡Acierto en Impar!"

        if multiplier > 0:
            prize = apuesta * multiplier
            await self.bot.db.economy_update_balance(interaction.user.id, prize - apuesta)
            await self.bot.global_stats.register_dice_win(interaction.user.id, prize, apuesta)

            phrase = await self.bot.db.global_get_random_phrase("dice", "success")
            await interaction.followup.send(
                f"{phrase}🎲 Los dados cayeron en: {d1_str} + {d2_str} = **{total}**\n"
                f"🎉 **{pago_descripcion}** Has ganado **{int(prize)}** choskris. *(Multiplicador {multiplier}x)*"
            )
        else:
            cashback_pct = await self.bot.db.get_user_job_perk(interaction.user.id, "gambling_cashback", 0.0)
            loss = int(apuesta * (1 - cashback_pct))
            await self.bot.db.economy_update_balance(interaction.user.id, -loss)
            await self.bot.global_stats.register_dice_loss(interaction.user.id, apuesta)

            phrase = await self.bot.db.global_get_random_phrase("dice", "fail")
            msg = f"{phrase}🎲 Los dados cayeron en: {d1_str} + {d2_str} = **{total}**\n❌ Perdiste **{apuesta}** choskris."
            if cashback_pct > 0:
                msg += f" (-**{apuesta - loss}** cashback)"

            current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
            msg += f"\n💰 Saldo actual: **{current_balance}**"
            await interaction.followup.send(msg)

    @economy_group.command(name="crimen", description="Comete un delito. Altas ganancias, alto riesgo.")
    async def crimen(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_data = await self.bot.db.economy_get_user_data(interaction.user.id)
        now = datetime.datetime.now(datetime.timezone.utc)

        if self._check_jail(user_data['jail_until']):
            jail_until = datetime.datetime.fromisoformat(user_data['jail_until'])
            delta = jail_until - now
            await interaction.followup.send(f"🚓 Estás en la cárcel. Sales en **{delta.days} días, {delta.seconds // 3600}h**.")
            return

        streak = user_data['crime_streak']
        base_reward = 500

        success_boost = await self.bot.db.get_user_job_perk(interaction.user.id, "crime_success_rate", 0.0)
        payout_boost = await self.bot.db.get_user_job_perk(interaction.user.id, "crime_payout_boost", 0.0)
        jail_bonus = await self.bot.db.get_user_job_perk(interaction.user.id, "jail_bonus", 0.0)

        chance = 0.45 + success_boost - (streak * 0.05)
        chance = max(0.10, chance)

        job = await self.bot.db.get_user_active_job(interaction.user.id)

        if random.random() < chance:
            reward = int((base_reward * (1 + streak * 0.2)))
            bonus = reward * payout_boost
            reward += bonus

            await self.bot.db.economy_crime_success(interaction.user.id, reward)
            await self.bot.global_stats.register_successful_crime(interaction.user.id, reward)

            phrase = await self.bot.db.global_get_random_phrase("crime_success", job)
            msg = f"{phrase}🥷 **¡Golpe exitoso!** Robaste **{int(reward)}** choskris.{f" (+{int(bonus)}!)" if bonus > 0.0 else ""}\n🔥 Racha criminal: **{streak + 1}**"

            current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
            msg += f"\n💰 Saldo actual: **{current_balance}**"
            await interaction.followup.send(msg)
        else:
            penalty = base_reward * 1.5
            jail_time = 72 * (1 + jail_bonus)
            bonus = 72 * (1 + jail_bonus) - 72
            jail_until_str = (now + datetime.timedelta(hours=jail_time)).isoformat()

            await self.bot.db.economy_crime_failure(interaction.user.id, penalty, jail_until_str)
            await self.bot.global_stats.register_jail_sentence(interaction.user.id, penalty)

            phrase = await self.bot.db.global_get_random_phrase("crime_fail", job)
            msg = f"{phrase}🚓 **¡Te atrapó la policía!** Perdiste **{int(penalty)}** choskris y tu racha criminal se reinicia a 0.\nPasarás {jail_time} horas en la cárcel." + (f"(+{bonus} horas...)" if bonus > 0.0 else "")

            current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
            msg += f"\n💰 Saldo actual: **{current_balance}**"
            await interaction.followup.send(msg)

    @economy_group.command(name="pagar", description="Transfiere choskris de tu cuenta personal a otro usuario.")
    @app_commands.describe(destinatario="El usuario que recibirá los choskris", cantidad="La cantidad de choskris a transferir")
    async def pagar(self, interaction: discord.Interaction, destinatario: discord.User, cantidad: int):
        await interaction.response.defer()

        phrase = await self.bot.db.global_get_random_phrase("pay_error")
        if cantidad <= 0:
            await interaction.followup.send(f"{phrase}La cantidad a transferir debe ser mayor a 0.")
            return

        if destinatario.id == interaction.user.id:
            await interaction.followup.send(f"{phrase}No puedes transferirte choskris a ti mismo.")
            return

        if destinatario.bot:
            await interaction.followup.send(f"{phrase}No puedes transferir choskris a un bot.")
            return

        user_data = await self.bot.db.economy_get_user_data(interaction.user.id)
        if user_data['balance'] < cantidad:
            await interaction.followup.send(f"{phrase}Saldo insuficiente. Tienes **{user_data['balance']:,}** choskris y quieres enviar **{cantidad:,}**.")
            return

        await self.bot.db.economy_transfer_balance(interaction.user.id, destinatario.id, cantidad)
        await self.bot.global_stats.register_money_gift_give(interaction.user.id, cantidad)
        await self.bot.global_stats.register_money_gift_receive(destinatario.id, cantidad)

        phrase = await self.bot.db.global_get_random_phrase("pay_success")
        msg = f"{phrase}💸 ¡{interaction.user.mention} le ha enviado **{cantidad:,}** choskris a {destinatario.mention}!"

        current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
        msg += f"\n💰 Saldo actual: **{current_balance}**"
        await interaction.followup.send(msg)

    @economy_group.command(name="generar", description="Genera choskris del aire y se lo otorga a un usuario.")
    @app_commands.describe(destinatario="El usuario que recibirá los choskris generados", cantidad="La cantidad de choskris a generar")
    async def generar_dinero(self, interaction: discord.Interaction, destinatario: discord.User, cantidad: int):
        if await self.bot.filter_operators(interaction): return

        await interaction.response.defer()

        if cantidad <= 0:
            await interaction.followup.send("La cantidad generada debe ser mayor a 0.")
            return

        if destinatario.bot:
            await interaction.followup.send("No puedes otorgar choskris a un bot.")
            return

        await self.bot.db.economy_update_balance(destinatario.id, cantidad)
        await self.bot.global_stats.register_money_gift_receive(destinatario.id, cantidad)

        await interaction.followup.send(f"✅ Has generado **{cantidad:,}** choskris para {destinatario.mention}.")

    @economy_group.command(name="interes", description="Reclama los intereses generados por tus ahorros")
    async def claim_interest(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        phrase = await self.bot.db.global_get_random_phrase("interest_fail")
        claimed_amount = await self.bot.db.economy_claim_interest(user_id)

        if claimed_amount is None:
            await interaction.response.send_message(f"{phrase}No tienes una cuenta de economía registrada.", ephemeral=True)
            return

        if claimed_amount <= 0:
            await interaction.response.send_message( f"{phrase}No tienes intereses pendientes por reclamar.", ephemeral=True)
            return

        await self.bot.global_stats.register_interest_payout(user_id, claimed_amount)
        phrase = await self.bot.db.global_get_random_phrase("interest_success")
        message = f"{phrase}Has reclamado **+{claimed_amount:,}** choskris acumulados de intereses."

        current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
        message += f"\n💰 Saldo actual: **{current_balance}**"
        await interaction.response.send_message(message)

    @economy_group.command(name="meterfrase", description="Inserta una frase customizada para las acciones de economía")
    async def meterfrase(self, interaction: discord.Interaction, frase: str, categoria: str, tag: Optional[str] = None):
        if await self.bot.filter_operators(interaction): return
        await self.bot.db.economy_add_phrase(frase, categoria, tag)

        await interaction.response.send_message(f"Añadido '{frase}' a la lista de frases.", ephemeral=True)

    @staticmethod
    def _get_random_symbol():
        symbols = list(SYMBOLS.keys())
        weights = [SYMBOLS[s]["weight"] for s in symbols]
        return random.choices(symbols, weights=weights, k=1)[0]

    @economy_group.command(name="slots", description="Juega a la máquina tragaperras")
    @app_commands.describe(apuesta="Cantidad de monedas a apostar")
    async def slots(self, interaction: discord.Interaction, apuesta: int):
        if apuesta <= 0:
            await interaction.response.send_message("La apuesta debe ser mayor a 0.", ephemeral=True)
            return

        user_id = interaction.user.id

        reel1 = self._get_random_symbol()
        reel2 = self._get_random_symbol()
        reel3 = self._get_random_symbol()

        multiplier = 0.0
        if reel1 == reel2 == reel3:
            multiplier = SYMBOLS[reel1]["payout_3"]
        elif reel1 == reel2 or reel1 == reel3:
            multiplier = SYMBOLS[reel1]["payout_2"]
        elif reel2 == reel3:
            multiplier = SYMBOLS[reel2]["payout_2"]

        winnings = int(apuesta * multiplier)
        net_change = winnings - apuesta

        success, current_balance = await self.bot.db.economy_process_slots_bet(interaction.user.id, apuesta, net_change)

        if not success:
            await interaction.response.send_message(f"No tienes suficientes monedas. Saldo actual: **{current_balance}**", ephemeral=True)
            return

        reels_display = f"| {reel1} | {reel2} | {reel3} |"
        if winnings > 0:
            result_text = f"🎉 ¡Ganaste **{winnings}** monedas!\n(Multiplicador: {multiplier}x)"
            await self.bot.global_stats.register_slots_win(interaction.user.id, winnings, apuesta)
        else:
            result_text = "❌ Has perdido tu apuesta."
            await self.bot.global_stats.register_slots_loss(interaction.user.id, apuesta)

        embed = discord.Embed(title="🎰 Tragaperras 🎰", color=discord.Color.gold() if winnings > 0 else discord.Color.red())
        embed.add_field(name="Rodillos", value=f"```\n{reels_display}\n```", inline=False)
        embed.add_field(name="Resultado", value=result_text, inline=False)

        current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
        embed.add_field(name=f"", value=f"💰 Saldo actual: **{current_balance}**")

        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="forzardrop", description="Obliga al juego a generar un drop inmediatamente")
    async def drop(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        channel_id = interaction.channel.id
        now = datetime.datetime.now(datetime.timezone.utc)

        self.last_drop_time[channel_id] = now
        amount = random.randint(50, 150)

        embed = discord.Embed(title="¡Han caído unos choskris!", description=f"Alguien ha dejado caer **{amount}** choskris al suelo. ¡Sé el primero en cogerlos!", color=0xf1c40f)

        view = DropView(amount=amount, db=self.bot.db, global_stats=self.bot.global_stats)
        await interaction.response.send_message("¡Drop en camino!", ephemeral=True)
        await interaction.channel.send(embed=embed, view=view)


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not await self.bot.config.is_channel_whitelisted(message.guild.id, message.channel.id):
            return

        channel_id = message.channel.id
        now = datetime.datetime.now(datetime.timezone.utc)

        if channel_id in self.last_drop_time:
            if now < self.last_drop_time[channel_id] + datetime.timedelta(minutes=2):
                return

        if random.random() < 0.015:
            self.last_drop_time[channel_id] = now
            amount = random.randint(50, 150)

            embed = discord.Embed(title="¡Han caído unos choskris!", description=f"Alguien ha dejado caer **{amount}** choskris al suelo. ¡Sé el primero en cogerlos!", color=0xf1c40f)

            view = DropView(amount=amount, db=self.bot.db, global_stats=self.bot.global_stats)
            await message.channel.send(embed=embed, view=view)

    @tasks.loop(time=datetime.time(hour=0, minute=0, second=0))
    async def daily_interest_task(self):
        users = await self.bot.db.economy_get_active_users()

        for user_id, balance, active_job, current_unclaimed in users:
            perk_bonus = await self.bot.db.get_job_perk(active_job, "bank_interest_bonus", 0.0)

            if perk_bonus <= 0:
                continue

            daily_interest = math.floor(balance * perk_bonus)
            await self.bot.db.economy_add_unclaimed_interest(user_id, daily_interest)

    @daily_interest_task.before_loop
    async def before_daily_interest(self):
        await self.bot.wait_until_ready()


async def setup(bot: JoseLuisBot):
    await bot.add_cog(EconomyCog(bot))