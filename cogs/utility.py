import os

from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands

from main import JoseLuisBot


class EraseConfirmModal(discord.ui.Modal):
    def __init__(self, bot: JoseLuisBot, target_id: int):
        super().__init__(title="Confirmar borrado")
        self.bot = bot
        self.target_id = target_id
        self.user_id_input = discord.ui.TextInput(
            label=f"Escribe el ID {target_id} para confirmar",
            placeholder=str(target_id),
            min_length=1,
            max_length=32,
        )
        self.add_item(self.user_id_input)
        self.balance_input = discord.ui.TextInput(
            label="¿Cuántos choskris tiene? (100 si no tiene perfil)",
            placeholder="Mira su saldo con /choskris",
            min_length=1,
            max_length=32,
        )
        self.add_item(self.balance_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if self.user_id_input.value.strip() != str(self.target_id):
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ El ID no coincide. No se ha borrado nada.", color=discord.Color.red()),
                ephemeral=True,
            )
            return
        balance = await self.bot.db.economy.peek_balance(self.target_id)
        typed_balance = "".join(character for character in self.balance_input.value if character.isdigit())
        if typed_balance != str(balance):
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ La cantidad de choskris no coincide. No se ha borrado nada.", color=discord.Color.red()),
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            embed=discord.Embed(description="⏳ Borrando datos...", color=discord.Color.orange()),
            view=None,
        )
        counts = await self.bot.db.merger.erase(self.target_id)
        self.bot.scientific_users.discard(self.target_id)
        await interaction.edit_original_response(
            embed=discord.Embed(
                title="🗑️ Datos borrados",
                description=f"Se han borrado **{sum(counts.values())} filas** de <@{self.target_id}>.",
                color=discord.Color.dark_green(),
            ),
            view=None,
        )


class EraseUserView(discord.ui.View):
    def __init__(self, bot: JoseLuisBot, author_id: int, target_id: int):
        super().__init__(timeout=120)
        self.bot = bot
        self.author_id = author_id
        self.target_id = target_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Solo quien ejecutó el comando puede confirmar esto.", color=discord.Color.red()),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Borrar todo", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(EraseConfirmModal(self.bot, self.target_id))

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(description="❌ Borrado cancelado. No se ha modificado nada.", color=discord.Color.greyple()),
            view=self,
        )


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

    @utility_group.command(name="notacioncientifica", description="Muestra los números a partir de un millón en notación científica")
    @app_commands.describe(activar="Activar o desactivar la notación científica")
    async def scientific_notation(self, interaction: discord.Interaction, activar: bool):
        await self.bot.db.settings.set_scientific_notation(interaction.user.id, activar)
        if activar:
            self.bot.scientific_users.add(interaction.user.id)
        else:
            self.bot.scientific_users.discard(interaction.user.id)
        message = "✅ Los números desde un millón se mostrarán en notación científica." if activar else "✅ Los números se mostrarán de forma normal."
        await interaction.response.send_message(embed=discord.Embed(description=message, color=discord.Color.green()), ephemeral=True)

    @utility_group.command(name="apagar", description="Apagar el bot (se va a reiniciar)")
    async def shutdown(self, interaction: discord.Interaction):
        if await self.bot.filter_owner(interaction): return

        await interaction.response.send_message("Shutting down...", ephemeral=True)
        await self.bot.db.close()
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
    async def execsql(self, interaction: discord.Interaction, query: str):
        if await self.bot.filter_owner(interaction): return

        await interaction.response.defer(ephemeral=True)

        async def run_db_query(sql: str) -> tuple[str, Any, Any]:
            async with self.bot.db.execute(sql) as cursor:
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    rows = await cursor.fetchall()
                    dict_rows = [dict(zip(columns, row)) for row in rows]
                    return "SELECT", columns, dict_rows

                affected_rows = cursor.rowcount

            await self.bot.db.commit()
            return "MUTATION", affected_rows, None

        try:
            query_type, result_data, rows = await run_db_query(query)

            if query_type == "MUTATION":
                await interaction.followup.send(
                    f"**Sentencia ejecutada correctamente.**\n"
                    f"**Filas afectadas:** `{result_data}`"
                )
            else:
                if not rows:
                    await interaction.followup.send("La consulta no devolvió resultados (0 filas).")
                    return

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

    @utility_group.command(name="execsqlscript", description="Ejecuta un script SQL en la base de datos")
    async def execsqlscript(self, interaction: discord.Interaction, script: str):
        if await self.bot.filter_owner(interaction): return

        await self.bot.db.executescript(script)
        await self.bot.db.commit()

        await interaction.response.send_message("Script SQL ejecutado correctamente.", ephemeral=True)

    @utility_group.command(name="execsqlfile", description="Ejecuta un archivo SQL en la base de datos")
    async def execsqlfile(self, interaction: discord.Interaction, file: discord.Attachment):
        if await self.bot.filter_owner(interaction): return

        await interaction.response.defer(ephemeral=True)

        if not file.filename.endswith(".sql"):
            await interaction.followup.send("El archivo debe ser un script `.sql`.", ephemeral=True)
            return

        try:
            sql_content = (await file.read()).decode("utf-8")

            await self.bot.db.executescript(sql_content)
            await self.bot.db.commit()

            await interaction.followup.send("Script SQL ejecutado correctamente.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error al ejecutar el script SQL:\n```py\n{e}\n```", ephemeral=True)

    @utility_group.command(name="borrardatos", description="Borra todos tus datos en el bot (el dueño puede borrar los de cualquiera)")
    @app_commands.describe(usuario="Usuario cuyos datos se van a borrar (EH TU, QUITA DE AQUI SI NO ERES ASPER)")
    async def erase_user_data(self, interaction: discord.Interaction, usuario: Optional[str] = None):
        if usuario is None or not usuario.strip():
            target_id = interaction.user.id
        elif usuario.strip().isdecimal() and 0 < int(usuario.strip()) < 2**64:
            target_id = int(usuario.strip())
        else:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ El ID no es válido: debe ser un número.", color=discord.Color.red()),
                ephemeral=True,
            )
            return
        if target_id != interaction.user.id and await self.bot.filter_owner(interaction): return

        await interaction.response.defer(ephemeral=True)
        counts = await self.bot.db.merger.preview(target_id)

        if not counts:
            await interaction.followup.send(
                embed=discord.Embed(description=f"❌ <@{target_id}> no tiene ningún dato registrado.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🗑️ Borrar datos de usuario",
            description=(
                f"Se borrarán **{sum(counts.values())} filas** de <@{target_id}>.\n\n"
                "**Es irreversible.** Su cuenta de Discord no se toca, solo sus datos en el bot.\n\n"
                f"Para confirmar tendrás que escribir su ID (`{target_id}`) y cuántos choskris tiene ahora mismo (100 si no tiene perfil de economía)."
            ),
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="Tablas afectadas", value="\n".join(f"`{table}`: {count}" for table, count in counts.items()), inline=False)
        await interaction.followup.send(embed=embed, view=EraseUserView(self.bot, interaction.user.id, target_id), ephemeral=True)

    @utility_group.command(name="error")
    async def causeerror(self, interaction: discord.Interaction):
        if await self.bot.filter_owner(interaction): return
        await interaction.response.send_message(f"{1/0}")

async def setup(bot: JoseLuisBot):
    await bot.add_cog(UtilityCog(bot))