import sqlite3
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


class GlobalStatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _fetch_user_stats(user_id: int) -> dict:
        with sqlite3.connect("bot_data.db") as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_global_stats WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return {}

    stats_group = app_commands.Group(
        name="estadisticas",
        description="Comandos para ver estadísticas del jugador"
    )

    @stats_group.command(name="casino", description="Mira estadísticas de los juegos de azar")
    async def stats_gambling(self, interaction: discord.Interaction, target: Optional[discord.User] = None):
        user = target or interaction.user
        data = self._fetch_user_stats(user.id)

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

        await interaction.response.send_message(embed=embed)

    @stats_group.command(name="economia", description="Mira estadísticas de flujo de dinero y movimientos")
    async def stats_economy(self, interaction: discord.Interaction, target: Optional[discord.User] = None):
        user = target or interaction.user
        data = self._fetch_user_stats(user.id)

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
        data = self._fetch_user_stats(user.id)

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


async def setup(bot: commands.Bot):
    await bot.add_cog(GlobalStatsCog(bot))