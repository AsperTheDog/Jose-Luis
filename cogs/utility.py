import asyncio
import os
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

from main import JoseLuisBot


class UtilityCog(commands.Cog):
    utility_group = app_commands.Group(
        name="utilidades",
        description="Comandos con distintas utilidades"
    )

    def __init__(self, bot: JoseLuisBot):
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

    @utility_group.command(name="dumpdb", description="Descarga una copia de la base de datos (bot_data.db)")
    async def dumpdb(self, interaction: discord.Interaction):
        if await self.bot.filter_owner(interaction): return

        db_path = "bot_data.db"

        if not os.path.exists(db_path):
            await interaction.response.send_message("No se encontró el archivo de la base de datos.", ephemeral=True)
            return

        file = discord.File(db_path, filename="bot_data.db")
        await interaction.response.send_message("Aquí tienes una copia actual de la base de datos:", file=file, ephemeral=True)

    @utility_group.command(name="execsql", description="Ejecuta una consulta SQL en bot_data.db con formato de tabla alineada.")
    @app_commands.describe(query="La sentencia SQL a ejecutar (SELECT, UPDATE, INSERT, DELETE, etc.)")
    async def exec_sql(self, interaction: discord.Interaction, query: str):
        if await self.bot.filter_owner(interaction): return

        await interaction.response.defer(ephemeral=True)

        def run_db_query(sql: str, db_path: str = "bot_data.db"):
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(sql)

                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    return ("SELECT", columns, [dict(row) for row in rows])
                else:
                    conn.commit()
                    return ("MUTATION", cursor.rowcount, None)

        try:
            query_type, result_data, rows = await asyncio.to_thread(run_db_query, query)

            if query_type == "MUTATION":
                await interaction.followup.send(
                    f"**Sentencia ejecutada correctamente.**\n"
                    f"**Filas afectadas:** `{result_data}`"
                )
            else:
                if not rows:
                    return await interaction.followup.send("La consulta no devolvió resultados (0 filas).")

                columns = result_data
                display_rows = rows[:15]

                col_widths = {}
                for col in columns:
                    max_len = len(str(col))
                    for row in display_rows:
                        val_str = str(row[col]) if row[col] is not None else "NULL"
                        max_len = max(max_len, len(val_str))
                    col_widths[col] = min(max_len, 30)

                header_cells = [f"{col:<{col_widths[col]}}"[:col_widths[col]] for col in columns]
                header_line = " | ".join(header_cells)
                separator_line = "-+-".join("-" * col_widths[col] for col in columns)

                lines = [header_line, separator_line]

                for row in display_rows:
                    row_cells = []
                    for col in columns:
                        val_str = str(row[col]) if row[col] is not None else "NULL"
                        if len(val_str) > col_widths[col]:
                            val_str = val_str[:col_widths[col] - 1] + "…"
                        row_cells.append(f"{val_str:<{col_widths[col]}}")
                    lines.append(" | ".join(row_cells))

                output = "\n".join(lines)
                if len(rows) > 15:
                    output += f"\n... ({len(rows) - 15} filas adicionales ocultas)"

                if len(output) > 1900:
                    output = output[:1900] + "\n... [Resultado truncado]"

                await interaction.followup.send(f"```text\n{output}\n```")

        except Exception as e:
            await interaction.followup.send(f"**Error al ejecutar SQL:**\n```py\n{e}\n```")

async def setup(bot: JoseLuisBot):
    await bot.add_cog(UtilityCog(bot))