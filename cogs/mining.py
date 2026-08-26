import asyncio
import datetime

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import random
from typing import Optional

from database import DBManager
from main import JoseLuisBot

JSON_PATH = "mining.json"


class AscensorView(discord.ui.View):
    def __init__(self, user_id: int, levels: dict, db: DBManager):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.db = db

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
        await self.db.mining_change_depth(interaction.user.id, selected_level)
        await interaction.response.send_message(content=f"🛗 El ascensor te ha llevado a: **{selected_level}**")


class DrinkConfirmView(discord.ui.View):
    def __init__(self, bot, user_id: int, gain: int, total_cost: int, refill_alert: str):
        super().__init__(timeout=60.0)  # El botón caduca a los 60 segundos
        self.bot = bot
        self.user_id = user_id
        self.gain = gain
        self.total_cost = total_cost
        self.refill_alert = refill_alert

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("No puedes usar este botón.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Comprar y Beber", style=discord.ButtonStyle.success, emoji="🥤")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        energy, _, _, choskris = await self.bot.db.mining_get_refill_data(self.user_id)

        if energy >= 100:
            await interaction.response.send_message("Tu energía ya está al máximo.", ephemeral=True)
            self.stop()
            return

        if choskris < self.total_cost:
            await interaction.response.send_message(f"Ya no tienes suficientes Choskris (Necesitas {self.total_cost}).", ephemeral=True)
            self.stop()
            return

        new_energy = min(100, energy + self.gain)
        new_choskris = choskris - self.total_cost
        await self.bot.db.mining_apply_refill(self.user_id, new_energy, new_choskris)
        await self.bot.global_stats.register_drink_action(self.user_id, self.total_cost)

        for item in self.children:
            item.disabled = True

        msg = (
            f"🥤 ¡Has comprado una bebida por **{self.total_cost} Choskris**{self.refill_alert}!\n"
            f"⚡ **Energía restaurada:** {new_energy}/100 (+{self.gain})"
        )

        current_balance = await self.bot.db.economy_get_balance(self.user_id)
        msg += f"\n💰 Saldo actual: **{current_balance}**"
        await interaction.response.edit_message(
            content=msg,
            view=None
        )
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(content="Compra cancelada.", view=None)
        self.stop()


class EquipPickaxeView(discord.ui.View):
    def __init__(self, bot, user_id: int, pickaxes: list, pickaxes_game_data: dict):
        super().__init__(timeout=60.0)
        self.bot = bot
        self.user_id = user_id
        self.pickaxes = pickaxes
        self.pickaxes_game_data = pickaxes_game_data

        options = []
        for p in self.pickaxes:
            db_id = p[0]
            pick_key = p[1]
            current_dur = p[2]
            is_equipped = p[3] == 1

            p_data = self.pickaxes_game_data[pick_key]

            status_label = " [Equipado]" if is_equipped else ""
            label = f"{p_data['name']}{status_label}"
            desc = f"Durabilidad: {current_dur}/{p_data['max_durability']}"

            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(db_id),
                    description=desc[:100],
                    emoji=p_data.get("emoji"),
                    default=is_equipped,
                )
            )

        self.pick_select = discord.ui.Select(
            placeholder="Selecciona el pico a equipar...",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.pick_select.callback = self.select_callback
        self.add_item(self.pick_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("No puedes usar el menú de otra persona.", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        target_db_id = int(self.pick_select.values[0])

        selected_pick = next((p for p in self.pickaxes if p[0] == target_db_id), None)
        if not selected_pick:
            await interaction.followup.edit_message(
                message_id=interaction.message.id,
                content="Error: No se encontró el pico seleccionado.",
                embed=None,
                view=None,
            )
            self.stop()
            return

        if selected_pick[3] == 1:
            pick_data = self.pickaxes_game_data[selected_pick[1]]
            await interaction.followup.edit_message(
                message_id=interaction.message.id,
                content=f"ℹ️ Ya tienes equipado el pico **{pick_data['name']}** {pick_data['emoji']}.",
                embed=None,
                view=None,
            )
            self.stop()
            return

        await self.bot.db.mining_equip_pickaxe(self.user_id, target_db_id)
        pick_data = self.pickaxes_game_data[selected_pick[1]]

        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            content=f"✅ Has equipado: **{pick_data['name']}** {pick_data['emoji']}",
            embed=None,
            view=None,
        )
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Equipamiento cancelado.", embed=None, view=None)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception:
            pass


class CraftQuantityModal(discord.ui.Modal):
    def __init__(self, bot, user_id: int, receta_id: str, recipe: dict, game_data: dict):
        super().__init__(title="🔨 Cantidad a Forjar")
        self.bot = bot
        self.user_id = user_id
        self.receta_id = receta_id
        self.recipe = recipe
        self.game_data = game_data

        is_pickaxe = recipe["type"] == "pickaxe"
        res_data = (
            game_data["pickaxes"][recipe["result"]]
            if is_pickaxe
            else game_data["valuables"][recipe["result"]]
        )

        self.amount_input = discord.ui.TextInput(
            label=f"¿Cuántos '{res_data['name']}' deseas forjar?",
            placeholder="Introduce un número (mínimo 1)...",
            default="1",
            min_length=1,
            max_length=4,
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

        try:
            amount = int(self.amount_input.value.strip())
            if amount < 1:
                raise ValueError
        except ValueError:
            await interaction.followup.send("Debes introducir un número entero mayor o igual a 1.", ephemeral=True)
            return

        inventory = await self.bot.db.mining_get_user_inventory(self.user_id)

        missing_mats = []
        for mat_id, req_amount in self.recipe["ingredients"].items():
            total_req = req_amount * amount
            user_has = inventory.get(mat_id, 0)
            if user_has < total_req:
                mat_name = self.game_data["materials"][mat_id]["name"]
                missing_mats.append(
                    f"**{total_req - user_has}x {mat_name}** (Tienes:"
                    f" {user_has}/{total_req})"
                )

        if missing_mats:
            mats_str = ", ".join(missing_mats)
            await interaction.followup.edit_message(
                message_id=interaction.message.id,
                content=f"No tienes suficientes materiales para forjar **{amount}x**. Te falta: {mats_str}.",
                embed=None,
                view=None,
            )
            return

        is_pickaxe = self.recipe["type"] == "pickaxe"
        result_id = self.recipe["result"]

        if is_pickaxe:
            item_info = self.game_data["pickaxes"][result_id]
            max_dur = item_info["max_durability"]
            result_name = item_info["name"]
        else:
            item_info = self.game_data["valuables"][result_id]
            max_dur = None
            result_name = item_info["name"]

        await self.bot.db.mining_craft_item(self.user_id, self.recipe["ingredients"], result_id, self.recipe["type"], amount, max_dur)
        await self.bot.global_stats.register_item_crafted(self.user_id, amount)

        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            content=f"🔨 ¡Has forjado con éxito: **{amount}x {result_name}** {item_info.get('emoji', '')}!",
            embed=None,
            view=None,
        )


class CraftSelectView(discord.ui.View):
    def __init__(self, bot, user_id: int, game_data: dict):
        super().__init__(timeout=60.0)
        self.bot = bot
        self.user_id = user_id
        self.game_data = game_data

        options = []
        for r_id, r_data in self.game_data["recipes"].items():
            if r_data["type"] == "pickaxe":
                res_data = self.game_data["pickaxes"][r_data["result"]]
            else:
                res_data = self.game_data["valuables"][r_data["result"]]

            ing_text = ", ".join(
                [
                    f"{v}x {self.game_data['materials'][k]['name']}"
                    for k, v in r_data["ingredients"].items()
                ]
            )

            options.append(
                discord.SelectOption(
                    label=res_data["name"][:100],
                    value=r_id,
                    description=f"Requiere: {ing_text}"[:100],
                    emoji=res_data.get("emoji"),
                )
            )

        self.craft_select = discord.ui.Select(
            placeholder="Selecciona el objeto a forjar...",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.craft_select.callback = self.select_callback
        self.add_item(self.craft_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("No puedes interactuar con el menú de otra persona.",ephemeral=True,)
            return False
        return True

    async def select_callback(self, interaction: discord.Interaction):
        receta_id = self.craft_select.values[0]
        recipe = self.game_data["recipes"][receta_id]

        modal = CraftQuantityModal(
            bot=self.bot,
            user_id=self.user_id,
            receta_id=receta_id,
            recipe=recipe,
            game_data=self.game_data,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Forja cancelada.", embed=None, view=None)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception:
            pass


class MiningSystemCog(commands.Cog):
    def __init__(self, bot: JoseLuisBot):
        self.bot = bot
        self.active_miners = set()
        self.daily_reset_task.start()

        with open(JSON_PATH, "r", encoding="utf-8") as f:
            self.game_data = json.load(f)

    mining_group = app_commands.Group(
        name="mineria",
        description="Comandos para minar y forjar objetos"
    )

    def cog_unload(self):
        self.daily_reset_task.cancel()

    @mining_group.command(name="minar", description="Usa tu pico y energía para obtener materiales.")
    async def mine(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if user_id in self.active_miners:
            await interaction.response.send_message("**¡Ya estás minando!** Espera a que termine tu acción actual antes de volver a picar.", ephemeral=True)
            return

        self.active_miners.add(user_id)

        try:
            energy, depth_id, current_xp, user_lvl, equipped_pick = await self.bot.db.mining_get_user_status(user_id)

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
                await self.bot.db.mining_deduct_energy(user_id, energy_cost)
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
            lvl_up_msg = ""

            pick_was_broken = False
            new_xp = current_xp + 10
            required_xp = int(100 * (user_lvl ** 1.5))
            leveled_up = new_xp >= required_xp

            new_level = user_lvl + 1 if leveled_up else user_lvl
            final_xp = new_xp - required_xp if leveled_up else new_xp

            await self.bot.db.mining_record_mine_action(user_id, energy_cost, db_pick_id, new_durability, dropped_material, total_yield, final_xp, new_level)

            if new_durability <= 0:
                durability_msg = f"💥 **¡Tu {pickaxe_data['name']} se ha roto!**"
            if leveled_up:
                lvl_up_msg = f"\n⬆️ **¡Has subido al Nivel Minero {new_level}!**"

            await self.bot.global_stats.register_mine_action(interaction.user.id, energy_cost, total_yield)
            if pick_was_broken:
                await self.bot.global_stats.register_pickaxe_broken(interaction.user.id)

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
        app_commands.Choice(name="Lata Normal (+50 Energía)", value="single"),
        app_commands.Choice(name="Relleno Total (100% Energía)", value="full")
    ])
    async def drink(self, interaction: discord.Interaction, modo: Optional[str] = "full"):
        user_id = interaction.user.id

        energy, user_lvl, refills, choskris = await self.bot.db.mining_get_refill_data(user_id)

        if energy >= 100:
            await interaction.response.send_message("Tu energía ya está al máximo (100/100).", ephemeral=True)
            return

        cost_per_energy = 2
        final_cost = cost_per_energy * (1.25 ** refills)
        cost_perc = int(((final_cost / cost_per_energy) - 1) * 100)

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

        next_refill_reset = self.daily_reset_task.next_iteration
        reset_time = discord.utils.format_dt(next_refill_reset, "R") if next_refill_reset else "en un millón de años"
        refill_alert = "" if cost_perc == 0 else f" (+{cost_perc}% por {refills + 1} bebidas hoy. Se reinicia {reset_time})"

        view = DrinkConfirmView(self.bot, user_id, gain, total_cost, refill_alert)

        await interaction.response.send_message(
            f"🥤 **Confirmación de Compra**\n"
            f"- **Restauración:** +{gain}⚡ (Energía actual: {energy}/100)\n"
            f"- **Coste Total:** **{total_cost} Choskris**{refill_alert}\n"
            f"- **Tu Saldo:** {choskris} Choskris\n\n"
            f"¿Deseas confirmar la bebida?",
            view=view
        )

    @mining_group.command(name="ascensor", description="Cambia el nivel de profundidad en el que minas.")
    async def elevator(self, interaction: discord.Interaction):
        await self.bot.db.mining_ensure_user(interaction.user.id)
        view = AscensorView(interaction.user.id, self.game_data["levels"], self.bot.db)
        await interaction.response.send_message("🛗 Selecciona tu destino:", view=view)

    @mining_group.command(name="obtenerpico", description="Reclama un pico de piedra básico gratuito.")
    async def get_pickaxe(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        pick_id = "pico_piedra"
        max_dur = self.game_data["pickaxes"][pick_id]["max_durability"]

        now = datetime.datetime.now()
        last_pick = await self.bot.db.mining_get_last_basic_pick(user_id)

        if last_pick:
            next_time = last_pick + datetime.timedelta(days=1)
            if next_time > now:

                time_dialog = discord.utils.format_dt(next_time, "R")
                await interaction.response.send_message(f"El herrero está descansando. Vuelve {time_dialog}", ephemeral=True)
                return

        await self.bot.db.mining_claim_basic_pickaxe(user_id, pick_id, max_dur)

        await self.bot.global_stats.register_basic_pickaxe_claim(interaction.user.id)
        await interaction.response.send_message("🪨 Has recibido tu **Pico de Piedra** gratuito.")

    @mining_group.command(name="equipar", description="Muestra tus picos y te permite equipar uno.")
    async def equip(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_id = interaction.user.id

        pickaxes = await self.bot.db.mining_get_user_pickaxes(user_id)

        if not pickaxes:
            await interaction.followup.send("⛏️ No tienes picos en tu inventario. Usa `/obtenerpico` o `/forjar`.", ephemeral=True,)
            return

        embed = discord.Embed(
            title="⛏️ Tu Inventario de Picos",
            description="Selecciona en el menú desplegable el pico que deseas equipar.",
            color=0x2ECC71,
        )

        for i, p in enumerate(pickaxes, 1):
            p_data = self.game_data["pickaxes"][p[1]]
            status = "✅ **[Equipado]**" if p[3] == 1 else ""
            embed.add_field(
                name=f"{p_data['emoji']} {p_data['name']} {status}",
                value=f"Durabilidad: `{p[2]}/{p_data['max_durability']}`",
                inline=False,
            )

        view = EquipPickaxeView(self.bot, user_id, pickaxes, self.game_data["pickaxes"])

        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg

    @mining_group.command(name="forjar", description="Muestra la mesa de forja y te permite construir objetos.")
    async def craft(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_id = interaction.user.id

        embed = discord.Embed(
            title="🔨 Mesa de Forja",
            description="Selecciona la receta que deseas construir en el menú desplegable.",
            color=discord.Color.orange(),
        )

        for r_id, r_data in self.game_data["recipes"].items():
            if r_data["type"] == "pickaxe":
                res_data = self.game_data["pickaxes"][r_data["result"]]
                v_text = "*(Pico Equipable)*"
            else:
                res_data = self.game_data["valuables"][r_data["result"]]
                v_text = f"Valor: **{res_data['value']}** Choskris"

            ing_text = ", ".join(
                [
                    f"{v}x {self.game_data['materials'][k]['name']}"
                    for k, v in r_data["ingredients"].items()
                ]
            )
            embed.add_field(
                name=f"{res_data['emoji']} {res_data['name']}",
                value=f"Requisitos: {ing_text}\n{v_text}",
                inline=False,
            )

        view = CraftSelectView(
            bot=self.bot,
            user_id=user_id,
            game_data=self.game_data,
        )

        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg

    @mining_group.command(name="vender", description="Vende automáticamente todos tus objetos valiosos por choskris.")
    async def sell(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        items = await self.bot.db.mining_get_user_valuables(user_id)

        if not items:
            await interaction.response.send_message("No tienes objetos valiosos para vender.", ephemeral=True)
            return

        total_choskris = sum(self.game_data["valuables"][v_id]["value"] * amount for v_id, amount in items)
        total_items = sum(amount for _, amount in items)

        await self.bot.db.mining_sell_all_valuables(user_id, total_choskris)

        await self.bot.global_stats.register_item_sale(interaction.user.id, total_items, total_choskris)
        msg = f"🪙 Has vendido tus objetos valiosos por un total de **{total_choskris}** Choskris."
        current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
        msg += f"\n💰 Saldo actual: **{current_balance}**"
        await interaction.response.send_message(msg)

    @mining_group.command(name="inventario", description="Revisa tus Choskris, Energía, Materiales y Valiosos.")
    async def inventory(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        user = user if user else interaction.user
        user_id = user.id

        profile = await self.bot.db.mining_get_full_profile(user_id)

        xp, level, energy, depth = profile["user"]

        xp_needed = int(100 * (level ** 1.5))
        progress_pct = min(1.0, xp / xp_needed)
        filled_blocks = int(progress_pct * 8)
        bar = "█" * filled_blocks + "░" * (8 - filled_blocks)

        materials = profile["materials"]
        valuables = profile["valuables"]
        equipped_pick = profile["equipped_pick"]

        embed = discord.Embed(title=f"🎒 Inventario de {user.display_name}", color=discord.Color.green())

        depth_name = self.game_data["levels"][depth]["name"]
        pick_str = "Ninguno"
        if equipped_pick:
            p_data = self.game_data["pickaxes"][equipped_pick[0]]
            pick_str = f"{p_data['emoji']} {p_data['name']} (Dur: {equipped_pick[1]}/{p_data['max_durability']})"

        embed.add_field(name=f"👷🏻‍♂️ Nivel {level}", value=f"`[{bar}]` {xp}/{xp_needed} XP", inline=False)
        embed.add_field(name="Estadísticas", value=f"⚡ **Energía:** {energy}/100\n🛗 **Capa:** {depth_name}\n⛏️ **Pico:** {pick_str}", inline=False)

        mat_str = "\n".join([f"{self.game_data['materials'][m]['emoji']} {val}x {self.game_data['materials'][m]['name']}" for m, val in materials.items()])
        embed.add_field(name="Materias Primas", value=mat_str if mat_str else "*Vacío*", inline=True)

        val_total = 0
        val_str_list = []
        for v, val in valuables.items():
            v_data = self.game_data["valuables"][v]
            subtotal = val * v_data["value"]
            val_total += subtotal
            val_str_list.append(f"{v_data['emoji']} {val}x {v_data['name']}")

        val_str = "\n".join(val_str_list)
        if val_str:
            val_str += f"\n\n*(Valor de venta total: **{val_total}** Choskris)*"
        embed.add_field(name="Objetos Valiosos", value=val_str if val_str else "*Vacío*", inline=True)

        await interaction.response.send_message(embed=embed)

    @tasks.loop(time=datetime.time(hour=0, minute=0, second=0))
    async def daily_reset_task(self):
        await self.bot.db.mining_reset_all_energy()

    @daily_reset_task.before_loop
    async def before_daily_interest(self):
        await self.bot.wait_until_ready()


async def setup(bot: JoseLuisBot):
    await bot.add_cog(MiningSystemCog(bot))