import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime
import time
import random

from main import JoseLuisBot
from database import BOT_RACE_HOUSE_SEED

TRACK_LENGTH = 1000.0
RACE_TIMES = [datetime.time(hour=h, minute=m) for h in range(24) for m in (0, 30)]

class HorseBetCog(commands.Cog):
    def __init__(self, bot: JoseLuisBot):
        self.bot = bot
        self.race_loop.start()

    caballos_group = app_commands.Group(
        name="caballos",
        description="Comandos relacionados con la apuesta de caballos"
    )

    def cog_unload(self):
        self.race_loop.cancel()

    @staticmethod
    def generate_horses():
        names = ["Sardinilla", "Relinchín", "Jorse Luis", "Flurflirs", "Semáforo", "Mondongo", "Comida de Emergencia"]
        random.shuffle(names)
        horses = []
        for i in range(1, 5):
            horses.append((i, names[i - 1], random.randint(3, 9), random.randint(4, 10), random.randint(2, 8)))
        return horses

    @tasks.loop(time=RACE_TIMES)
    async def race_loop(self):
        now = datetime.datetime.now()
        today_date = now.strftime("%Y-%m-%d")

        unprocessed_dates = await self.bot.db.betting_get_unprocessed_dates()
        for old_date in unprocessed_dates:
            race = await self.bot.db.betting_get_race(old_date)
            if race:
                winner = sorted(race, key=lambda h: (-h['distance'], h['finish_time'] or float('inf')))[0]
                resolved_bets = await self.bot.db.betting_resolve_payouts(old_date, winner['horse_id'])
                for bet in resolved_bets:
                    if bet['won']:
                        await self.bot.global_stats.register_bet_won(bet['user_id'], bet['payout'])
                    else:
                        await self.bot.global_stats.register_bet_lost(bet['user_id'])

        today_race = await self.bot.db.betting_get_race(today_date)
        if not today_race:
            await self.bot.db.betting_create_race(today_date, self.generate_horses())
            today_race = await self.bot.db.betting_get_race(today_date)

        if 12 <= now.hour <= 23:
            for horse in today_race:
                if horse['finished']:
                    continue

                fatigue = 1.0 if horse['distance'] < (horse['stamina'] * 100) else 0.6
                clutch_bonus = horse['clutch'] * 3 if (TRACK_LENGTH - horse['distance']) < 250 else 0
                variance = random.uniform(-15.0, 15.0)

                tick_distance = (horse['speed'] * 8) * fatigue + clutch_bonus + variance
                new_distance = horse['distance'] + max(5.0, tick_distance)

                finished = False
                finish_timestamp = None

                if new_distance >= TRACK_LENGTH:
                    new_distance = TRACK_LENGTH
                    finished = True

                    overshoot = (horse['distance'] + max(5.0, tick_distance)) - TRACK_LENGTH
                    progress_made = max(5.0, tick_distance)
                    fraction_of_tick = 1.0 - (overshoot / progress_made)

                    finish_timestamp = time.time() + fraction_of_tick

                await self.bot.db.betting_update_horse_distance(today_date, horse['horse_id'], new_distance, finished, finish_timestamp)

    @race_loop.before_loop
    async def before_race_loop(self):
        await self.bot.wait_until_ready()
        today_date = datetime.datetime.now().strftime("%Y-%m-%d")
        race = await self.bot.db.betting_get_race(today_date)
        if not race:
            await self.bot.db.betting_create_race(today_date, self.generate_horses())

    @caballos_group.command(name="carreras", description="Mira el estado de la carrera de hoy y el pozo de apuestas.")
    async def carreras(self, interaction: discord.Interaction):
        now = datetime.datetime.now().astimezone()
        today_date = now.strftime("%Y-%m-%d")
        today_12 = now.replace(hour=12, minute=0, second=0, microsecond=0)
        race = await self.bot.db.betting_get_race(today_date)

        if not race:
            embed = discord.Embed(
                title="🏇 Gran Premio de Tres Cantos",
                description="Las inscripciones aún se están preparando.",
                color=discord.Color.light_grey()
            )
            await interaction.response.send_message(embed=embed)
            return

        bet_rows = await self.bot.db.betting_get_race_bets_summary(today_date)
        bets_by_horse = {row['horse_id']: row['total_bet'] for row in bet_rows}

        total_player_pool = sum(bets_by_horse.values())
        house_rake = int(total_player_pool * 0.1)
        distributable = (total_player_pool + BOT_RACE_HOUSE_SEED) - house_rake

        all_finished = all(h['finished'] for h in race)
        if now.hour < 12:
            time_status = f"⏳ Empieza {discord.utils.format_dt(today_12, 'R')}"
        elif all_finished:
            time_status = "🏁 **Carrera finalizada**"
        else:
            next_update = self.race_loop.next_iteration
            if next_update:
                time_status = f"🟢 Empezó {discord.utils.format_dt(today_12, 'R')} | Próximo avance: {discord.utils.format_dt(next_update, 'R')}"
            else:
                time_status = f"🟢 Empezó {discord.utils.format_dt(today_12, 'R')}"

        embed = discord.Embed(
            title="🏇 Gran Premio de Tres Cantos",
            description=f"**Estado de la pista** ({today_date}) | **Meta:** {int(TRACK_LENGTH)}m\n{time_status}",
            color=discord.Color.brand_green()
        )

        track_visual = ""
        for h in sorted(race, key=lambda x: x['horse_id']):
            progress = int((h['distance'] / TRACK_LENGTH) * 20)
            progress = min(20, max(0, progress))

            bar = "▰" * progress + "▱" * (20 - progress)
            if h['finished']:
                bar = "▰" * 20 + " 🏁"

            horse_bets = bets_by_horse.get(h['horse_id'], 0)
            est_multiplier = f"{distributable / horse_bets:.2f}x" if horse_bets > 0 else "N/A"

            track_visual += f"**#{h['horse_id']} - {h['horse_name']}** (Pozo: {horse_bets} 🪙 | Cuota est.: {est_multiplier})\n"
            track_visual += f"`[{bar}] {int(h['distance'])}m`\n\n"

        embed.add_field(name="Pista en Vivo", value=track_visual, inline=False)
        embed.add_field(
            name="💰 Pozo Total",
            value=f"**Total Apostado:** {total_player_pool} 🪙\n**Premio a Distribuir (con casa):** {distributable} 🪙",
            inline=False
        )

        if now.hour < 12:
            embed.set_footer(text="¡Aún puedes apostar!")
        else:
            embed.set_footer(text="¡Carrera en curso! Las apuestas que se hagan ahora serán para mañana.")

        await interaction.response.send_message(embed=embed)

    @caballos_group.command(name="apostar", description="Apuesta tus monedas a un caballo.")
    @app_commands.describe(
        caballo="El número del caballo (1-4)",
        cantidad="La cantidad de monedas a apostar"
    )
    async def apostar(self, interaction: discord.Interaction, caballo: app_commands.Range[int, 1, 4], cantidad: int):
        if cantidad <= 0:
            embed = discord.Embed(
                title="⚠️ Apuesta Inválida",
                description="La cantidad a apostar debe ser mayor a 0.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        now = datetime.datetime.now().astimezone()
        if now.hour < 12:
            target_date = now.strftime("%Y-%m-%d")
            target_dt = now.replace(hour=12, minute=0, second=0, microsecond=0)
            time_label = f"**HOY** ({discord.utils.format_dt(target_dt, 'R')})"
        else:
            tomorrow = now + datetime.timedelta(days=1)
            target_date = tomorrow.strftime("%Y-%m-%d")
            target_dt = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)
            time_label = f"**MAÑANA** ({discord.utils.format_dt(target_dt, 'R')})"

        success = await self.bot.db.betting_place_bet(interaction.user.id, target_date, caballo, cantidad)

        if not success:
            embed = discord.Embed(
                title="❌ Fondos Insuficientes",
                description="No tienes suficientes monedas para realizar esta apuesta.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await self.bot.global_stats.register_bet_placed(interaction.user.id, cantidad)

        embed = discord.Embed(
            title="🎟️ Apuesta Registrada",
            description=f"Has apostado **{cantidad}** monedas al caballo **#{caballo}** para la carrera de {time_label}.",
            color=discord.Color.gold()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text="¡Buena suerte en las gradas!")

        await interaction.response.send_message(embed=embed)

    @caballos_group.command(name="ultimacarrera", description="Mira los resultados de la última carrera completada.")
    async def ultimacarrera(self, interaction: discord.Interaction):
        last_date, race = await self.bot.db.betting_get_last_race()

        if not race:
            embed = discord.Embed(
                title="🏁 Resultados",
                description="Aún no hay registros de carreras finalizadas.",
                color=discord.Color.light_grey()
            )
            await interaction.response.send_message(embed=embed)
            return

        sorted_race = sorted(race, key=lambda h: (-h['distance'], h['finish_time'] or float('inf')))

        try:
            race_dt = datetime.datetime.strptime(last_date, "%Y-%m-%d").replace(hour=12).astimezone()
            date_display = discord.utils.format_dt(race_dt, "D")
        except ValueError:
            date_display = last_date

        embed = discord.Embed(
            title="🏁 Resultados: Gran Premio de Pavonia",
            description=f"**Fecha:** {date_display}",
            color=discord.Color.gold()
        )

        results_text = ""
        medals = ["🥇", "🥈", "🥉", "🏅"]
        for i, h in enumerate(sorted_race):
            results_text += f"{medals[i]} **{h['horse_name']}** *(Caballo #{h['horse_id']})*\n"

        embed.add_field(name="Clasificación Final", value=results_text, inline=False)
        embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/3253/3253086.png")

        await interaction.response.send_message(embed=embed)

    @caballos_group.command(name="misapuestas", description="Consulta tu historial de apuestas y resultados.")
    async def misapuestas(self, interaction: discord.Interaction):
        history = await self.bot.db.betting_get_user_history(interaction.user.id)

        if not history:
            embed = discord.Embed(
                title="📜 Tu Historial de Apuestas",
                description="No tienes apuestas registradas en el hipódromo.",
                color=discord.Color.light_grey()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(title="📜 Historial de Apuestas", color=discord.Color.blurple())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)

        for bet in history:
            if bet['result'] == "win":
                status = f"✅ **¡Ganaste {bet['payout']} monedas!**"
            elif bet['result'] == "loss":
                status = "❌ Perdiste"
            else:
                status = "⏳ En espera"

            horse_info = bet['horse_name'] if bet['horse_name'] else "Desconocido"

            try:
                race_dt = datetime.datetime.strptime(bet['race_date'], "%Y-%m-%d").replace(hour=12).astimezone()
                date_str = discord.utils.format_dt(race_dt, "d")
                relative_str = discord.utils.format_dt(race_dt, "R")
            except ValueError:
                date_str = bet['race_date']
                relative_str = "Desconocido"

            embed.add_field(
                name=f"📅 {date_str} | Caballo #{bet['horse_id']} ({horse_info})",
                value=f"**Apostado:** {bet['bet_amount']} monedas\n**Resultado:** {status}\n🕒 Carrera: {relative_str}",
                inline=False
            )

        await interaction.response.send_message(embed=embed)


async def setup(bot: JoseLuisBot):
    await bot.add_cog(HorseBetCog(bot))