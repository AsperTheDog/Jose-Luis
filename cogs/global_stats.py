from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from main import JoseLuisBot


class GlobalStatsCog(commands.Cog):
    def __init__(self, bot: JoseLuisBot):
        self.bot = bot

    stats_group = app_commands.Group(
        name="estadisticas",
        description="Comandos para ver estadísticas del jugador"
    )

    @stats_group.command(name="casino", description="Mira estadísticas de los juegos de azar")
    async def stats_gambling(self, interaction: discord.Interaction, target: Optional[discord.User] = None):
        user = target or interaction.user
        data = await self.bot.db.global_fetch_user_stats(user.id)

        embed = discord.Embed(
            title=f"🎰 Estadísticas de Casino - {user.display_name}",
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        r_win = data.get("roulette_bets_won", 0)
        r_loss = data.get("roulette_bets_lost", 0)
        r_gained = data.get("roulette_money_gained", 0)
        r_lost = data.get("roulette_money_lost", 0)
        r_max = data.get("roulette_biggest_bet", 0)
        embed.add_field(
            name="🔴 Ruleta",
            value=(
                f"**Vi/De:** {r_win} / {r_loss}\n"
                f"**Obtenido:** ${r_gained:,}\n"
                f"**Perdido:** ${r_lost:,}\n"
                f"**Beneficios:** ${(r_gained - r_lost):,}\n"
                f"**Mayor Apuesta:** ${r_max:,}"
            ),
            inline=True,
        )

        d_win = data.get("dice_bets_won", 0)
        d_loss = data.get("dice_bets_lost", 0)
        d_gained = data.get("dice_money_gained", 0)
        d_lost = data.get("dice_money_lost", 0)
        d_max = data.get("dice_biggest_bet", 0)
        embed.add_field(
            name="🎲 Dados",
            value=(
                f"**Vi/De:** {d_win} / {d_loss}\n"
                f"**Obtenido:** ${d_gained:,}\n"
                f"**Perdido:** ${d_lost:,}\n"
                f"**Beneficios:** ${(d_gained - d_lost):,}\n"
                f"**Mayor Apuesta:** ${d_max:,}"
            ),
            inline=True,
        )

        s_win = data.get("slots_bets_won", 0)
        s_loss = data.get("slots_bets_lost", 0)
        s_gained = data.get("slots_money_gained", 0)
        s_lost = data.get("slots_money_lost", 0)
        s_max = data.get("slots_biggest_bet", 0)
        embed.add_field(
            name="🎰 Tragaperras",
            value=(
                f"**Vi/De:** {s_win} / {s_loss}\n"
                f"**Obtenido:** ${s_gained:,}\n"
                f"**Perdido:** ${s_lost:,}\n"
                f"**Beneficios:** ${(s_gained - s_lost):,}\n"
                f"**Mayor Apuesta:** ${s_max:,}"
            ),
            inline=True,
        )

        c_win = data.get("cards_bets_won", 0)
        c_loss = data.get("cards_bets_lost", 0)
        c_gained = data.get("cards_money_gained", 0)
        c_lost = data.get("cards_money_lost", 0)
        c_max = data.get("cards_biggest_bet", 0)
        embed.add_field(
            name="🃏 Cartas",
            value=(
                f"**Vi/De:** {c_win} / {c_loss}\n"
                f"**Obtenido:** ${c_gained:,}\n"
                f"**Perdido:** ${c_lost:,}\n"
                f"**Beneficios:** ${(c_gained - c_lost):,}\n"
                f"**Mayor Apuesta:** ${c_max:,}"
            ),
            inline=True,
        )

        await interaction.response.send_message(embed=embed)

    @stats_group.command(name="economia", description="Mira estadísticas de flujo de dinero y movimientos")
    async def stats_economy(self, interaction: discord.Interaction, target: Optional[discord.User] = None):
        user = target or interaction.user
        data = await self.bot.db.global_fetch_user_stats(user.id)

        embed = discord.Embed(
            title=f"💸 Economía y Crímen - {user.display_name}",
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        gained = data.get("money_obtained", 0)
        spent = data.get("money_spent", 0)
        peak = data.get("highest_money_accumulated", 0)
        interest = data.get("interest_money_gained", 0)
        embed.add_field(
            name="🏦 Resumen y Capital",
            value=(
                f"**Total Ganado:** ${gained:,}\n"
                f"**Total Gastado:** ${spent:,}\n"
                f"**Máximo Acumulado:** ${peak:,}\n"
                f"**Interés Obtenido:** ${interest:,}"
            ),
            inline=False,
        )

        work_count = data.get("times_worked", 0)
        work_cash = data.get("money_from_work", 0)
        job_switches = data.get("times_switched_jobs", 0)
        allowance_count = data.get("times_asked_allowance", 0)
        allowance_cash = data.get("money_from_allowance", 0)
        allowance_streak = data.get("biggest_allowance_streak", 0)
        drops = data.get("drops_claimed", 0)
        drop_cash = data.get("money_from_drops", 0)
        embed.add_field(
            name="💼 Trabajo y Actividades",
            value=(
                f"**Trabajos Hechos:** {work_count} jornadas (${work_cash:,})\n"
                f"**Cambios de Empleo:** {job_switches}\n"
                f"**Pagas Reclamadas:** {allowance_count} veces (${allowance_cash:,})\n"
                f"**Racha Máxima de Pagas:** {allowance_streak} días\n"
                f"**Drops Reclamados:** {drops} (${drop_cash:,})"
            ),
            inline=True,
        )

        given = data.get("money_given", 0)
        received = data.get("money_received", 0)
        max_gift = data.get("biggest_money_gift", 0)
        embed.add_field(
            name="🤝 Transferencias",
            value=(
                f"**Dinero Regalado:** ${given:,}\n"
                f"**Dinero Recibido:** ${received:,}\n"
                f"**Mayor Regalo Enviado:** ${max_gift:,}"
            ),
            inline=True,
        )

        crimes = data.get("crimes_successful", 0)
        crime_cash = data.get("crime_money_gained", 0)
        jail_time = data.get("times_gone_to_jail", 0)
        fines = data.get("crime_fines_paid", 0)
        embed.add_field(
            name="🚨 Crímen",
            value=(
                f"**Crímenes Exitosos:** {crimes} (${crime_cash:,})\n"
                f"**Veces en la Cárcel:** {jail_time}\n"
                f"**Dinero Multado:** ${fines:,}"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=embed)

    @stats_group.command(name="mineria", description="Mira estadísticas de minería y forja")
    async def stats_mining(self, interaction: discord.Interaction, target: Optional[discord.User] = None):
        user = target or interaction.user
        data = await self.bot.db.global_fetch_user_stats(user.id)

        embed = discord.Embed(
            title=f"⛏️ Minería - {user.display_name}",
            color=discord.Color.dark_orange(),
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        mined = data.get("times_mined", 0)
        energy = data.get("energy_spent", 0)
        mats = data.get("materials_mined", 0)
        drank = data.get("times_drank", 0)
        drink_cash = data.get("money_spent_drinking", 0)
        embed.add_field(
            name="⛏️ Trabajo en la Mina",
            value=(
                f"**Veces en la Mina:** {mined:,}\n"
                f"**Energía gastada:** {energy:,}\n"
                f"**Materiales Extraídos:** {mats:,}\n"
                f"**Bebidas consumidas:** {drank:,} (${drink_cash:,})"
            ),
            inline=True,
        )

        picks_claimed = data.get("basic_pickaxes_claimed", 0)
        picks_broken = data.get("pickaxes_broken", 0)
        crafted = data.get("items_crafted", 0)
        embed.add_field(
            name="🛠️ Forja",
            value=(
                f"**Picos Básicos Reclamados:** {picks_claimed}\n"
                f"**Picos Rotos:** {picks_broken}\n"
                f"**Objetos Forjados:** {crafted:,}"
            ),
            inline=True,
        )

        sold = data.get("items_sold", 0)
        sales_cash = data.get("item_sales_money_gained", 0)
        embed.add_field(
            name="⚖️ Mercado",
            value=(
                f"**Objetos Vendidos:** {sold:,}\n"
                f"**Ganancias:** ${sales_cash:,}"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=embed)

    @stats_group.command(name="hackeo", description="Mira estadísticas de los ataques informáticos")
    async def stats_hacking(self, interaction: discord.Interaction, target: Optional[discord.User] = None):
        user = target or interaction.user
        data = await self.bot.db.global_fetch_user_stats(user.id)

        embed = discord.Embed(
            title=f"💻 Hackeo - {user.display_name}",
            color=discord.Color.purple(),
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        easy = data.get("hacking_times_hacked_easy", 0)
        normal = data.get("hacking_times_hacked_normal", 0)
        hard = data.get("hacking_times_hacked_hard", 0)
        veryhard = data.get("hacking_times_hacked_very_hard", 0)
        total_success = easy + normal + hard + veryhard

        embed.add_field(
            name="✅ Éxitos",
            value=(
                f"**Fácil:** {easy:,}\n"
                f"**Normal:** {normal:,}\n"
                f"**Difícil:** {hard:,}\n"
                f"**Muy Difícil:** {veryhard:,}\n"
                f"**Total:** {total_success:,}"
            ),
            inline=True,
        )

        timeout = data.get("hacking_times_failed_timeout", 0)
        firewall = data.get("hacking_times_failed_firewall", 0)
        lost = data.get("hacking_times_failed_lost", 0)
        total_failed = timeout + firewall + lost

        embed.add_field(
            name="❌ Fallos",
            value=(
                f"**Tiempo Agotado:** {timeout:,}\n"
                f"**Bloqueo Firewall:** {firewall:,}\n"
                f"**Fallo del objetivo:** {lost:,}\n"
                f"**Total:** {total_failed:,}"
            ),
            inline=True,
        )

        time_elapsed = data.get("hacking_time_spent", 0.0)
        money_gained = data.get("hacking_money_gained", 0)
        total_attempts = total_success + total_failed
        win_rate = (total_success / total_attempts * 100) if total_attempts > 0 else 0.0

        embed.add_field(
            name="📊 Balance General",
            value=(
                f"**Ganancias Totales:** ${money_gained:,}\n"
                f"**Ataques Totales:** {total_attempts:,}\n"
                f"**Tasa de Éxito:** {win_rate:.1f}%\n"
                f"**Tiempo jugado:** {time_elapsed:.1f}s"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=embed)

    @stats_group.command(name="gacha", description="Mira estadísticas del sistema de invocación de personajes")
    async def stats_gacha(self, interaction: discord.Interaction, target: Optional[discord.User] = None):
        user = target or interaction.user
        data = await self.bot.db.global_fetch_user_stats(user.id)

        embed = discord.Embed(
            title=f"🎰 Gacha - {user.display_name}",
            color=discord.Color.dark_purple(),
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        throws = data.get("gacha_throws", 0)
        boosted = data.get("gacha_boosted_throws", 0)
        embed.add_field(
            name="🎲 Tiradas",
            value=(
                f"**Total:** {throws:,}\n"
                f"**Potenciadas:** {boosted:,}\n"
            ),
            inline=True,
        )

        s2 = data.get("gacha_shards_obtained_2", 0)
        s3 = data.get("gacha_shards_obtained_3", 0)
        s4 = data.get("gacha_shards_obtained_4", 0)
        s5 = data.get("gacha_shards_obtained_5", 0)
        embed.add_field(
            name="🧩 Fragmentos Obtenidos",
            value=(
                f"**2★:** {s2:,}\n"
                f"**3★:** {s3:,}\n"
                f"**4★:** {s4:,}\n"
                f"**5★:** {s5:,}"
            ),
            inline=True,
        )

        crafted = data.get("gacha_units_crafted", 0)
        destroyed = data.get("gacha_shards_destroyed", 0)
        dust_obtained = data.get("gacha_dust_obtained", 0)
        dust_spent = data.get("gacha_dust_spent", 0)
        embed.add_field(
            name="💨 Forja y Polvo Gacha",
            value=(
                f"**Unidades Creadas:** {crafted:,}\n"
                f"**Fragmentos Destruidos:** {destroyed:,}\n"
                f"**Polvo Obtenido:** {dust_obtained:,}\n"
                f"**Polvo Gastado:** {dust_spent:,}"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot: JoseLuisBot):
    await bot.add_cog(GlobalStatsCog(bot))