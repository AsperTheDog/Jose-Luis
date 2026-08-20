import asyncio
import datetime

import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import aiosqlite
import json
import random
from typing import Optional

from main import JoseLuisBot

DB_PATH = "bot_data.db"
JSON_PATH = "mining.json"


class AscensorView(discord.ui.View):
    def __init__(self, user_id: int, levels: dict):
        super().__init__(timeout=60)
        self.user_id = user_id

        options = []
        for level_id, data in levels.items():
            options.append(discord.SelectOption(
                label=data["name"],
                value=level_id,
                description=f"Dureza: {data['hardness']}"
            ))

        self.select = discord.ui.Select(placeholder="Elige a qué profundidad descender...", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Estos botones no son para ti.", ephemeral=True)
            return

        selected_level = self.select.values[0]
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE mining_users SET current_depth_id = ? WHERE user_id = ?", (selected_level, self.user_id))
            conn.commit()

        await interaction.response.edit_message(content=f"🛗 El ascensor te ha llevado a: **{selected_level}**", view=None)


class MiningSystemCog(commands.Cog):
    def __init__(self, bot: JoseLuisBot):
        self.bot = bot
        self.active_miners = set()
        self._init_db()

        with open(JSON_PATH, "r", encoding="utf-8") as f:
            self.game_data = json.load(f)

    mining_group = app_commands.Group(
        name="mineria",
        description="Comandos para minar y forjar objetos"
    )

    def cog_unload(self):
        self.daily_reset_task.cancel()

    def _init_db(self):
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.executescript("""
                 CREATE TABLE IF NOT EXISTS mining_users
                 (
                     user_id          INTEGER PRIMARY KEY,
                     xp               INTEGER DEFAULT 0,
                     level            INTEGER DEFAULT 1,
                     energy           INTEGER DEFAULT 100,
                     current_depth_id TEXT    DEFAULT 'superficie',
                     refills          INTEGER DEFAULT 0,
                     last_basic_pick  DATETIME
                 );
                 CREATE TABLE IF NOT EXISTS mining_inv_materials
                 (
                     user_id     INTEGER,
                     material_id TEXT,
                     amount      INTEGER,
                     PRIMARY KEY (user_id, material_id)
                 );
                 CREATE TABLE IF NOT EXISTS mining_inv_valuables
                 (
                     user_id     INTEGER,
                     valuable_id TEXT,
                     amount      INTEGER,
                     PRIMARY KEY (user_id, valuable_id)
                 );
                 CREATE TABLE IF NOT EXISTS mining_inv_pickaxes
                 (
                     id          INTEGER PRIMARY KEY AUTOINCREMENT,
                     user_id     INTEGER,
                     pickaxe_id  TEXT,
                     durability  INTEGER,
                     is_equipped INTEGER DEFAULT 0
                 );
                 """)
            conn.commit()

    def _get_or_create_user(self, user_id: int):
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO mining_users (user_id) VALUES (?)", (user_id,))
            conn.commit()

    @mining_group.command(name="minar", description="Usa tu pico y energía para obtener materiales.")
    async def mine(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        self._get_or_create_user(user_id)

        if user_id in self.active_miners:
            await interaction.response.send_message("**¡Ya estás minando!** Espera a que termine tu acción actual antes de volver a picar.", ephemeral=True)
            return

        self.active_miners.add(user_id)

        try:
            async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
                async with db.execute("SELECT energy, current_depth_id, xp, level FROM mining_users WHERE user_id = ?", (user_id,)) as cursor:
                    row = await cursor.fetchone()
                    energy, depth_id, current_xp, user_lvl = row

                async with db.execute("SELECT id, pickaxe_id, durability FROM mining_inv_pickaxes WHERE user_id = ? AND is_equipped = 1", (user_id,)) as cursor:
                    equipped_pick = await cursor.fetchone()

            if not equipped_pick:
                await interaction.response.send_message("No tienes ningún pico equipado. Usa `/equipar` o `/obtenerpico`.", ephemeral=True)
                return

            level_data = self.game_data["levels"][depth_id]
            energy_cost = level_data.get("energy_cost", 10)

            if energy < energy_cost:
                await interaction.response.send_message(f"No tienes suficiente energía para picar aquí ({energy_cost} requeridos). Usa `/beber`.", ephemeral=True)
                return

            db_pick_id, pickaxe_key, durability = equipped_pick
            pickaxe_data = self.game_data["pickaxes"][pickaxe_key]
            net_power = pickaxe_data["efficiency"] - level_data["hardness"] + user_lvl

            if net_power <= 0:
                async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
                    await db.execute("UPDATE mining_users SET energy = energy - ? WHERE user_id = ?",(energy_cost, user_id),)
                    await db.commit()

                await interaction.response.send_message(
                    f"⚠️ La roca en **{level_data['name']}** es demasiado dura para tu nivel y pico actual.\n"
                    f"*Pierdes {energy_cost} de energía, pero tu pico no sufre desgaste.*",
                    ephemeral=True
                )
                return

            raw_yield = 20 * (net_power / (net_power + 20))
            total_yield = max(1, round(raw_yield))
            dropped_material = random.choice(level_data["drops"])
            mat_data = self.game_data["materials"][dropped_material]

            new_durability = durability - 1
            durability_msg = f"Durabilidad pico: {new_durability}/{pickaxe_data['max_durability']}"

            async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
                await db.execute("UPDATE mining_users SET energy = energy - ? WHERE user_id = ?", (energy_cost, user_id))

                if new_durability <= 0:
                    await db.execute("DELETE FROM mining_inv_pickaxes WHERE id = ?", (db_pick_id,))
                    durability_msg = f"💥 **¡Tu {pickaxe_data['name']} se ha roto!**"
                    self.bot.global_stats.register_pickaxe_broken(interaction.user.id)
                else:
                    await db.execute("UPDATE mining_inv_pickaxes SET durability = ? WHERE id = ?",(new_durability, db_pick_id),)

                await db.execute("""
                    INSERT INTO mining_inv_materials (user_id, material_id, amount)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, material_id) DO UPDATE SET amount = amount + ?
                    """, (user_id, dropped_material, total_yield, total_yield),)

                new_xp = current_xp + 10
                required_xp = int(100 * (user_lvl ** 1.5))
                lvl_up_msg = ""

                if new_xp >= required_xp:
                    await db.execute("UPDATE mining_users SET xp = ?, level = level + 1 WHERE user_id = ?", (new_xp - required_xp, user_id))
                    lvl_up_msg = f"\n⬆️ **¡Has subido al Nivel Minero {user_lvl + 1}!**"
                else:
                    await db.execute("UPDATE mining_users SET xp = ? WHERE user_id = ?", (new_xp, user_id))

                await db.commit()

            hit_1 = total_yield // 3
            hit_2 = total_yield // 3
            hit_3 = total_yield - (hit_1 + hit_2)
            hits = [hit_1, hit_2, hit_3]

            embed = discord.Embed(
                title=f"⛏️ Picando en {level_data['name']}...",
                description="*Buscando una buena veta de mineral...*\n\n`[░░░░░░░░░░] 0%`",
                color=discord.Color.dark_grey()
            )
            await interaction.response.send_message(embed=embed)

            accumulated_yield = 0
            stages = [
                ("*¡CLANG!* Golpeando la primera capa de roca...", "`[███░░░░░░░] 33%`", hits[0]),
                ("*¡CRACK!* Abriendo la veta principal...", "`[███████░░░] 66%`", hits[1]),
                ("*¡Último picado!* Extrayendo minerales...", "`[██████████] 100%`", hits[2])
            ]

            for text, progress_bar, count in stages:
                await asyncio.sleep(2)
                accumulated_yield += count

                embed.description = (
                    f"{text}\n\n"
                    f"{progress_bar}\n"
                    f"⛏️ **Recolectado:** +{accumulated_yield}x {mat_data['name']} {mat_data['emoji']}"
                )
                await interaction.edit_original_response(embed=embed)

            self.bot.global_stats.register_mine_action(interaction.user.id, energy_cost, total_yield)
            final_embed = discord.Embed(
                title="✅ ¡Extracción Completada!",
                description=(
                    f"Has terminado de minar en **{level_data['name']}** (-{energy_cost}⚡).\n\n"
                    f"📦 **Obtenido:** **{total_yield}x {mat_data['name']}** {mat_data['emoji']}\n"
                    f"🛠️ {durability_msg}{lvl_up_msg}"
                ),
                color=discord.Color.green()
            )
            await interaction.edit_original_response(embed=final_embed)
        finally:
            self.active_miners.discard(user_id)

    @mining_group.command(name="beber", description="Compra y bebe una bebida energética al instante con Choskris.")
    @app_commands.describe(modo="Elige si quieres tomar una lata (+50) o rellenar al máximo (+100)")
    @app_commands.choices(modo=[
        app_commands.Choice(name="Lata Normal (+50 Energía) - 100 Choskris", value="single"),
        app_commands.Choice(name="Relleno Total (100% Energía)", value="full")
    ])
    async def drink(self, interaction: discord.Interaction, modo: Optional[str] = "single"):
        user_id = interaction.user.id
        self._get_or_create_user(user_id)

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT energy, level, refills FROM mining_users WHERE user_id = ?", (user_id,))
            energy, user_lvl, refills = cursor.fetchone()
            cursor.execute("SELECT balance FROM economy_users WHERE user_id = ?", (user_id,))
            choskris = cursor.fetchone()[0]

            cost_per_energy = min(8, int(2 + (0.5 * ((user_lvl - 1) ** 1.2))))
            final_cost = cost_per_energy * (1.5 ** refills)
            cost_perc = int(((final_cost / cost_per_energy) - 1) * 100)

            if energy >= 100:
                await interaction.response.send_message("Tu energía ya está al máximo (100/100).", ephemeral=True)
                return

            if modo == "full":
                needed_energy = 100 - energy
                total_cost = int(needed_energy * final_cost)
                gain = needed_energy
            else:
                gain = min(50, 100 - energy)
                total_cost = int(gain * final_cost)

            if choskris < total_cost:
                await interaction.response.send_message(f"No tienes suficientes Choskris. Necesitas **{total_cost} Choskris** para restaurar +{gain} de energía *(Tienes: {choskris})*.", ephemeral=True)
                return

            new_energy = energy + gain
            new_choskris = choskris - total_cost
            cursor.execute("UPDATE mining_users SET energy = ?, refills = refills + 1 WHERE user_id = ?", (new_energy, user_id))
            cursor.execute("UPDATE economy_users SET balance = ? WHERE user_id = ?", (new_choskris, user_id))
            conn.commit()

        refill_alert = "" if cost_perc == 0 else f" (+{cost_perc}% por {refills + 1} bebidas hoy)"
        self.bot.global_stats.register_drink_action(interaction.user.id, total_cost)
        await interaction.response.send_message(
            f"🥤 Has comprado una bebida por **{total_cost} Choskris**{refill_alert}.\n"
            f"⚡ **Energía:** {new_energy}/100 (+{gain})\n"
        )

    @mining_group.command(name="ascensor", description="Cambia el nivel de profundidad en el que minas.")
    async def elevator(self, interaction: discord.Interaction):
        self._get_or_create_user(interaction.user.id)
        view = AscensorView(interaction.user.id, self.game_data["levels"])
        await interaction.response.send_message("🛗 Selecciona tu destino:", view=view)

    @mining_group.command(name="obtenerpico", description="Reclama un pico de piedra básico gratuito.")
    async def get_pickaxe(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        self._get_or_create_user(user_id)

        pick_id = "pico_piedra"
        max_dur = self.game_data["pickaxes"][pick_id]["max_durability"]

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT last_basic_pick FROM mining_users WHERE user_id = ?", (user_id,))
            last_pick = cursor.fetchone()[0]
            last_pick = datetime.datetime.fromisoformat(last_pick) if last_pick else None
            now = datetime.datetime.now()
            if last_pick:
                cooldown = last_pick - now
                if cooldown < datetime.timedelta(days=1):
                    h, r = divmod(cooldown.seconds, 3600)
                    m, s = divmod(r, 60)
                    await interaction.response.send_message(f"El herrero está descansando. Vuelve en {h}h {m}m.", ephemeral=True)
                    return

            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM mining_inv_pickaxes WHERE user_id = ? AND is_equipped = 1", (user_id,))
            has_equipped = cursor.fetchone()[0] > 0

            is_equipped = 0 if has_equipped else 1
            cursor.execute("UPDATE mining_users SET last_basic_pick = ? WHERE user_id = ?", (now.isoformat(), user_id))
            cursor.execute("INSERT INTO mining_inv_pickaxes (user_id, pickaxe_id, durability, is_equipped) VALUES (?, ?, ?, ?)", (user_id, pick_id, max_dur, is_equipped))
            conn.commit()

        self.bot.global_stats.register_basic_pickaxe_claim(interaction.user.id)
        await interaction.response.send_message("🪨 Has recibido tu **Pico de Piedra** gratuito.")

    @mining_group.command(name="equipar", description="Equipa un pico de tu inventario. No pongas número para ver la lista.")
    @app_commands.describe(indice="El número del pico que quieres equipar")
    async def equip(self, interaction: discord.Interaction, indice: Optional[int] = None):
        user_id = interaction.user.id

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, pickaxe_id, durability, is_equipped FROM mining_inv_pickaxes WHERE user_id = ? ORDER BY id ", (user_id,))
            pickaxes = cursor.fetchall()

        if not pickaxes:
            await interaction.response.send_message("No tienes picos. Usa `/obtenerpico` o `/forjar`.", ephemeral=True)
            return

        if indice is None:
            msg = "**Tus Picos:**\n"
            for i, p in enumerate(pickaxes, 1):
                p_data = self.game_data["pickaxes"][p[1]]
                status = "✅ [Equipado]" if p[3] == 1 else ""
                msg += f"`[{i}]` {p_data['emoji']} **{p_data['name']}** - Dur: {p[2]}/{p_data['max_durability']} {status}\n"
            msg += "\n*Usa `/equipar [número]` para equipar uno.*"
            await interaction.response.send_message(msg)
            return

        if indice < 1 or indice > len(pickaxes):
            await interaction.response.send_message("Índice no válido.", ephemeral=True)
            return

        target_db_id = pickaxes[indice - 1][0]
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE mining_inv_pickaxes SET is_equipped = 0 WHERE user_id = ?", (user_id,))
            cursor.execute("UPDATE mining_inv_pickaxes SET is_equipped = 1 WHERE id = ?", (target_db_id,))
            conn.commit()

        pick_data = self.game_data["pickaxes"][pickaxes[indice - 1][1]]
        await interaction.response.send_message(f"✅ Has equipado: **{pick_data['name']}** {pick_data['emoji']}")

    @mining_group.command(name="forjar", description="Craftea objetos o picos. Si no pasas ID, verás la lista de recetas.")
    @app_commands.describe(receta_id="El ID interno de la receta (Opcional)")
    async def craft(self, interaction: discord.Interaction, receta_id: Optional[str] = None):
        user_id = interaction.user.id
        self._get_or_create_user(user_id)

        if not receta_id or receta_id not in self.game_data["recipes"]:
            embed = discord.Embed(title="🔨 Mesa de Forja", description="Usa `/forjar [id_receta]` para construir algo.", color=discord.Color.orange())
            for r_id, r_data in self.game_data["recipes"].items():
                if r_data["type"] == "pickaxe":
                    res_data = self.game_data["pickaxes"][r_data["result"]]
                    v_text = "*(Pico Equipable)*"
                else:
                    res_data = self.game_data["valuables"][r_data["result"]]
                    v_text = f"Valor: **{res_data['value']}** Choskris"

                ing_text = ", ".join([f"{v}x {self.game_data['materials'][k]['name']}" for k, v in r_data["ingredients"].items()])
                embed.add_field(name=f"`{r_id}` | {res_data['emoji']} {res_data['name']}", value=f"Requisitos: {ing_text}\n{v_text}", inline=False)

            await interaction.response.send_message(embed=embed)
            return

        recipe = self.game_data["recipes"][receta_id]

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT material_id, amount FROM mining_inv_materials WHERE user_id = ?", (user_id,))
            inventory = dict(cursor.fetchall())

            for mat_id, req_amount in recipe["ingredients"].items():
                if inventory.get(mat_id, 0) < req_amount:
                    await interaction.response.send_message(f"Te faltan materiales. Necesitas **{req_amount}x {self.game_data['materials'][mat_id]['name']}**.", ephemeral=True)
                    return

            for mat_id, req_amount in recipe["ingredients"].items():
                cursor.execute("UPDATE mining_inv_materials SET amount = amount - ? WHERE user_id = ? AND material_id = ?",
                               (req_amount, user_id, mat_id))

            cursor.execute("DELETE FROM mining_inv_materials WHERE amount <= 0 AND user_id = ?", (user_id,))

            if recipe["type"] == "pickaxe":
                max_dur = self.game_data["pickaxes"][recipe["result"]]["max_durability"]
                cursor.execute("INSERT INTO mining_inv_pickaxes (user_id, pickaxe_id, durability) VALUES (?, ?, ?)",(user_id, recipe["result"], max_dur))
                result_name = self.game_data["pickaxes"][recipe["result"]]["name"]
            else:
                cursor.execute("""
                               INSERT INTO mining_inv_valuables (user_id, valuable_id, amount)
                               VALUES (?, ?, 1)
                               ON CONFLICT(user_id, valuable_id) DO UPDATE SET amount = amount + 1
                               """, (user_id, recipe["result"]))
                result_name = self.game_data["valuables"][recipe["result"]]["name"]

            conn.commit()

        self.bot.global_stats.register_item_crafted(interaction.user.id)
        await interaction.response.send_message(f"🔨 ¡Has forjado con éxito: **{result_name}**!")

    @mining_group.command(name="vender", description="Vende automáticamente todos tus objetos valiosos por choskris.")
    async def sell(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT valuable_id, amount FROM mining_inv_valuables WHERE user_id = ?", (user_id,))
            items = cursor.fetchall()

            if not items:
                await interaction.response.send_message("No tienes objetos valiosos para vender.", ephemeral=True)
                return

            total_choskris = 0
            total_items = 0
            for v_id, amount in items:
                total_items += amount
                total_choskris += self.game_data["valuables"][v_id]["value"] * amount

            cursor.execute("DELETE FROM mining_inv_valuables WHERE user_id = ?", (user_id,))
            cursor.execute("UPDATE economy_users SET balance = balance + ? WHERE user_id = ?", (total_choskris, user_id))
            conn.commit()

        self.bot.global_stats.register_item_sale(interaction.user.id, total_items, total_choskris)
        await interaction.response.send_message(f"💰 Has vendido tus objetos valiosos por un total de **{total_choskris}** Choskris.")

    @mining_group.command(name="inventario", description="Revisa tus Choskris, Energía, Materiales y Valiosos.")
    async def inventory(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        self._get_or_create_user(user_id)

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT energy, current_depth_id FROM mining_users WHERE user_id = ?", (user_id,))
            energy, depth = cursor.fetchone()

            cursor.execute("SELECT material_id, amount FROM mining_inv_materials WHERE user_id = ?", (user_id,))
            materials = cursor.fetchall()

            cursor.execute("SELECT valuable_id, amount FROM mining_inv_valuables WHERE user_id = ?", (user_id,))
            valuables = cursor.fetchall()

            cursor.execute("SELECT pickaxe_id, durability FROM mining_inv_pickaxes WHERE user_id = ? AND is_equipped = 1",
                           (user_id,))
            equipped_pick = cursor.fetchone()

        embed = discord.Embed(title=f"🎒 Inventario de {interaction.user.display_name}", color=discord.Color.green())

        # Stats
        depth_name = self.game_data["levels"][depth]["name"]
        pick_str = "Ninguno"
        if equipped_pick:
            p_data = self.game_data["pickaxes"][equipped_pick[0]]
            pick_str = f"{p_data['emoji']} {p_data['name']} (Dur: {equipped_pick[1]}/{p_data['max_durability']})"

        embed.add_field(name="Estadísticas",
                        value=f"⚡ **Energía:** {energy}/100\n🛗 **Capa:** {depth_name}\n⛏️ **Pico:** {pick_str}",
                        inline=False)

        # Materiales
        mat_str = "\n".join(
            [f"{self.game_data['materials'][m[0]]['emoji']} {m[1]}x {self.game_data['materials'][m[0]]['name']}" for m
             in materials])
        embed.add_field(name="Materias Primas", value=mat_str if mat_str else "*Vacío*", inline=True)

        # Valiosos
        val_total = 0
        val_str_list = []
        for v in valuables:
            v_data = self.game_data["valuables"][v[0]]
            subtotal = v[1] * v_data["value"]
            val_total += subtotal
            val_str_list.append(f"{v_data['emoji']} {v[1]}x {v_data['name']}")

        val_str = "\n".join(val_str_list)
        if val_str:
            val_str += f"\n\n*(Valor de venta total: **{val_total}** Choskris)*"
        embed.add_field(name="Objetos Valiosos", value=val_str if val_str else "*Vacío*", inline=True)

        await interaction.response.send_message(embed=embed)

    @tasks.loop(time=datetime.time(hour=0, minute=0, second=0))
    async def daily_reset_task(self):
        with sqlite3.connect("bot_data.db") as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("UPDATE mining_users SET energy = 100, refills = 0")

            conn.commit()

    @daily_reset_task.before_loop
    async def before_daily_interest(self):
        await self.bot.wait_until_ready()


async def setup(bot: JoseLuisBot):
    await bot.add_cog(MiningSystemCog(bot))