import datetime
import json
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from dungeon_engine import BattleState, DungeonEngine, fmt_int, progress_bar
from main import JoseLuisBot

RARITY_VALUE = {"comun": 1, "raro": 2, "epico": 4, "legendario": 8, "mitico": 16}
DEFAULT_ACCENT = discord.Color.from_str("#2C3E50")


def item_value(item: dict) -> int:
    base = 5 * (1.15 ** int(item.get("floor_found", 1))) * RARITY_VALUE.get(item.get("rarity", "comun"), 1)
    return int(base * (1 + 0.25 * len(item.get("sockets", []))))


def parse_dt(value) -> Optional[datetime.datetime]:
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        parsed = value
    else:
        try:
            parsed = datetime.datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        return []
    return loaded if isinstance(loaded, list) else []


def _json_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


TRIGGER_LABELS = {
    "ON_ATTACK": "Al atacar",
    "ON_CRIT": "Al asestar un crítico",
    "ON_DEFEND": "Al defender",
    "ON_HIT_TAKEN": "Al recibir un golpe",
    "ON_STATUS_APPLIED": "Al aplicar un estado",
    "ON_TURN_START": "Al inicio del turno",
    "ON_TURN_END": "Al final del turno",
    "ON_KILL": "Al matar",
    "ON_BATTLE_START": "Al empezar el combate",
    "ON_BATTLE_END": "Al acabar el combate",
    "ON_LOW_HP": "Con la vida baja",
    "ON_SHIELD_BREAK": "Al romperse tu escudo",
    "ON_HEAL": "Al curarte",
    "ON_ENERGY_GAIN": "Al ganar energía",
    "ON_POTION_USE": "Al usar una poción",
    "ON_SKILL_USE": "Al usar una habilidad",
    "ON_STATUS_TICK": "Al tickear un estado",
    "ON_DODGE": "Al esquivar",
    "ON_BOSS_PHASE": "Al cambiar de fase un jefe",
    "ON_FLOOR_CLEAR": "Al limpiar el piso",
}
DAMAGE_TYPE_LABELS = {"fisico": "físico", "fuego": "fuego", "hielo": "hielo", "rayo": "rayo", "veneno": "veneno", "arcano": "arcano"}


def _pct(value) -> str:
    return f"{int(round(float(value) * 100))}%"


async def ensure_dungeon_access(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        await interaction.response.send_message(
            embed=discord.Embed(description="❌ La mazmorra solo funciona dentro de un servidor.", color=discord.Color.red()),
            ephemeral=True,
        )
        return False

    bot: JoseLuisBot = interaction.client
    if await bot.is_bot_operator(interaction.guild.id, interaction.user):
        return True

    role_id = int(await bot.db.guild.get(interaction.guild.id, "dungeon_role_id") or 0)
    roles = getattr(interaction.user, "roles", [])
    if not role_id or (role_id and any(role.id == role_id for role in roles)):
        return True
    detail = f"Necesitas el rol <@&{role_id}> para entrar en la mazmorra."
    await interaction.response.send_message(
        embed=discord.Embed(title="🔒 Acceso restringido", description=detail, color=discord.Color.dark_red()),
        ephemeral=True,
    )
    return False


class DungeonGroup(app_commands.Group):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await ensure_dungeon_access(interaction)


class CombatView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, potions: int, no_potions: bool = False, skill_name: str = "Habilidad", ended: bool = False):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.message: Optional[discord.Message] = None

        self._add("Atacar", "⚔️", discord.ButtonStyle.danger, "attack", ended, row=0)
        self._add("Defender", "🛡️", discord.ButtonStyle.primary, "defend", ended, row=0)
        self._add(skill_name[:60], "✨", discord.ButtonStyle.success, "skill", ended, row=0)
        self._add(f"Poción ({potions})", "🧪", discord.ButtonStyle.secondary, "potion", ended or no_potions or potions <= 0, row=0)
        self._add("Huir", "🏃", discord.ButtonStyle.secondary, "flee", ended, row=1)

    def _add(self, label: str, emoji: str, style: discord.ButtonStyle, action: str, disabled: bool, row: int = 0) -> None:
        button = discord.ui.Button(label=label, emoji=emoji, style=style, disabled=disabled, row=row)

        async def callback(interaction: discord.Interaction, _action: str = action) -> None:
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(
                    embed=discord.Embed(description="❌ Estos botones no son para ti.", color=discord.Color.red()),
                    ephemeral=True,
                )
                return
            await self.cog.handle_action(interaction, self, _action)

        button.callback = callback
        self.add_item(button)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class InventoryView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, items: list[dict]):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        equipped = [item for item in items if item.get("is_equipped")]
        bag = [item for item in items if not item.get("is_equipped")]

        if bag:
            equip_options = [
                discord.SelectOption(
                    label=item["name"][:100],
                    value=item["item_uid"],
                    description=f"{cog.slot_name(item['slot'])} · {item['rarity']} · {len(item['sockets'])} ranuras"[:100],
                    emoji=cog.rarity_emoji(item["rarity"]),
                )
                for item in bag[:25]
            ]
            select = discord.ui.Select(placeholder="Equipar un objeto...", options=equip_options, row=0)
            select.callback = self._equip_callback
            self.add_item(select)

            sell_options = [
                discord.SelectOption(
                    label=f"{item['name']} (+{fmt_int(item_value(item))} oro)"[:100],
                    value=item["item_uid"],
                    description=f"Vender · {cog.slot_name(item['slot'])} · {item['rarity']}"[:100],
                    emoji="🪙",
                )
                for item in bag[:25]
            ]
            select = discord.ui.Select(placeholder="Vender un objeto de la mochila...", options=sell_options, row=1)
            select.callback = self._sell_callback
            self.add_item(select)

        if equipped:
            unequip_options = [
                discord.SelectOption(
                    label=item["name"][:100],
                    value=item["item_uid"],
                    description=f"Desequipar · {cog.slot_name(item['slot'])} · {item['rarity']}"[:100],
                    emoji="↩️",
                )
                for item in equipped[:25]
            ]
            select = discord.ui.Select(placeholder="Desequipar un objeto...", options=unequip_options, row=2)
            select.callback = self._unequip_callback
            self.add_item(select)

        close = discord.ui.Button(label="Cerrar", style=discord.ButtonStyle.secondary, row=3)
        close.callback = self._close
        self.add_item(close)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ No puedes usar el inventario de otra persona.", color=discord.Color.red()),
                ephemeral=True,
            )
            return False
        return True

    async def _equip_callback(self, interaction: discord.Interaction) -> None:
        item_uid = interaction.data["values"][0]
        ok = await self.cog.repo.equip_item(self.user_id, item_uid)
        if not ok:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Ese objeto ya no existe.", color=discord.Color.red()), ephemeral=True)
            return
        await self.cog.refresh_vitals(self.user_id)
        await interaction.response.defer()
        await self.cog.send_inventory(interaction, edit=True)

    async def _sell_callback(self, interaction: discord.Interaction) -> None:
        item_uid = interaction.data["values"][0]
        item = await self.cog.repo.get_item(self.user_id, item_uid)
        if not item:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Ese objeto ya no existe.", color=discord.Color.red()), ephemeral=True)
            return
        if item.get("is_equipped"):
            await interaction.response.send_message(embed=discord.Embed(description="⚠️ Desequípalo primero para poder venderlo.", color=discord.Color.orange()), ephemeral=True)
            return
        value = item_value(item)
        await self.cog.repo.delete_item(self.user_id, item_uid)
        await self.cog.repo.add_gold(self.user_id, value)
        await interaction.response.defer()
        await self.cog.send_inventory(interaction, edit=True, note=f"🪙 Has vendido **{item['name']}** por **{fmt_int(value)}** de oro interno.")

    async def _unequip_callback(self, interaction: discord.Interaction) -> None:
        item_uid = interaction.data["values"][0]
        item = await self.cog.repo.get_item(self.user_id, item_uid)
        if not item:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Ese objeto ya no existe.", color=discord.Color.red()), ephemeral=True)
            return
        await self.cog.repo.unequip_item(self.user_id, item_uid)
        await self.cog.refresh_vitals(self.user_id)
        await interaction.response.defer()
        await self.cog.send_inventory(interaction, edit=True, note=f"↩️ Has desequipado **{item['name']}**: ya puedes venderlo desde la mochila.")

    async def _close(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=None)


class QuantityModal(discord.ui.Modal):
    def __init__(self, cog: "DungeonCog", user_id: int, key: str):
        super().__init__(title="Cantidad a comprar")
        self.cog = cog
        self.user_id = user_id
        self.key = key
        self.quantity = discord.ui.TextInput(label="Cantidad", default="1", min_length=1, max_length=3)
        self.add_item(self.quantity)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            amount = max(1, min(99, int(str(self.quantity.value).strip())))
        except ValueError:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Introduce un número válido.", color=discord.Color.red()), ephemeral=True)
            return
        await self.cog.market_buy(interaction, self.key, amount)


class MarketView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, options: list[discord.SelectOption]):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        select = discord.ui.Select(placeholder="¿Qué quieres comprar?", options=options)
        select.callback = self._selected
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Este menú no es para ti.", color=discord.Color.red()), ephemeral=True)
            return False
        return True

    async def _selected(self, interaction: discord.Interaction) -> None:
        key = interaction.data["values"][0]
        await interaction.response.send_modal(QuantityModal(self.cog, self.user_id, key))


class ShopView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, options: list[discord.SelectOption]):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.selected: Optional[str] = None
        select = discord.ui.Select(placeholder="Selecciona una reliquia...", options=options)
        select.callback = self._selected
        self.add_item(select)
        buy = discord.ui.Button(label="Comprar", emoji="🪙", style=discord.ButtonStyle.success)
        buy.callback = self._buy
        self.add_item(buy)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Este menú no es para ti.", color=discord.Color.red()), ephemeral=True)
            return False
        return True

    async def _selected(self, interaction: discord.Interaction) -> None:
        self.selected = interaction.data["values"][0]
        await interaction.response.defer()

    async def _buy(self, interaction: discord.Interaction) -> None:
        if not self.selected:
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ Selecciona primero una reliquia.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return
        await self.cog.shop_buy(interaction, self.selected)


class MutationView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, options: list[discord.SelectOption]):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.selected: Optional[str] = None
        select = discord.ui.Select(placeholder="Selecciona una mutación...", options=options)
        select.callback = self._selected
        self.add_item(select)
        buy = discord.ui.Button(label="Mejorar", emoji="✨", style=discord.ButtonStyle.success)
        buy.callback = self._buy
        self.add_item(buy)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Este menú no es para ti.", color=discord.Color.red()), ephemeral=True)
            return False
        return True

    async def _selected(self, interaction: discord.Interaction) -> None:
        self.selected = interaction.data["values"][0]
        await interaction.response.defer()

    async def _buy(self, interaction: discord.Interaction) -> None:
        if not self.selected:
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ Selecciona primero una mutación.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return
        await self.cog.mutation_buy(interaction, self.selected)


class SkillView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, options: list[discord.SelectOption]):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        select = discord.ui.Select(placeholder="Elige tu habilidad activa...", options=options)
        select.callback = self._selected
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Este menú no es para ti.", color=discord.Color.red()), ephemeral=True)
            return False
        return True

    async def _selected(self, interaction: discord.Interaction) -> None:
        skill_id = interaction.data["values"][0]
        skill = self.cog.engine.get_skill(skill_id)
        await self.cog.repo.update_user(self.user_id, active_skill=skill_id)
        await interaction.response.edit_message(
            embed=discord.Embed(
                description=f"{skill['emoji']} Habilidad activa: **{skill['name']}** ({skill['cost']}⚡)",
                color=discord.Color.blurple(),
            ),
            view=None,
        )


class AnomalyView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, options: list[discord.SelectOption]):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        select = discord.ui.Select(placeholder="Elige una anomalía...", options=options)
        select.callback = self._selected
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Este menú no es para ti.", color=discord.Color.red()), ephemeral=True)
            return False
        return True

    async def _selected(self, interaction: discord.Interaction) -> None:
        anomaly_id = interaction.data["values"][0]
        await self.cog.start_anomaly(interaction, anomaly_id)


class ShiftsView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, options: list[discord.SelectOption], max_values: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        select = discord.ui.Select(placeholder="Activa o desactiva afijos...", options=options, min_values=0, max_values=max(1, max_values))
        select.callback = self._selected
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Este menú no es para ti.", color=discord.Color.red()), ephemeral=True)
            return False
        return True

    async def _selected(self, interaction: discord.Interaction) -> None:
        values = interaction.data["values"]
        await self.cog.repo.update_user(self.user_id, shifts=json.dumps(values))
        await interaction.response.edit_message(embed=await self.cog.render_shifts(self.user_id), view=self)


class AutomationView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, enabled: bool):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        button = discord.ui.Button(
            label="Desactivar" if enabled else "Activar",
            emoji="⏹️" if enabled else "▶️",
            style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
        )
        button.callback = self._toggle
        self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Este menú no es para ti.", color=discord.Color.red()), ephemeral=True)
            return False
        return True

    async def _toggle(self, interaction: discord.Interaction) -> None:
        await self.cog.toggle_automation(interaction)


class ForgeView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, items: list[dict], item_uid: Optional[str], socket_index: int):
        super().__init__(timeout=240)
        self.cog = cog
        self.user_id = user_id
        self.item_uid = item_uid
        self.socket_index = socket_index

        options = [
            discord.SelectOption(
                label=f"{item['name']} ({cog.slot_name(item['slot'])})"[:100],
                value=item["item_uid"],
                description=f"{item['rarity']} · {len(item['sockets'])} ranuras · piso {item['floor_found']}"[:100],
                emoji=cog.rarity_emoji(item["rarity"]),
                default=item["item_uid"] == item_uid,
            )
            for item in items[:25]
        ]
        item_select = discord.ui.Select(placeholder="Elige un objeto para forjar...", options=options, row=0)
        item_select.callback = self._pick_item
        self.add_item(item_select)

        selected = next((item for item in items if item["item_uid"] == item_uid), None)
        if selected and selected["sockets"]:
            socket_options = [
                discord.SelectOption(
                    label=f"Ranura {index + 1}{' 🔒' if mod.get('locked') else ''}"[:100],
                    value=str(index),
                    description=cog.describe_mod(mod)[:100],
                    default=index == socket_index,
                )
                for index, mod in enumerate(selected["sockets"][:25])
            ]
            socket_select = discord.ui.Select(placeholder="Elige una ranura...", options=socket_options, row=1)
            socket_select.callback = self._pick_socket
            self.add_item(socket_select)

        has_sockets = bool(selected and selected["sockets"])
        for label, emoji, style, handler, row, enabled in (
            ("Reforjar (oro)", "🔨", discord.ButtonStyle.primary, self._reroll, 2, has_sockets),
            ("Bloquear", "🔒", discord.ButtonStyle.secondary, self._toggle_lock, 2, has_sockets),
            ("Infundir (monedas)", "🪙", discord.ButtonStyle.success, self._infuse, 2, has_sockets),
        ):
            button = discord.ui.Button(label=label, emoji=emoji, style=style, disabled=not enabled, row=row)
            button.callback = handler
            self.add_item(button)

        close = discord.ui.Button(label="Cerrar", style=discord.ButtonStyle.secondary, row=3)
        close.callback = self._close
        self.add_item(close)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Esta forja no es para ti.", color=discord.Color.red()), ephemeral=True)
            return False
        return True

    async def _pick_item(self, interaction: discord.Interaction) -> None:
        await self.cog.send_forge(interaction, edit=True, item_uid=interaction.data["values"][0], socket_index=0)

    async def _pick_socket(self, interaction: discord.Interaction) -> None:
        await self.cog.send_forge(interaction, edit=True, item_uid=self.item_uid, socket_index=int(interaction.data["values"][0]))

    async def _reroll(self, interaction: discord.Interaction) -> None:
        await self.cog.forge_reroll(interaction, self.item_uid)

    async def _toggle_lock(self, interaction: discord.Interaction) -> None:
        await self.cog.forge_toggle_lock(interaction, self.item_uid, self.socket_index)

    async def _infuse(self, interaction: discord.Interaction) -> None:
        await self.cog.forge_offer_infusion(interaction, self.item_uid, self.socket_index)

    async def _close(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=None)


class InfuseView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, item_uid: str, socket_index: int, candidates: list[dict]):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        self.item_uid = item_uid
        self.socket_index = socket_index
        self.candidates = candidates
        options = [
            discord.SelectOption(label=f"Opción {index + 1}"[:100], value=str(index),
                                 description=cog.describe_mod(mod)[:100])
            for index, mod in enumerate(candidates)
        ]
        select = discord.ui.Select(placeholder="Elige el disparador a infundir...", options=options)
        select.callback = self._pick
        self.add_item(select)
        cancel = discord.ui.Button(label="Cancelar", style=discord.ButtonStyle.secondary, row=1)
        cancel.callback = self._cancel
        self.add_item(cancel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Esta forja no es para ti.", color=discord.Color.red()), ephemeral=True)
            return False
        return True

    async def _pick(self, interaction: discord.Interaction) -> None:
        chosen = self.candidates[int(interaction.data["values"][0])]
        await self.cog.forge_apply_infusion(interaction, self.item_uid, self.socket_index, chosen)

    async def _cancel(self, interaction: discord.Interaction) -> None:
        await self.cog.send_forge(interaction, edit=True, item_uid=self.item_uid, socket_index=self.socket_index)


class EchoView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, options: list[discord.SelectOption]):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.selected: Optional[str] = None
        select = discord.ui.Select(placeholder="Selecciona un Eco...", options=options)
        select.callback = self._selected
        self.add_item(select)
        buy = discord.ui.Button(label="Despertar", emoji="✨", style=discord.ButtonStyle.success)
        buy.callback = self._buy
        self.add_item(buy)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Este menú no es para ti.", color=discord.Color.red()), ephemeral=True)
            return False
        return True

    async def _selected(self, interaction: discord.Interaction) -> None:
        self.selected = interaction.data["values"][0]
        await interaction.response.defer()

    async def _buy(self, interaction: discord.Interaction) -> None:
        if not self.selected:
            await interaction.response.send_message(embed=discord.Embed(description="⚠️ Selecciona primero un Eco.", color=discord.Color.orange()), ephemeral=True)
            return
        await self.cog.echo_buy(interaction, self.selected)


class TrainingView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, enabled: bool, has_pending: bool):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        toggle = discord.ui.Button(label="Desactivar" if enabled else "Activar", emoji="⏹️" if enabled else "▶️", style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success)
        toggle.callback = self._toggle
        self.add_item(toggle)
        claim = discord.ui.Button(label="Recoger XP", emoji="🎓", style=discord.ButtonStyle.primary, disabled=not has_pending)
        claim.callback = self._claim
        self.add_item(claim)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Este menú no es para ti.", color=discord.Color.red()), ephemeral=True)
            return False
        return True

    async def _toggle(self, interaction: discord.Interaction) -> None:
        await self.cog.toggle_training(interaction)

    async def _claim(self, interaction: discord.Interaction) -> None:
        await self.cog.claim_training(interaction)


class SettingsView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, auto: bool):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        button = discord.ui.Button(label="Desactivar avance automático" if auto else "Activar avance automático", emoji="⏸️" if auto else "▶️", style=discord.ButtonStyle.danger if auto else discord.ButtonStyle.success)
        button.callback = self._toggle
        self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Este menú no es para ti.", color=discord.Color.red()), ephemeral=True)
            return False
        return True

    async def _toggle(self, interaction: discord.Interaction) -> None:
        await self.cog.toggle_auto_advance(interaction)


class PrestigeConfirmView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, dust: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        self.dust = dust
        confirm = discord.ui.Button(label="Renacer", emoji="✨", style=discord.ButtonStyle.danger)
        confirm.callback = self._confirm
        self.add_item(confirm)
        cancel = discord.ui.Button(label="Cancelar", style=discord.ButtonStyle.secondary)
        cancel.callback = self._cancel
        self.add_item(cancel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Esta decisión no es tuya.", color=discord.Color.red()), ephemeral=True)
            return False
        return True

    async def _confirm(self, interaction: discord.Interaction) -> None:
        await self.cog.do_prestige(interaction, self.dust)

    async def _cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=discord.Embed(description="❌ Has decidido seguir luchando.", color=discord.Color.red()), view=None)


class DungeonCog(commands.Cog):
    mazmorra_group = DungeonGroup(name="mazmorra", description="Mazmorra RPG exclusiva para suscriptores")

    def __init__(self, bot: JoseLuisBot):
        self.bot = bot
        self.engine = DungeonEngine()
        self.automation_task.start()

    def cog_unload(self) -> None:
        self.automation_task.cancel()

    @property
    def repo(self):
        return self.bot.db.dungeon

    def slot_name(self, slot: str) -> str:
        return self.engine.data["gear_slots"].get(slot, {}).get("name", slot)

    def rarity_emoji(self, rarity: str) -> str:
        return self.engine.data["rarities"].get(rarity, {}).get("emoji", "⚪")

    def mutation_name(self, mutation_id: str) -> str:
        return self.engine.data["mutations"].get(mutation_id, {}).get("name", mutation_id)

    def skills_of(self, state: BattleState) -> dict:
        return self.engine.get_skill(state.skill_id) or {"name": "Habilidad", "emoji": "✨"}

    def statuses_str(self, combatant) -> str:
        if not combatant.statuses:
            return "*sin estados*"
        parts = []
        for tag, instance in combatant.statuses.items():
            spec = self.engine.data["statuses"].get(tag, {})
            label = f"{spec.get('emoji', '')} {spec.get('name', tag)}".strip()
            parts.append(f"{label} x{instance.stacks} ({instance.turns}t)")
        return ("📌 " + " · ".join(parts))[:1024]

    def describe_condition(self, cond: Optional[dict]) -> str:
        if not cond:
            return ""
        ctype = cond.get("type", "ALWAYS")
        target = cond.get("target", "self")
        who = "el enemigo" if target == "foe" else "tú"
        if ctype == "ALWAYS":
            return ""
        if ctype in ("HP_BELOW", "HP_ABOVE"):
            sign = "<" if ctype == "HP_BELOW" else ">"
            subject = "la vida del enemigo" if target == "foe" else "tu vida"
            return f"si {subject} {sign} {cond.get('pct')}%"
        if ctype in ("ENERGY_BELOW", "ENERGY_ABOVE"):
            sign = "<" if ctype == "ENERGY_BELOW" else ">"
            return f"si tu energía {sign} {cond.get('pct')}%"
        if ctype in ("SHIELD_ABOVE", "SHIELD_BELOW"):
            sign = ">" if ctype == "SHIELD_ABOVE" else "<"
            return f"si tu escudo {sign} {cond.get('pct') or cond.get('value')}%"
        if ctype == "IS_CRITICAL":
            return "si el golpe es crítico"
        if ctype == "HAS_STATUS":
            spec = self.engine.data["statuses"].get(cond.get("tag", ""), {})
            stacks = int(cond.get("stacks", 1))
            suffix = f" x{stacks}+" if stacks > 1 else ""
            return f"si {who} tiene {spec.get('name', cond.get('tag', ''))}{suffix}"
        if ctype == "RANDOM":
            return f"{_pct(cond.get('chance', 0))} de probabilidad"
        if ctype == "TURN_ABOVE":
            return f"a partir del turno {cond.get('value')}"
        if ctype == "FLOOR_ABOVE":
            return f"en pisos > {cond.get('value')}"
        return str(ctype).lower()

    def describe_effect(self, effect: dict) -> str:
        etype = effect.get("type", "")
        if etype == "DEAL_DAMAGE":
            kind = DAMAGE_TYPE_LABELS.get(effect.get("damage_type"), effect.get("damage_type", ""))
            return f"{_pct(effect.get('ratio', 0))} de daño {kind}"
        if etype == "APPLY_STATUS":
            spec = self.engine.data["statuses"].get(effect.get("tag", ""), {})
            return f"aplica {spec.get('name', effect.get('tag', ''))} x{effect.get('stacks', 1)}"
        if etype == "GAIN_SHIELD":
            return f"escudo del {_pct(effect.get('ratio', 0))} de la vida"
        if etype == "HEAL_HP":
            return f"cura {_pct(effect.get('ratio', 0))} de la vida"
        if etype == "REFUND_ENERGY":
            return f"+{effect.get('value')} energía"
        if etype == "STEAL_ENERGY":
            return f"roba {effect.get('value')} de energía"
        if etype == "LIFESTEAL":
            return f"roba vida ({_pct(effect.get('ratio', 0))} del daño)"
        if etype == "PURGE_STATUS":
            spec = self.engine.data["statuses"].get(effect.get("tag", ""), {})
            return f"purga {spec.get('name', effect.get('tag', ''))}"
        if etype == "CLEANSE":
            return f"limpia {effect.get('value')} estados"
        if etype == "GAIN_GOLD":
            return f"+{fmt_int(effect.get('value', 0))} oro"
        if etype == "GRANT_XP":
            return f"+{effect.get('value')} XP"
        if etype == "EXECUTE":
            return f"ejecuta por debajo del {_pct(effect.get('pct', 0))}"
        if etype == "EXTRA_TURN":
            return f"ataque extra ({_pct(effect.get('chance', 0))})"
        return str(etype).lower()

    def describe_mod(self, mod: dict) -> str:
        trigger = TRIGGER_LABELS.get(mod.get("on"), str(mod.get("on", "?")))
        condition = self.describe_condition(mod.get("if"))
        effect = self.describe_effect(mod.get("then", {}))
        return f"{trigger}: {condition + ' → ' if condition else ''}{effect}"

    def describe_item(self, item: dict) -> str:
        labels = {"attack": "ATQ", "defense": "DEF", "max_hp": "VID", "max_energy": "ENE", "crit": "CRIT"}
        bits = []
        for key, label in labels.items():
            value = item.get("stats", {}).get(key)
            if not value:
                continue
            bits.append(f"{label} +{_pct(value) if key == 'crit' else fmt_int(value)}")
        lines = [" · ".join(bits)] if bits else []
        for index, mod in enumerate(item.get("sockets", [])):
            lines.append(f"`{index + 1}` {self.describe_mod(mod)}{' 🔒' if mod.get('locked') else ''}")
        return "\n".join(lines) or "*Sin estadísticas ni ranuras*"

    async def accent_color(self, user_id: int) -> discord.Color:
        cosmetics = await self.repo.get_cosmetics(user_id)
        for cosmetic_id, equipped in cosmetics.items():
            if not equipped:
                continue
            spec = self.engine.data["boss_shop"].get(cosmetic_id)
            if spec and spec.get("type") == "accent":
                try:
                    return discord.Color.from_str(spec["color"])
                except ValueError:
                    continue
        return DEFAULT_ACCENT

    async def profile_of(self, user_id: int) -> tuple[dict, list[dict], dict, dict]:
        return (await self.repo.get_user(user_id), await self.repo.get_inventory(user_id), await self.repo.get_mutations(user_id), await self.repo.get_echoes(user_id))

    async def floor_progress(self, user_id: int) -> tuple[int, int]:
        user = await self.repo.get_user(user_id)
        return int(user["floor_kills"]), max(1, int(self.engine.cfg["enemies_per_floor"]))

    async def grant_item(self, user_id: int, item: dict) -> str:
        cap = max(1, int(self.engine.cfg.get("inventory_cap", 15)))
        count = len(await self.repo.get_inventory(user_id))
        if count >= cap:
            return f"⚠️ **{item['name']}** se ha perdido: tienes la mochila llena (**{count}/{cap}**). Vende algo para hacer sitio."
        await self.repo.add_item(user_id, item)
        return ""

    async def refresh_vitals(self, user_id: int) -> None:
        user, items, mutations, echoes = await self.profile_of(user_id)
        stats = self.engine.player_stats(user, items, mutations, echoes)
        await self.repo.update_user(
            user_id,
            max_hp=stats["max_hp"],
            hp=stats["max_hp"],
            max_energy=stats["max_energy"],
            energy=stats["max_energy"],
        )

    async def active_fight(self, user_id: int) -> Optional[BattleState]:
        raw = await self.repo.get_fight(user_id)
        if not raw:
            return None
        try:
            state = BattleState.from_dict(raw)
        except (KeyError, TypeError, ValueError) as error:
            print(f"[dungeon] Combate ilegible del usuario {user_id}, se descarta: {error}")
            await self.repo.clear_fight(user_id)
            return None
        if state.stage != "active":
            await self.repo.clear_fight(user_id)
            return None
        return state

    def render_combat(self, state: BattleState, accent: discord.Color, ended: bool = False, progress: Optional[tuple[int, int]] = None, summary_fields: Optional[list[tuple[str, str]]] = None) -> discord.Embed:
        enemy = state.enemy
        player = state.player
        if state.is_boss:
            title = f"👑 JEFE · {enemy.emoji} {enemy.name} - Piso {state.floor}"
        elif state.is_anomaly:
            title = f"🌀 ANOMALÍA · {enemy.emoji} {enemy.name} - Piso {state.floor}"
        elif state.training:
            title = f"🥋 Simulacro · {enemy.emoji} {enemy.name} - Piso {state.floor}"
        elif state.farm:
            title = f"🔁 Repetición · {enemy.emoji} {enemy.name} - Piso {state.floor}"
        else:
            title = f"{enemy.emoji} Piso {state.floor} · {enemy.name}"
        if ended:
            marker = {"victory": "🏆 ", "defeat": "💀 ", "fled": "🏃 ", "timeout": "⏳ "}.get(state.stage, "")
            title = marker + title

        embed = discord.Embed(title=title, color=accent)

        for summary_name, summary_value in summary_fields or []:
            if summary_value:
                embed.add_field(name=summary_name, value=summary_value[:1024], inline=False)

        enemy_value = f"❤️ `[{progress_bar(enemy.hp, enemy.max_hp)}]` **{fmt_int(enemy.hp)}/{fmt_int(enemy.max_hp)}**"
        if enemy.shield:
            enemy_value += f"\n🛡️ Escudo: **{fmt_int(enemy.shield)}**"
        if enemy.is_boss and enemy.phase_name:
            enemy_value += f"\n🌀 Postura: **{enemy.phase_name}**"
        if enemy.statuses:
            enemy_value += f"\n\n{self.statuses_str(enemy)}"
        if state.training:
            enemy_value += "\n\n♻️ *No puede morir: se recompone. Sal cuando quieras con **Huir**.*"
        embed.add_field(name="👹 Enemigo", value=enemy_value[:1024], inline=False)

        player_value = (f"❤️ `[{progress_bar(player.hp, player.max_hp)}]` **{fmt_int(player.hp)}/{fmt_int(player.max_hp)}**\n" f"⚡ `[{progress_bar(player.energy, player.max_energy)}]` **{fmt_int(player.energy)}/{fmt_int(player.max_energy)}**")
        if player.shield:
            player_value += f"\n🛡️ Escudo: **{fmt_int(player.shield)}**"
        if player.statuses:
            player_value += f"\n\n{self.statuses_str(player)}"
        embed.add_field(name="🧙 Tú", value=player_value[:1024], inline=False)

        if not ended:
            recent = [line[:140] for line in state.log[-7:]]
            log_text = "\n".join(recent) if recent else "*La mazmorra guarda silencio...*"
            embed.add_field(name="📜 Bitácora", value=log_text[:1024], inline=False)

        skill = self.skills_of(state)
        location = f"Simulacro piso {state.floor}" if state.training else f"Piso {state.floor}"
        footer = f"Turno {state.turn} · 🧪 {state.potions} · 🎯 {skill.get('name', '?')} · {location}"
        if progress and not ended and not (state.farm or state.is_boss or state.is_anomaly or state.training):
            footer += f" · 👹 {progress[0]}/{progress[1]}"
        if state.shifts:
            footer += f" · 🌌 {len(state.shifts)} afijo(s)"
        embed.set_footer(text=footer[:2048])
        return embed

    async def handle_action(self, interaction: discord.Interaction, view: CombatView, action: str) -> None:
        user_id = interaction.user.id
        state = await self.active_fight(user_id)
        if state is None:
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ No tienes ningún combate activo. Usa `/mazmorra explorar`.",
                                    color=discord.Color.orange()),
                ephemeral=True,
            )
            return

        shift_effects = self.engine.shift_effects(state.shifts)
        result = self.engine.player_action(state, action, shift_effects, random.Random())
        if not result["ok"]:
            await interaction.response.send_message(embed=discord.Embed(description=f"⚠️ {result['reason']}", color=discord.Color.orange()), ephemeral=True)
            return

        accent = await self.accent_color(user_id)
        if state.stage == "active":
            await self.repo.save_fight(user_id, state.to_dict())
            skill = self.skills_of(state)
            new_view = CombatView(self, user_id, state.potions, state.no_potions, skill.get("name", "Habilidad"))
            new_view.message = getattr(interaction, "message", None)
            await interaction.response.edit_message(embed=self.render_combat(state, accent, progress=await self.floor_progress(user_id)), view=new_view)
        elif state.stage == "victory":
            sections = await self.apply_victory(user_id, state)
            embed = self.render_combat(state, accent, ended=True, progress=await self.floor_progress(user_id), summary_fields=[("🎁 Botín", "\n".join(sections["loot"])), ("🗺️ Progreso", "\n".join(sections["progress"]))])
            await interaction.response.edit_message(embed=embed, view=CombatView(self, user_id, 0, ended=True))
        elif state.stage in ("fled", "timeout"):
            note = await self.apply_retreat(user_id, state)
            embed = self.render_combat(state, accent, ended=True, progress=await self.floor_progress(user_id), summary_fields=[("🏃 Retirada", note)])
            await interaction.response.edit_message(embed=embed, view=CombatView(self, user_id, 0, ended=True))
        else:
            note = await self.apply_defeat(user_id, state)
            embed = self.render_combat(state, accent, ended=True, progress=await self.floor_progress(user_id), summary_fields=[("💀 Derrota", note)])
            await interaction.response.edit_message(embed=embed, view=CombatView(self, user_id, 0, ended=True))

    async def apply_victory(self, user_id: int, state: BattleState) -> dict[str, list[str]]:
        if state.training:
            await self.repo.clear_fight(user_id)
            return {"loot": [], "progress": ["🎯 El simulacro no concede recompensas."]}
        user = await self.repo.get_user(user_id)
        rewards = state.rewards
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        updates: dict = {"potions": state.potions, "runs": int(user["runs"]) + 1}
        loot = [f"💰 **+{fmt_int(rewards['gold'])}** oro interno", f"⭐ **+{fmt_int(rewards['xp'])}** XP"]
        progress: list[str] = []

        level, xp, gained = self.engine.gain_xp(user["level"], user["xp"], rewards["xp"])
        updates["level"] = level
        updates["xp"] = xp
        if gained:
            loot.append(f"⬆️ ¡Subes al nivel **{level}**!")

        item_added = False
        if rewards.get("item"):
            item = rewards["item"]
            warning = await self.grant_item(user_id, item)
            if warning:
                loot.append(warning)
            else:
                item_added = True
                loot.append(f"🎁 **{item['name']}** {self.rarity_emoji(item['rarity'])}")

        if rewards.get("coins"):
            await self.repo.add_boss_coins(user_id, rewards["coins"])
            loot.append(f"🪙 **+{fmt_int(rewards['coins'])}** Monedas")

        if rewards.get("dust"):
            await self.repo.add_dust(user_id, rewards["dust"])
            loot.append(f"✨ **+{fmt_int(rewards['dust'])}** Polvo")

        if rewards.get("gold"):
            await self.repo.add_gold(user_id, rewards["gold"])

        if state.training:
            updates["training_used"] = int(user["training_used"]) + 1
        elif state.is_boss:
            tier = self.engine.boss_tier_for_floor(state.floor)
            highest = max(int(user["highest_floor"]), state.floor)
            updates.update(floor=state.floor + 1, highest_floor=highest, boss_tier=tier, last_boss_at=now, last_boss_floor=state.floor)
            await self.bot.global_stats.register_dungeon_depth(user_id, highest)
            await self.bot.global_stats.register_dungeon_floor_cleared(user_id)
            await self.bot.global_stats.register_dungeon_boss(user_id, tier, rewards["coins"])
            await self.repo.add_log(user_id, "boss", f"Derrotaste al jefe del piso {state.floor}.")
        elif state.is_anomaly:
            updates["last_alt_at"] = now
            updates["alt_floor"] = None
            await self.bot.global_stats.register_dungeon_anomaly(user_id)
            await self.repo.add_log(user_id, "anomaly", f"Cerraste la anomalía {state.anomaly_id}.")
        elif state.farm:
            pass
        else:
            needed = max(1, int(self.engine.cfg["enemies_per_floor"]))
            if int(user["floor_kills"]) >= needed:
                progress.append(f"🔁 El piso **{state.floor}** ya está despejado: estos enemigos no cuentan. Usa `/mazmorra avanzar` para bajar.")
            else:
                kills = int(user["floor_kills"]) + 1
                if kills >= needed:
                    highest = max(int(user["highest_floor"]), state.floor)
                    updates["highest_floor"] = highest
                    await self.bot.global_stats.register_dungeon_depth(user_id, highest)
                    await self.bot.global_stats.register_dungeon_floor_cleared(user_id)
                    if bool(user["auto_advance"]):
                        updates.update(floor=state.floor + 1, floor_kills=0)
                        progress.append(f"🚪 ¡Piso **{state.floor}** despejado! Desciendes al piso **{state.floor + 1}**.")
                        await self.repo.add_log(user_id, "floor", f"Despejaste el piso {state.floor}.")
                    else:
                        updates["floor_kills"] = needed
                        progress.append(f"🚪 ¡Piso **{state.floor}** despejado! Avance automático desactivado: usa `/mazmorra avanzar` para bajar.")
                else:
                    updates["floor_kills"] = kills
                    progress.append(f"👹 Enemigos derrotados: **{kills}/{needed}**")

        await self.repo.update_user(user_id, **updates)
        await self.repo.clear_fight(user_id)
        await self.refresh_vitals(user_id)

        await self.bot.global_stats.register_dungeon_loot(user_id, rewards["gold"], 1 if item_added else 0)
        if not state.training:
            await self.bot.global_stats.register_dungeon_kill(user_id)
        await self.bot.global_stats.register_dungeon_combat(user_id, state.damage_dealt, state.damage_taken)
        return {"loot": loot, "progress": progress}

    async def apply_defeat(self, user_id: int, state: BattleState) -> str:
        user = await self.repo.get_user(user_id)
        penalty = int(int(user["gold"]) * 0.10)
        await self.repo.spend_gold(user_id, penalty)
        await self.repo.update_user(user_id, potions=state.potions)
        await self.repo.clear_fight(user_id)
        await self.refresh_vitals(user_id)
        await self.bot.global_stats.register_dungeon_death(user_id)
        await self.bot.global_stats.register_dungeon_combat(user_id, state.damage_dealt, state.damage_taken)
        await self.repo.add_log(user_id, "death", f"Caíste en el piso {state.floor}.")
        return (f"Pierdes **{fmt_int(penalty)}** de oro interno, pero conservas tu piso {user['floor']}.\n" f"Vuelve a intentarlo cuando quieras.")

    async def apply_retreat(self, user_id: int, state: BattleState) -> str:
        user = await self.repo.get_user(user_id)
        penalty = int(int(user["gold"]) * float(self.engine.cfg["flee_gold_penalty_pct"]))
        if penalty:
            await self.repo.spend_gold(user_id, penalty)
        await self.repo.update_user(user_id, potions=state.potions)
        await self.repo.clear_fight(user_id)
        await self.refresh_vitals(user_id)
        await self.bot.global_stats.register_dungeon_retreat(user_id)
        if state.stage == "timeout":
            reason = "El combate se alargó demasiado y tuviste que retirarte."
        else:
            reason = "Te retiraste del combate."
        return (f"{reason} Conservas tu piso y tu equipo, pero no ganas recompensas." + (f" Pierdes **{fmt_int(penalty)}** de oro." if penalty else ""))

    async def start_fight_message(self, interaction: discord.Interaction, state: BattleState) -> None:
        user_id = interaction.user.id
        await self.repo.save_fight(user_id, state.to_dict())
        accent = await self.accent_color(user_id)
        skill = self.skills_of(state)
        view = CombatView(self, user_id, state.potions, state.no_potions, skill.get("name", "Habilidad"))
        await interaction.response.send_message(embed=self.render_combat(state, accent), view=view)
        try:
            view.message = await interaction.original_response()
        except discord.HTTPException:
            pass

    @mazmorra_group.command(name="explorar", description="Desciende por los pisos de la mazmorra.")
    @app_commands.describe(piso="Repite un piso ya superado para farmear equipo (opcional).")
    async def explore(self, interaction: discord.Interaction, piso: Optional[int] = None) -> None:
        user_id = interaction.user.id
        state = await self.active_fight(user_id)
        if state is not None:
            accent = await self.accent_color(user_id)
            skill = self.skills_of(state)
            view = CombatView(self, user_id, state.potions, state.no_potions, skill.get("name", "Habilidad"))
            await interaction.response.send_message(embed=self.render_combat(state, accent, progress=await self.floor_progress(user_id)), view=view)
            view.message = await interaction.original_response()
            return

        user, items, mutations, echoes = await self.profile_of(user_id)
        shifts = _json_list(user.get("shifts"))

        if piso is not None:
            if piso < 1 or piso > int(user["highest_floor"]):
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"⚠️ Solo puedes repetir pisos entre **1** y **{int(user['highest_floor'])}**.",
                        color=discord.Color.orange(),
                    ),
                    ephemeral=True,
                )
                return
            floor, farm = piso, True
        else:
            floor = int(user["floor"])
            if self.engine.is_gate_floor(floor):
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="🚪 Puerta de Jefe",
                        description=(f"El piso **{floor}** está bloqueado por un Jefe.\n"
                                     f"Resuélvelo con `/mazmorra jefe`, o farmea con `/mazmorra explorar piso:N`."),
                        color=discord.Color.dark_gold(),
                    ),
                    ephemeral=True,
                )
                return
            farm = False

        state = self.engine.start_floor(user, items, mutations, floor, shifts, user.get("active_skill") or self.engine.default_skill_id(), int(user["potions"]), farm=farm, echoes=echoes)
        await self.start_fight_message(interaction, state)

    @mazmorra_group.command(name="avanzar", description="Desciende al siguiente piso cuando ya lo has despejado.")
    async def advance(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        if await self.active_fight(user_id) is not None:
            await interaction.response.send_message(embed=discord.Embed(description="⚠️ Termina tu combate actual primero.", color=discord.Color.orange()), ephemeral=True)
            return
        user = await self.repo.get_user(user_id)
        floor = int(user["floor"])
        needed = max(1, int(self.engine.cfg["enemies_per_floor"]))
        if self.engine.is_gate_floor(floor):
            await interaction.response.send_message(embed=discord.Embed(description="⚠️ Este piso está bloqueado por un Jefe: resuélvelo con `/mazmorra jefe`.", color=discord.Color.orange()), ephemeral=True)
            return
        if int(user["floor_kills"]) < needed:
            await interaction.response.send_message(embed=discord.Embed(description=f"⚠️ Todavía no has despejado el piso **{floor}**: **{int(user['floor_kills'])}/{needed}** enemigos.", color=discord.Color.orange()), ephemeral=True)
            return
        await self.repo.update_user(user_id, floor=floor + 1, floor_kills=0)
        await self.repo.add_log(user_id, "floor", f"Descendiste al piso {floor + 1}.")
        await interaction.response.send_message(embed=discord.Embed(title="🚪 Desciendes", description=f"Bajas al piso **{floor + 1}**.", color=discord.Color.green()))

    @mazmorra_group.command(name="jefe", description="Desafía al Jefe que bloquea tu progreso.")
    async def boss(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        state = await self.active_fight(user_id)
        if state is not None:
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ Termina tu combate actual antes de desafiar a un Jefe.",
                                    color=discord.Color.orange()),
                ephemeral=True,
            )
            return

        user = await self.repo.get_user(user_id)
        floor = int(user["floor"])
        if not self.engine.is_gate_floor(floor):
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ Ahora mismo no hay ningún Jefe bloqueando tu avance.",
                                    color=discord.Color.orange()),
                ephemeral=True,
            )
            return

        cooldown = datetime.timedelta(hours=self.engine.cfg["boss_cooldown_hours"])
        last = parse_dt(user.get("last_boss_at"))
        if last and datetime.datetime.now(datetime.timezone.utc) < last + cooldown:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⏳ Los Jefes están reagrupándose",
                    description=f"Podrás volver a desafiar a un Jefe {discord.utils.format_dt(last + cooldown, 'R')}.",
                    color=discord.Color.dark_gold(),
                ),
                ephemeral=True,
            )
            return

        mutations = await self.repo.get_mutations(user_id)
        items = await self.repo.get_inventory(user_id)
        echoes = await self.repo.get_echoes(user_id)
        tier = self.engine.boss_tier_for_floor(floor)
        state = self.engine.start_boss(user, items, mutations, tier, _json_list(user.get("shifts")), user.get("active_skill") or self.engine.default_skill_id(), int(user["potions"]), echoes=echoes)
        await self.start_fight_message(interaction, state)

    @mazmorra_group.command(name="perfil", description="Consulta tu progreso en la mazmorra.")
    async def profile(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        user = await self.repo.get_user(user_id)
        items = await self.repo.get_inventory(user_id)
        mutations = await self.repo.get_mutations(user_id)
        cosmetics = await self.repo.get_cosmetics(user_id)
        stats = self.engine.player_stats(user, items, mutations)
        level = int(user["level"])
        xp_needed = self.engine.level_xp_needed(level)
        tier = int(user["boss_tier"])
        cap = self.engine.conversion_cap(tier)
        today = datetime.date.today().isoformat()
        used = int(user["conversion_used"]) if user.get("conversion_date") == today else 0

        embed = discord.Embed(title=f"🏰 Perfil de {interaction.user.display_name}", color=await self.accent_color(user_id))
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(
            name=f"🧙 Nivel {level}",
            value=f"`[{progress_bar(int(user['xp']), xp_needed)}]` {fmt_int(int(user['xp']))}/{fmt_int(xp_needed)} XP",
            inline=False,
        )
        embed.add_field(
            name="⚔️ Combate",
            value=(f"**Ataque:** {fmt_int(stats['attack'])}\n**Defensa:** {fmt_int(stats['defense'])}\n"
                   f"**Vida:** {fmt_int(stats['max_hp'])}\n**Energía:** {fmt_int(stats['max_energy'])}\n"
                   f"**Crítico:** {stats['crit'] * 100:.1f}%"),
            inline=True,
        )
        embed.add_field(
            name="🗺️ Progreso",
            value=(f"**Piso actual:** {int(user['floor'])} ({int(user['floor_kills'])}/{max(1, int(self.engine.cfg['enemies_per_floor']))} enemigos)\n**Piso máximo:** {int(user['highest_floor'])}\n"
                   f"**Avance automático:** {'sí' if bool(user['auto_advance']) else 'no'}\n**Jefes superados:** {tier}\n**Polvo:** {fmt_int(int(user['dust']))}"),
            inline=True,
        )
        embed.add_field(
            name="🪙 Economía",
            value=(f"**Oro interno:** {fmt_int(int(user['gold']))}\n"
                   f"**Monedas de Jefe:** {fmt_int(int(user['boss_coins']))}\n"
                   f"**Tope diario:** {fmt_int(cap)} Choskris ({int(used)}/{cap} usados)\n"
                   f"**Cambio:** 1 🪙 = {self.engine.cfg['conversion_rate']} Choskris"),
            inline=False,
        )

        equipped = [item for item in items if item.get("is_equipped")]
        gear_text = "\n".join(f"{self.rarity_emoji(item['rarity'])} **{item['name']}** ({self.slot_name(item['slot'])}, " f"{len(item['sockets'])} ranuras)" for item in equipped ) or "*Ninguno*"
        embed.add_field(name="🎒 Equipo", value=gear_text[:1024], inline=False)

        if mutations:
            mut_text = ", ".join(f"{self.engine.data['mutations'][mid]['emoji']} {self.engine.data['mutations'][mid]['name']} " f"nivel {lvl}" for mid, lvl in mutations.items() if mid in self.engine.data["mutations"])
            embed.add_field(name="🧬 Mutaciones", value=mut_text[:1024], inline=False)

        badges = [self.engine.data["boss_shop"][cid] for cid in cosmetics if cid in self.engine.data["boss_shop"] and self.engine.data["boss_shop"][cid].get("type") == "badge"]
        if badges:
            embed.add_field(name="🏅 Insignias", value=" ".join(b["emoji"] for b in badges), inline=False)

        await interaction.response.send_message(embed=embed)

    async def send_inventory(self, interaction: discord.Interaction, edit: bool = False, note: str = "") -> None:
        user_id = interaction.user.id
        items = await self.repo.get_inventory(user_id)
        equipped = [item for item in items if item.get("is_equipped")]
        embed = discord.Embed(title="🎒 Inventario de la Mazmorra", color=await self.accent_color(user_id))
        if note:
            embed.description = note
        embed.add_field(
            name="Equipado",
            value="\n\n".join(
                f"{self.rarity_emoji(item['rarity'])} "
                f"{self.engine.data['gear_slots'].get(item['slot'], {}).get('emoji', '')} "
                f"**{item['name']}** ({self.slot_name(item['slot'])})\n{self.describe_item(item)}"
                for item in equipped
            )[:1024] or "*Nada equipado*",
            inline=False,
        )
        embed.add_field(
            name="Mochila",
            value=(f"**{len(items)}/{max(1, int(self.engine.cfg.get('inventory_cap', 15)))}** objetos en total ({len(equipped)} equipados).\n"
                   f"**Solo se venden objetos desequipados**: usa el menú de abajo para desequipar lo que quieras soltar.\n"
                   f"Usa `/mazmorra forja` para reforjar o infundir ranuras."),
            inline=False,
        )
        view = InventoryView(self, user_id, items)
        if edit:
            await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    @mazmorra_group.command(name="inventario", description="Gestiona tu equipo.")
    async def inventory(self, interaction: discord.Interaction) -> None:
        await self.send_inventory(interaction)

    @mazmorra_group.command(name="forja", description="Refuerza, bloquea e infunde las ranuras de tu equipo.")
    async def forge(self, interaction: discord.Interaction) -> None:
        items = await self.repo.get_inventory(interaction.user.id)
        if not items:
            await interaction.response.send_message(
                embed=discord.Embed(description="🎒 No tienes objetos que forjar.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return
        first = next((item for item in items if item.get("is_equipped")), items[0])
        await self.send_forge(interaction, item_uid=first["item_uid"], socket_index=0)

    async def send_forge(self, interaction: discord.Interaction, edit: bool = False, item_uid: Optional[str] = None, socket_index: int = 0, note: str = "") -> None:
        user_id = interaction.user.id
        items = await self.repo.get_inventory(user_id)
        if not items:
            await interaction.response.send_message(
                embed=discord.Embed(description="🎒 No tienes objetos que forjar.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return
        selected = next((item for item in items if item["item_uid"] == item_uid), None) or items[0]
        user = await self.repo.get_user(user_id)
        reroll_cost = self.engine.socket_reroll_cost(selected)
        infuse_cost = self.engine.socket_infuse_cost()

        embed = discord.Embed(
            title="🔨 Forja de Enclaves",
            color=await self.accent_color(user_id),
            description=note or ("Reforja todas las ranuras **libres** a la vez, bloquea las que te gusten, "
                                 "o **infunde** una ranura con el disparador que elijas."),
        )
        embed.add_field(
            name=f"{self.rarity_emoji(selected['rarity'])} {selected['name']}",
            value=self.describe_item(selected)[:1024],
            inline=False,
        )
        embed.add_field(
            name="💸 Costes",
            value=(f"🔨 Reforjar ranuras libres: **{fmt_int(reroll_cost)}** oro\n"
                   f"🪙 Infundir la ranura seleccionada: **{fmt_int(infuse_cost)}** Monedas de Jefe"),
            inline=False,
        )
        embed.set_footer(text=f"Oro: {fmt_int(int(user['gold']))} · Monedas de Jefe: {fmt_int(int(user['boss_coins']))}")
        view = ForgeView(self, user_id, items, selected["item_uid"], socket_index)
        if edit:
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    async def forge_reroll(self, interaction: discord.Interaction, item_uid: str) -> None:
        user_id = interaction.user.id
        item = await self.repo.get_item(user_id, item_uid)
        if not item or not item["sockets"]:
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ Ese objeto no tiene ranuras.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return
        cost = self.engine.socket_reroll_cost(item)
        if not await self.repo.spend_gold(user_id, cost):
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Necesitas **{fmt_int(cost)}** de oro interno.",
                                    color=discord.Color.red()),
                ephemeral=True,
            )
            return
        sockets = self.engine.reroll_sockets(item, random.SystemRandom())
        await self.repo.set_item_sockets(user_id, item_uid, sockets)
        await self.refresh_vitals(user_id)
        await self.bot.global_stats.register_dungeon_reroll(user_id, sum(1 for mod in sockets if not mod.get("locked")))
        await self.send_forge(interaction, edit=True, item_uid=item_uid, socket_index=0, note=f"🔨 Has reforjado las ranuras libres por **{fmt_int(cost)}** oro.")

    async def forge_toggle_lock(self, interaction: discord.Interaction, item_uid: str, socket_index: int) -> None:
        user_id = interaction.user.id
        item = await self.repo.get_item(user_id, item_uid)
        if not item or not item["sockets"]:
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ Ese objeto no tiene ranuras.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return
        sockets = [dict(mod) for mod in item["sockets"]]
        index = min(max(0, socket_index), len(sockets) - 1)
        sockets[index]["locked"] = not sockets[index].get("locked")
        await self.repo.set_item_sockets(user_id, item_uid, sockets)
        state = "bloqueada 🔒" if sockets[index]["locked"] else "desbloqueada 🔓"
        await self.send_forge(interaction, edit=True, item_uid=item_uid, socket_index=index, note=f"Ranura **{index + 1}** {state}.")

    async def forge_offer_infusion(self, interaction: discord.Interaction, item_uid: str, socket_index: int) -> None:
        user_id = interaction.user.id
        cost = self.engine.socket_infuse_cost()
        user = await self.repo.get_user(user_id)
        if int(user["boss_coins"]) < cost:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Necesitas **{fmt_int(cost)}** Monedas de Jefe.",
                                    color=discord.Color.red()),
                ephemeral=True,
            )
            return
        item = await self.repo.get_item(user_id, item_uid)
        if not item or not item["sockets"]:
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ Ese objeto no tiene ranuras.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return
        candidates = self.engine.infuse_candidates(item, random.SystemRandom())
        embed = discord.Embed(
            title="🪙 Infusión de Enclave",
            color=discord.Color.dark_gold(),
            description=(f"Elige el disparador que ocupará la ranura **{socket_index + 1}** de "
                         f"**{item['name']}**.\nCoste: **{fmt_int(cost)}** Monedas de Jefe."),
        )
        for index, mod in enumerate(candidates):
            embed.add_field(name=f"Opción {index + 1}", value=self.describe_mod(mod)[:1024], inline=False)
        await interaction.response.edit_message(embed=embed, view=InfuseView(self, user_id, item_uid, socket_index, candidates))

    async def forge_apply_infusion(self, interaction: discord.Interaction, item_uid: str, socket_index: int, chosen: dict) -> None:
        user_id = interaction.user.id
        cost = self.engine.socket_infuse_cost()
        if not await self.repo.spend_boss_coins(user_id, cost):
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Necesitas **{fmt_int(cost)}** Monedas de Jefe.",
                                    color=discord.Color.red()),
                ephemeral=True,
            )
            return
        item = await self.repo.get_item(user_id, item_uid)
        if not item or not item["sockets"]:
            await self.repo.add_boss_coins(user_id, cost)
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ El objeto desapareció; se te ha reembolsado.",
                                    color=discord.Color.red()),
                ephemeral=True,
            )
            return
        sockets = [dict(mod) for mod in item["sockets"]]
        index = min(max(0, socket_index), len(sockets) - 1)
        sockets[index] = dict(chosen)
        await self.repo.set_item_sockets(user_id, item_uid, sockets)
        await self.refresh_vitals(user_id)
        await self.bot.global_stats.register_dungeon_infusion(user_id)
        await self.send_forge(interaction, edit=True, item_uid=item_uid, socket_index=index, note=f"🪙 Ranura **{index + 1}** infundida: {self.describe_mod(chosen)}")

    @mazmorra_group.command(name="mejoras", description="Compra pociones y mejoras con oro interno.")
    async def market(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        user = await self.repo.get_user(user_id)
        level = int(user["level"])
        upgrades = _json_dict(user.get("upgrades"))
        potion_spec = self.engine.data["market"]["potions"]
        options = [
            discord.SelectOption(
                label=f"{potion_spec['name']} ({fmt_int(self.engine.potion_price(level))} oro)"[:100],
                value="potions",
                description=potion_spec["desc"][:100],
                emoji=potion_spec["emoji"],
            )
        ]
        for key, spec in self.engine.data["upgrades"].items():
            current = int(upgrades.get(key, 0))
            cost = self.engine.upgrade_cost(key, current)
            options.append(discord.SelectOption(
                label=f"{spec['name']} · nivel {current} → {current + 1}"[:100],
                value=f"upgrade:{key}",
                description=f"{spec['desc']} Coste: {fmt_int(cost)} oro."[:100],
                emoji=spec["emoji"],
            ))
        embed = discord.Embed(
            title="🏪 Mejoras",
            description=("Pociones y mejoras permanentes compradas con **oro interno**.\n\n"
                         f"Oro disponible: **{fmt_int(int(user['gold']))}**\n"
                         f"Pociones: **{int(user['potions'])}**"),
            color=discord.Color.gold(),
        )
        view = MarketView(self, user_id, options)
        await interaction.response.send_message(embed=embed, view=view)

    async def market_buy(self, interaction: discord.Interaction, key: str, amount: int) -> None:
        user_id = interaction.user.id
        user = await self.repo.get_user(user_id)
        if key == "potions":
            unit = self.engine.potion_price(int(user["level"]))
            cost = unit * amount
            if not await self.repo.spend_gold(user_id, cost):
                await interaction.response.send_message(
                    embed=discord.Embed(description=f"❌ Necesitas **{fmt_int(cost)}** de oro interno.",
                                        color=discord.Color.red()),
                    ephemeral=True,
                )
                return
            new_potions = int(user["potions"]) + amount
            await self.repo.update_user(user_id, potions=new_potions)
            message = f"🧪 Has comprado **{amount}** poción(es) por **{fmt_int(cost)}** oro. Ahora tienes **{new_potions}**."
        else:
            upgrade_key = key.split(":", 1)[1]
            upgrades = _json_dict(user.get("upgrades"))
            current = int(upgrades.get(upgrade_key, 0))
            max_level = int(self.engine.cfg["upgrade_max_level"])
            amount = min(amount, max_level - current)
            if amount <= 0:
                await interaction.response.send_message(
                    embed=discord.Embed(description="❌ Esa mejora ya está al máximo.", color=discord.Color.orange()),
                    ephemeral=True,
                )
                return
            cost = sum(self.engine.upgrade_cost(upgrade_key, current + index) for index in range(amount))
            if not await self.repo.spend_gold(user_id, cost):
                await interaction.response.send_message(
                    embed=discord.Embed(description=f"❌ Necesitas **{fmt_int(cost)}** de oro interno.",
                                        color=discord.Color.red()),
                    ephemeral=True,
                )
                return
            upgrades[upgrade_key] = current + amount
            await self.repo.update_user(user_id, upgrades=json.dumps(upgrades))
            await self.refresh_vitals(user_id)
            spec = self.engine.data["upgrades"][upgrade_key]
            message = (f"{spec['emoji']} **{spec['name']}** sube a nivel **{current + amount}** " f"por **{fmt_int(cost)}** oro.")
        await interaction.response.edit_message(embed=discord.Embed(description=message, color=discord.Color.green()), view=None)

    @mazmorra_group.command(name="trofeos", description="Gasta Monedas de Jefe en insignias, acentos y enclaves.")
    async def shop(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        user = await self.repo.get_user(user_id)
        cosmetics = await self.repo.get_cosmetics(user_id)
        options = []
        for entry_id, spec in self.engine.data["boss_shop"].items():
            owned = entry_id in cosmetics
            label = f"{spec['name']} · {fmt_int(spec['cost'])} 🪙"
            if owned and spec.get("type") != "socket":
                label = f"{spec['name']} (en propiedad)"
            options.append(discord.SelectOption(
                label=label[:100],
                value=entry_id,
                description=spec["desc"][:100],
                emoji=spec.get("emoji", "🪙"),
            ))
        embed = discord.Embed(
            title="👑 Trofeos de Jefe",
            description=("Insignias, acentos y enclaves comprados con **Monedas de Jefe**.\n"
                         f"Monedas disponibles: **{fmt_int(int(user['boss_coins']))}** 🪙\n"
                         "Estas recompensas no afectan a la economía global."),
            color=discord.Color.dark_gold(),
        )
        await interaction.response.send_message(embed=embed, view=ShopView(self, user_id, options))

    async def shop_buy(self, interaction: discord.Interaction, entry_id: str) -> None:
        user_id = interaction.user.id
        spec = self.engine.data["boss_shop"].get(entry_id)
        if spec is None:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Ese artículo no existe.", color=discord.Color.red()), ephemeral=True)
            return

        cosmetics = await self.repo.get_cosmetics(user_id)
        if spec["type"] != "socket" and entry_id in cosmetics:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Ya posees esa recompensa.", color=discord.Color.orange()), ephemeral=True)
            return

        if spec["type"] == "socket":
            target = await self.pick_socket_target(user_id)
            if target is None:
                await interaction.response.send_message(
                    embed=discord.Embed(description="❌ No tienes ningún objeto equipado al que añadir una ranura.",
                                        color=discord.Color.orange()),
                    ephemeral=True,
                )
                return

        if not await self.repo.spend_boss_coins(user_id, int(spec["cost"])):
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Necesitas **{fmt_int(spec['cost'])}** Monedas de Jefe.",
                                    color=discord.Color.red()),
                ephemeral=True,
            )
            return

        if spec["type"] == "socket":
            target = await self.pick_socket_target(user_id)
            if target is None:
                await self.repo.add_boss_coins(user_id, int(spec["cost"]))
                await interaction.response.send_message(
                    embed=discord.Embed(description="❌ El objeto desapareció; se te ha reembolsado.",
                                        color=discord.Color.red()),
                    ephemeral=True,
                )
                return
            rng = random.SystemRandom()
            mod = self.engine.generate_mod(rng, self.engine.data["rarities"].get(target["rarity"], {}).get("power", 1.0), int(target["floor_found"]))
            sockets = list(target["sockets"]) + [mod]
            await self.repo.set_item_sockets(user_id, target["item_uid"], sockets)
            await self.refresh_vitals(user_id)
            message = (f"🔷 **{target['name']}** gana una ranura nueva " f"(`{mod['on']} → {mod['then']['type']}`). Ahora tiene **{len(sockets)}**.")
        else:
            await self.repo.add_cosmetic(user_id, entry_id)
            group = [cid for cid, other in self.engine.data["boss_shop"].items() if other.get("type") == spec["type"]]
            await self.repo.equip_cosmetic(user_id, entry_id, group)
            message = f"{spec.get('emoji', '🪙')} Has adquirido **{spec['name']}**."
            if spec["type"] == "accent":
                message += " Tus embeds de mazmorra ya usan este acento."

        await interaction.response.edit_message(embed=discord.Embed(description=message, color=discord.Color.green()), view=None)

    async def pick_socket_target(self, user_id: int) -> Optional[dict]:
        items = [item for item in await self.repo.get_inventory(user_id) if item.get("is_equipped")]
        if not items:
            return None
        order = {name: index for index, name in enumerate(self.engine.data["rarities"].keys())}
        return min(items, key=lambda item: (len(item["sockets"]), -order.get(item["rarity"], 0)))

    @mazmorra_group.command(name="canjear", description="Canjea Monedas de Jefe por Choskris (tope diario).")
    @app_commands.describe(cantidad="Cuántas Monedas de Jefe quieres canjear.")
    async def convert(self, interaction: discord.Interaction, cantidad: app_commands.Range[int, 1, 1_000_000]) -> None:
        await interaction.response.send_message("🏗️ Este comando está desactivado porque el juego está en beta 🏗️", ephemeral=True)
        return

        user_id = interaction.user.id
        user = await self.repo.get_user(user_id)
        tier = int(user["boss_tier"])
        cap = self.engine.conversion_cap(tier)
        rate = int(self.engine.cfg["conversion_rate"])
        today = datetime.date.today().isoformat()
        used = int(user["conversion_used"]) if user.get("conversion_date") == today else 0
        remaining_money = max(0, cap - used)
        max_by_cap = remaining_money // rate
        coins = min(int(cantidad), int(user["boss_coins"]), max_by_cap)
        if coins <= 0:
            reason = ("No tienes Monedas de Jefe suficientes." if int(user["boss_coins"]) <= 0 else f"Has alcanzado el tope diario ({fmt_int(cap)} Choskris).")
            await interaction.response.send_message(embed=discord.Embed(description=f"⚠️ {reason}", color=discord.Color.orange()), ephemeral=True)
            return
        money = coins * rate
        await self.repo.spend_boss_coins(user_id, coins)
        await self.repo.update_user(user_id, conversion_date=today, conversion_used=used + money)
        await self.bot.db.economy.update_balance(user_id, money)
        await self.bot.global_stats.register_dungeon_conversion(user_id, coins, money)
        balance = await self.bot.db.economy.get_balance(user_id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="💱 Canje completado",
                description=(f"Canjeaste **{fmt_int(coins)}** 🪙 por **{fmt_int(money)}** Choskris.\n"
                             f"Tope diario: **{fmt_int(used + money)}/{fmt_int(cap)}**\n"
                             f"Saldo actual: **{fmt_int(balance)}** Choskris."),
                color=discord.Color.green(),
            )
        )

    @mazmorra_group.command(name="mutaciones", description="Gasta Polvo Intergaláctico en mutaciones del sistema.")
    async def mutations_menu(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        user = await self.repo.get_user(user_id)
        owned = await self.repo.get_mutations(user_id)
        options = []
        for mutation_id, spec in self.engine.data["mutations"].items():
            current = int(owned.get(mutation_id, 0))
            cost = int(spec["cost_base"] * spec["cost_growth"] ** current) if current < spec["max_level"] else None
            status = "MÁX" if cost is None else f"nivel {current}→{current + 1} · {fmt_int(cost)} ✨"
            options.append(discord.SelectOption(
                label=f"{spec['name']} ({status})"[:100],
                value=mutation_id,
                description=spec["desc"][:100],
                emoji=spec["emoji"],
            ))
        embed = discord.Embed(
            title="🧬 Sistema de Mutaciones",
            description=(f"Polvo disponible: **{fmt_int(int(user['dust']))}** ✨\n"
                         "Las mutaciones reescriben las reglas del motor y sobreviven al prestigio."),
            color=discord.Color.dark_purple(),
        )
        lines = []
        for mutation_id, spec in self.engine.data["mutations"].items():
            level = int(owned.get(mutation_id, 0))
            lines.append(f"{spec['emoji']} **{spec['name']}** - nivel {level}/{spec['max_level']}")
        if lines:
            embed.add_field(name="Tus mutaciones", value="\n".join(lines)[:1024], inline=False)
        await interaction.response.send_message(embed=embed, view=MutationView(self, user_id, options))

    async def mutation_buy(self, interaction: discord.Interaction, mutation_id: str) -> None:
        user_id = interaction.user.id
        spec = self.engine.data["mutations"].get(mutation_id)
        if spec is None:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Esa mutación no existe.", color=discord.Color.red()), ephemeral=True)
            return
        user = await self.repo.get_user(user_id)
        owned = await self.repo.get_mutations(user_id)
        current = int(owned.get(mutation_id, 0))
        if current >= int(spec["max_level"]):
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ Esa mutación ya está al máximo.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return
        cost = int(spec["cost_base"] * spec["cost_growth"] ** current)
        if int(user["dust"]) < cost:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Necesitas **{fmt_int(cost)}** ✨ de Polvo (tienes {fmt_int(int(user['dust']))}).",
                                    color=discord.Color.red()),
                ephemeral=True,
            )
            return
        await self.repo.add_dust(user_id, -cost)
        await self.repo.set_mutation(user_id, mutation_id, current + 1)
        await self.bot.global_stats.register_dungeon_mutation(user_id)
        await interaction.response.edit_message(
            embed=discord.Embed(
                description=f"{spec['emoji']} **{spec['name']}** alcanza el nivel **{current + 1}** por **{fmt_int(cost)}** ✨.",
                color=discord.Color.green(),
            ),
            view=None,
        )

    @mazmorra_group.command(name="ecos", description="Gasta Polvo en Ecos permanentes, sin techo práctico.")
    async def echoes_menu(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        user = await self.repo.get_user(user_id)
        owned = await self.repo.get_echoes(user_id)
        options = []
        for echo_id, spec in self.engine.data["echoes"].items():
            level = int(owned.get(echo_id, 0))
            cost = self.echo_cost(echo_id, level)
            status = "MÁX" if cost is None else f"nivel {level} → {level + 1} · {fmt_int(cost)} ✨"
            options.append(discord.SelectOption(
                label=f"{spec['name']} ({status})"[:100],
                value=echo_id,
                description=spec["desc"][:100],
                emoji=spec["emoji"],
            ))
        embed = discord.Embed(
            title="✨ Ecos del Vacío",
            description=(f"Polvo disponible: **{fmt_int(int(user['dust']))}** ✨\n"
                         "Los Ecos son mejoras permanentes que sobreviven a todos los prestigios."),
            color=discord.Color.dark_purple(),
        )
        lines = [
            f"{spec['emoji']} **{spec['name']}** - nivel {int(owned.get(echo_id, 0))}/{spec['max_level']}"
            for echo_id, spec in self.engine.data["echoes"].items()
        ]
        embed.add_field(name="Tus Ecos", value="\n".join(lines)[:1024], inline=False)
        await interaction.response.send_message(embed=embed, view=EchoView(self, user_id, options))

    def echo_cost(self, echo_id: str, level: int) -> Optional[int]:
        spec = self.engine.data["echoes"][echo_id]
        if level >= int(spec["max_level"]):
            return None
        return int(spec["cost_base"] * spec["cost_growth"] ** level)

    async def echo_buy(self, interaction: discord.Interaction, echo_id: str) -> None:
        user_id = interaction.user.id
        spec = self.engine.data["echoes"].get(echo_id)
        if spec is None:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Ese Eco no existe.", color=discord.Color.red()), ephemeral=True)
            return
        owned = await self.repo.get_echoes(user_id)
        level = int(owned.get(echo_id, 0))
        cost = self.echo_cost(echo_id, level)
        if cost is None:
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ Ese Eco ya está al máximo.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return
        user = await self.repo.get_user(user_id)
        if int(user["dust"]) < cost:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ Necesitas **{fmt_int(cost)}** ✨ de Polvo (tienes {fmt_int(int(user['dust']))}).",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return
        await self.repo.add_dust(user_id, -cost)
        await self.repo.set_echo(user_id, echo_id, level + 1)
        await self.refresh_vitals(user_id)
        await self.bot.global_stats.register_dungeon_echo(user_id)
        await interaction.response.edit_message(
            embed=discord.Embed(
                description=f"{spec['emoji']} **{spec['name']}** alcanza el nivel **{level + 1}** por **{fmt_int(cost)}** ✨.",
                color=discord.Color.green(),
            ),
            view=None,
        )

    @mazmorra_group.command(name="habilidades", description="Elige la habilidad que usa el botón de combate.")
    async def skill_menu(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        user = await self.repo.get_user(user_id)
        skills = self.engine.available_skills(int(user["level"]))
        if not skills:
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ Todavía no has desbloqueado ninguna habilidad.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return
        options = []
        for skill in skills:
            mark = "✅ " if skill["id"] == self.engine.resolve_skill_id(user.get("active_skill")) else ""
            options.append(discord.SelectOption(
                label=f"{mark}{skill['name']}"[:100],
                value=skill["id"],
                description=f"{skill['desc']} ({skill['cost']}⚡, {skill['cooldown']}t enfriamiento)"[:100],
                emoji=skill["emoji"],
            ))
        await interaction.response.send_message(
            embed=discord.Embed(title="✨ Habilidades", description="Selecciona tu habilidad activa.",
                                color=discord.Color.blurple()),
            view=SkillView(self, user_id, options),
        )

    @mazmorra_group.command(name="entrenar", description="Entrena en segundo plano para ganar XP poco a poco.")
    async def train(self, interaction: discord.Interaction) -> None:
        await self.send_training(interaction)

    def passive_training_rate(self, mutation_level: int) -> float:
        spec = self.engine.data["mutations"]["training_room"]
        return float(spec.get("passive_base_pct", 0.0)) + float(spec.get("passive_pct_per_level", 0.0)) * max(0, mutation_level - 1)

    def passive_training_pending(self, user: dict, mutation_level: int) -> tuple[float, int]:
        since = parse_dt(user.get("training_since"))
        if not bool(user["training_enabled"]) or since is None:
            return 0.0, 0
        cap = float(self.engine.data["mutations"]["training_room"].get("passive_cap_hours", 24))
        elapsed = (datetime.datetime.now(datetime.timezone.utc) - since).total_seconds() / 3600.0
        hours = min(max(0.0, elapsed), cap)
        return hours, int(self.engine.level_xp_needed(int(user["level"])) * self.passive_training_rate(mutation_level) * hours)

    async def send_training(self, interaction: discord.Interaction, edit: bool = False, note: str = "") -> None:
        user_id = interaction.user.id
        mutations = await self.repo.get_mutations(user_id)
        mutation_level = self.engine.mutation_level(mutations, "training_room")
        if mutation_level <= 0:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"🔒 Necesitas la mutación **{self.mutation_name('training_room')}**.",
                                    color=discord.Color.dark_red()),
                ephemeral=True,
            )
            return
        user = await self.repo.get_user(user_id)
        enabled = bool(user["training_enabled"])
        hours, pending = self.passive_training_pending(user, mutation_level)
        spec = self.engine.data["mutations"]["training_room"]
        cap = float(spec.get("passive_cap_hours", 24))
        embed = discord.Embed(
            title=f"{spec['emoji']} {self.mutation_name('training_room')}",
            description=note or "Entrenamiento pasivo: acumula XP mientras esté activo, aunque no estés jugando.",
            color=discord.Color.dark_teal(),
        )
        embed.add_field(name="Estado", value="🟢 Activado" if enabled else "⚪ Desactivado", inline=True)
        embed.add_field(name="Ritmo", value=f"**{self.passive_training_rate(mutation_level) * 100:.1f}%** de nivel por hora", inline=True)
        embed.add_field(name="Tope", value=f"**{cap:.0f} h** (recógelo a diario)", inline=True)
        embed.add_field(name="Acumulado", value=(f"**{fmt_int(pending)}** XP en **{hours:.1f} h**" if pending else "*Nada todavía*"), inline=False)
        view = TrainingView(self, user_id, enabled, pending > 0)
        if edit:
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    async def toggle_training(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        user = await self.repo.get_user(user_id)
        if bool(user["training_enabled"]):
            note = await self.collect_training(user_id)
            await self.repo.update_user(user_id, training_enabled=0, training_since=None)
            await self.send_training(interaction, edit=True, note=f"{note}\n\n⚪ Entrenamiento **desactivado**.")
        else:
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            await self.repo.update_user(user_id, training_enabled=1, training_since=now)
            await self.send_training(interaction, edit=True, note="🟢 Entrenamiento **activado**: el XP se acumula desde ahora.")

    async def collect_training(self, user_id: int) -> str:
        mutations = await self.repo.get_mutations(user_id)
        mutation_level = self.engine.mutation_level(mutations, "training_room")
        user = await self.repo.get_user(user_id)
        hours, xp = self.passive_training_pending(user, mutation_level)
        if xp <= 0:
            return "🎓 Todavía no hay XP que recoger."
        level, remaining, gained = self.engine.gain_xp(int(user["level"]), int(user["xp"]), xp)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        await self.repo.update_user(user_id, level=level, xp=remaining, training_since=now)
        await self.refresh_vitals(user_id)
        await self.bot.global_stats.register_dungeon_passive_xp(user_id, xp)
        text = f"🎓 Recoges **{fmt_int(xp)}** XP de entrenamiento ({hours:.1f} h)."
        if gained:
            text += f" ⬆️ ¡Subes al nivel **{level}**!"
        return text

    async def claim_training(self, interaction: discord.Interaction) -> None:
        note = await self.collect_training(interaction.user.id)
        await self.send_training(interaction, edit=True, note=note)

    @mazmorra_group.command(name="practicar", description="Simulacro sin recompensas contra un muñeco que no puede morir.")
    @app_commands.describe(piso="Piso a simular (por defecto, aquel en el que estás).")
    async def practise(self, interaction: discord.Interaction, piso: Optional[int] = None) -> None:
        user_id = interaction.user.id
        mutations = await self.repo.get_mutations(user_id)
        if self.engine.mutation_level(mutations, "training_room") <= 0:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"🔒 Necesitas la mutación **{self.mutation_name('training_room')}**.",
                                    color=discord.Color.dark_red()),
                ephemeral=True,
            )
            return
        if await self.active_fight(user_id) is not None:
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ Termina tu combate actual primero.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return
        user = await self.repo.get_user(user_id)
        ref_floor = max(1, int(piso)) if piso else max(1, int(user["floor"]))
        items = await self.repo.get_inventory(user_id)
        echoes = await self.repo.get_echoes(user_id)
        state = self.engine.start_training(user, items, mutations, ref_floor, user.get("active_skill") or self.engine.default_skill_id(), int(user["potions"]), echoes=echoes)
        await self.bot.global_stats.register_dungeon_training(user_id)
        await self.start_fight_message(interaction, state)

    @mazmorra_group.command(name="anomalia", description="Entra en un piso alternativo (requiere mutación).")
    async def anomaly(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        mutations = await self.repo.get_mutations(user_id)
        mut_level = self.engine.mutation_level(mutations, "alternative_floors")
        if mut_level <= 0:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"🔒 Necesitas la mutación **{self.mutation_name('alternative_floors')}**.", color=discord.Color.dark_red()),
                ephemeral=True,
            )
            return
        if await self.active_fight(user_id) is not None:
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ Termina tu combate actual primero.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return
        user = await self.repo.get_user(user_id)
        cooldown = datetime.timedelta(minutes=self.engine.cfg["anomaly_cooldown_minutes"])
        last = parse_dt(user.get("last_alt_at"))
        if last and datetime.datetime.now(datetime.timezone.utc) < last + cooldown:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"⏳ Las anomalías se estabilizan {discord.utils.format_dt(last + cooldown, 'R')}.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return
        options = []
        for anomaly_id, spec in self.engine.data["anomalies"].items():
            if int(spec.get("min_mutation_level", 1)) > mut_level:
                continue
            options.append(discord.SelectOption(
                label=spec["name"], value=anomaly_id,
                description=f"Piso ×{spec['floor_mult']:.2f} · +{spec['dust_reward']}✨ · {spec['desc']}"[:100],
                emoji=spec["emoji"],
            ))
        if not options:
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ No tienes anomalías desbloqueadas todavía.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=discord.Embed(title="🌀 Anomalías Dimensionales",
                                description="Elige un piso alternativo. Su dificultad escala con tu piso máximo.",
                                color=discord.Color.dark_purple()),
            view=AnomalyView(self, user_id, options),
        )

    async def start_anomaly(self, interaction: discord.Interaction, anomaly_id: str) -> None:
        user_id = interaction.user.id
        user = await self.repo.get_user(user_id)
        mutations = await self.repo.get_mutations(user_id)
        items = await self.repo.get_inventory(user_id)
        echoes = await self.repo.get_echoes(user_id)
        state = self.engine.start_anomaly(user, items, mutations, anomaly_id, int(user["highest_floor"]), _json_list(user.get("shifts")), user.get("active_skill") or self.engine.default_skill_id(), int(user["potions"]), echoes=echoes)
        if state is None:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Esa anomalía no existe.", color=discord.Color.red()), ephemeral=True)
            return
        await self.start_fight_message(interaction, state)

    @mazmorra_group.command(name="alteraciones", description="Activa desplazamientos dimensionales para tus combates.")
    async def shift_menu(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        mutations = await self.repo.get_mutations(user_id)
        mut_level = self.engine.mutation_level(mutations, "dimensional_shifts")
        if mut_level <= 0:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"🔒 Necesitas la mutación **{self.mutation_name('dimensional_shifts')}**.", color=discord.Color.dark_red()),
                ephemeral=True,
            )
            return
        user = await self.repo.get_user(user_id)
        active = _json_list(user.get("shifts"))
        options = [
            discord.SelectOption(
                label=spec["name"], value=shift_id,
                description=spec["desc"][:100], emoji=spec["emoji"],
                default=shift_id in active,
            )
            for shift_id, spec in self.engine.data["shifts"].items()
        ]
        await interaction.response.send_message(
            embed=await self.render_shifts(user_id),
            view=ShiftsView(self, user_id, options, mut_level),
        )

    async def render_shifts(self, user_id: int) -> discord.Embed:
        user = await self.repo.get_user(user_id)
        active = _json_list(user.get("shifts"))
        mutations = await self.repo.get_mutations(user_id)
        mut_level = self.engine.mutation_level(mutations, "dimensional_shifts")
        lines = []
        for shift_id in active:
            spec = self.engine.data["shifts"].get(shift_id)
            if spec:
                lines.append(f"{spec['emoji']} **{spec['name']}** - {spec['desc']}")
        embed = discord.Embed(
            title=f"{self.engine.data['mutations']['dimensional_shifts']['emoji']} "
                  f"{self.mutation_name('dimensional_shifts')}",
            description=(f"Afijos activos: **{len(active)}/{mut_level}**\n"
                         "Los afijos alteran las reglas de tus combates y también tus recompensas."),
            color=discord.Color.dark_purple(),
        )
        if lines:
            embed.add_field(name="Activos", value="\n".join(lines)[:1024], inline=False)
        return embed

    @mazmorra_group.command(name="automatizar", description="Simula en segundo plano los pisos que ya has superado.")
    async def automate(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        mutations = await self.repo.get_mutations(user_id)
        mut_level = self.engine.mutation_level(mutations, "gambit_automator")
        if mut_level <= 0:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"🔒 Necesitas la mutación **{self.mutation_name('gambit_automator')}**.", color=discord.Color.dark_red()),
                ephemeral=True,
            )
            return
        automation = await self.repo.get_automation(user_id)
        spec = self.engine.data["mutations"]["gambit_automator"]
        ratio = float(spec["reward_ratio_base"]) + float(spec["reward_ratio_per_level"]) * (mut_level - 1)
        embed = discord.Embed(
            title=f"{self.engine.data['mutations']['gambit_automator']['emoji']} {self.mutation_name('gambit_automator')}",
            description=(f"Estado: **{'activo' if automation['enabled'] else 'inactivo'}**\n"
                         f"Pisos simulados por ciclo de 10 min: **{mut_level}**\n"
                         f"Ratio de recompensa: **{ratio * 100:.0f}%**\n"
                         f"Simulaciones totales: **{fmt_int(int(automation['sims']))}**"),
            color=discord.Color.dark_teal(),
        )
        if automation.get("last_report"):
            embed.add_field(name="Último informe", value=str(automation["last_report"])[:1024], inline=False)
        await interaction.response.send_message(embed=embed, view=AutomationView(self, user_id, bool(automation["enabled"])))

    async def toggle_automation(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        automation = await self.repo.get_automation(user_id)
        enabled = not bool(automation["enabled"])
        await self.repo.set_automation(user_id, enabled=1 if enabled else 0)
        label = self.mutation_name("gambit_automator")
        await interaction.response.edit_message(
            embed=discord.Embed(
                description=f"🤖 {label} **activado**." if enabled else f"🛑 {label} **desactivado**.",
                color=discord.Color.green() if enabled else discord.Color.dark_grey(),
            ),
            view=AutomationView(self, user_id, enabled),
        )

    @mazmorra_group.command(name="ajustes", description="Preferencias: avance automático de piso.")
    async def settings(self, interaction: discord.Interaction) -> None:
        await self.send_settings(interaction)

    async def send_settings(self, interaction: discord.Interaction, edit: bool = False) -> None:
        user = await self.repo.get_user(interaction.user.id)
        auto = bool(user["auto_advance"])
        needed = max(1, int(self.engine.cfg["enemies_per_floor"]))
        embed = discord.Embed(
            title="⚙️ Ajustes",
            description=(f"**Avance automático de piso:** {'activado' if auto else 'desactivado'}\n\n"
                         f"Cada piso requiere derrotar **{needed}** enemigos. Con el avance automático activado desciendes justo al despejarlo; "
                         f"con él desactivado te quedas en el piso (los enemigos que derrotes ahí ya no cuentan) hasta que uses `/mazmorra avanzar`."),
            color=discord.Color.blurple(),
        )
        view = SettingsView(self, interaction.user.id, auto)
        if edit:
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    async def toggle_auto_advance(self, interaction: discord.Interaction) -> None:
        user = await self.repo.get_user(interaction.user.id)
        await self.repo.update_user(interaction.user.id, auto_advance=0 if bool(user["auto_advance"]) else 1)
        await self.send_settings(interaction, edit=True)

    @mazmorra_group.command(name="acceso", description="Configura el rol de acceso a la mazmorra (operadores).")
    @app_commands.describe(rol="Rol que podrá usar la mazmorra. Sin argumento, muestra el actual.")
    async def configure(self, interaction: discord.Interaction, rol: Optional[discord.Role] = None) -> None:
        if await self.bot.filter_operators(interaction): return

        if rol is None:
            current = int(await self.bot.db.guild.get(interaction.guild.id, "dungeon_role_id") or 0)
            detail = f"<@&{current}>" if current else "*sin configurar*"
            await interaction.response.send_message(
                embed=discord.Embed(title="🔧 Acceso a la Mazmorra", description=f"Rol de acceso actual: {detail}", color=discord.Color.blurple()),
                ephemeral=True,
            )
            return
        await self.bot.db.guild.set(interaction.guild.id, "dungeon_role_id", rol.id)
        await interaction.response.send_message(
            embed=discord.Embed(title="🔧 Acceso actualizado", description=f"El rol de acceso a la mazmorra ahora es {rol.mention}.", color=discord.Color.green()),
            ephemeral=True,
        )

    @mazmorra_group.command(name="ayuda", description="Cómo funciona la Mazmorra RPG.")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🏰 Mazmorra RPG - Guía rápida",
            description=("Un dungeon crawler incremental exclusivo para suscriptores!"),
            color=discord.Color.dark_teal(),
        )
        embed.add_field(
            name="🏗️ Alerta: Juego en beta abierta 🏗️",
            value=(f"Este juego está en beta, es posible que el progreso se reinicie para todos en algún momento, y no se puede usar para ganar choskris aún. "
                   "Por favor jugad al juego igualmente para que lo vea en acción y salga de beta lo antes posible"),
            inline=False,
        )
        embed.add_field(
            name="⚔️ Bucle principal",
            value=(f"`/mazmorra explorar` - pelea; cada piso requiere derrotar {max(1, int(self.engine.cfg['enemies_per_floor']))} enemigos para despejarlo.\n"
                   "`/mazmorra jefe` - desafía al Jefe que bloquea cada 10 pisos (6h de espera tras ganar).\n"
                   "`/mazmorra avanzar` y `/mazmorra ajustes` - controlan el avance automático de piso.\n"
                   "`/mazmorra entrenar`, `/mazmorra practicar` y `/mazmorra anomalia` - requieren mutaciones."),
            inline=False,
        )
        embed.add_field(
            name="🧬 Sinergias",
            value=("Cada objeto genera triggers, condiciones y efectos. "
                   "Combínalos para crear builds absurdas; las mutaciones reescriben esas reglas."),
            inline=False,
        )
        embed.add_field(
            name="💱 Economía",
            value=("El oro interno se queda dentro del sistema. Las Monedas de Jefe se pueden canjear por Choskris "
                   "con `/mazmorra canjear`, sujeto a un tope diario que crece con cada Jefe superado."
                   "\n🏗️ Este comando está desactivado porque el juego está en beta aún 🏗️"),
            inline=False,
        )
        embed.add_field(
            name="🔨 Forja y Ecos",
            value=("`/mazmorra forja` - reforja las ranuras de un objeto, **bloquea** las que te gusten e "
                   "**infunde** una ranura con el trigger que elijas (usa monedas de Jefe).\n"
                   "`/mazmorra ecos` - mejoras permanentes compradas con Polvo."),
            inline=False,
        )
        embed.add_field(
            name="🌌 alteraciones",
            value="`/mazmorra alteraciones` - activa afijos que alteran las reglas del combate a cambio de una desventaja.",
            inline=False,
        )
        embed.add_field(
            name="🏃 Supervivencia",
            value=("Durante el combate puedes **Huir** en cualquier momento: conservas piso y equipo, "
                   "pero no ganas recompensas. Ningún combate puede eternizarse."),
            inline=False,
        )
        embed.add_field(
            name="✨ Prestigio",
            value="`/mazmorra prestigio` reinicia piso, nivel, oro y equipo, pero te da Polvo para mutaciones y Ecos permanentes.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @mazmorra_group.command(name="prestigio", description="Renace: reinicia tu progreso a cambio de Polvo Intergaláctico.")
    async def prestige(self, interaction: discord.Interaction) -> None:
        if not await ensure_dungeon_access(interaction):
            return
        user_id = interaction.user.id
        user = await self.repo.get_user(user_id)
        echoes = await self.repo.get_echoes(user_id)
        dust = int(self.engine.dust_for(int(user["highest_floor"])) * self.engine.echo_multiplier(echoes, "dust_mult"))
        if dust <= 0:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="⚠️ Necesitas haber llegado al menos al **piso 5** para obtener Polvo.",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="✨ Renacer (Prestigio)",
            description=(f"Polvo a obtener: **{fmt_int(dust)}** ✨ (piso máximo {int(user['highest_floor'])})\n\n"
                         "**Se reinicia:** piso actual, piso máximo, nivel, XP, oro interno, pociones, mejoras y equipo.\n"
                         "**Se conserva:** Polvo, Monedas de Jefe, mutaciones y cosméticos."),
            color=discord.Color.dark_purple(),
        )
        await interaction.response.send_message(embed=embed, view=PrestigeConfirmView(self, user_id, dust))

    async def do_prestige(self, interaction: discord.Interaction, dust: int) -> None:
        user_id = interaction.user.id
        await self.repo.clear_fight(user_id)
        await self.repo.delete_inventory(user_id)
        await self.repo.add_dust(user_id, dust)
        await self.repo.update_user(
            user_id,
            floor=1,
            highest_floor=0,
            level=1,
            xp=0,
            gold=0,
            potions=int(self.engine.cfg["potion_start"]),
            upgrades="{}",
            shifts="[]",
            alt_floor=None,
        )
        await self.refresh_vitals(user_id)
        await self.bot.global_stats.register_dungeon_prestige(user_id, dust)
        await self.repo.add_log(user_id, "prestige", f"Renaciste con {dust} de Polvo.")
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✨ Has renacido",
                description=f"El vacío te devuelve **{fmt_int(dust)}** ✨ de Polvo Intergaláctico.\nLa mazmorra vuelve a empezar.",
                color=discord.Color.dark_purple(),
            ),
            view=None,
        )

    @tasks.loop(minutes=10)
    async def automation_task(self) -> None:
        for row in await self.repo.automation_users():
            try:
                await self.run_automation(int(row["user_id"]))
            except Exception as error:
                print(f"[dungeon] Falló la automatización de {row['user_id']}: {error}")

    @automation_task.before_loop
    async def before_automation(self) -> None:
        await self.bot.wait_until_ready()

    async def run_automation(self, user_id: int) -> None:
        mutations = await self.repo.get_mutations(user_id)
        mut_level = self.engine.mutation_level(mutations, "gambit_automator")
        if mut_level <= 0:
            await self.repo.set_automation(user_id, enabled=0)
            return
        user = await self.repo.get_user(user_id)
        if int(user["highest_floor"]) < 1:
            return
        if await self.active_fight(user_id) is not None:
            return

        spec = self.engine.data["mutations"]["gambit_automator"]
        ratio = float(spec["reward_ratio_base"]) + float(spec["reward_ratio_per_level"]) * (mut_level - 1)
        echoes = await self.repo.get_echoes(user_id)
        rng = random.SystemRandom()
        floor = min(int(user["highest_floor"]), max(1, int(user["floor"]) - 1))
        gold = xp = 0
        items = []
        for _ in range(mut_level):
            reward = self.engine.auto_sim_rewards(floor, int(user["level"]), ratio, rng)
            gold += int(reward["gold"] * self.engine.echo_multiplier(echoes, "gold_mult"))
            xp += reward["xp"]
            if reward["item"]:
                items.append(reward["item"])
        level, remaining_xp, gained = self.engine.gain_xp(int(user["level"]), int(user["xp"]), xp)
        await self.repo.update_user(user_id, level=level, xp=remaining_xp)
        await self.repo.add_gold(user_id, gold)
        kept = lost = 0
        for item in items:
            warning = await self.grant_item(user_id, item)
            if warning:
                lost += 1
            else:
                kept += 1
        await self.refresh_vitals(user_id)
        automation = await self.repo.get_automation(user_id)
        report = f"Piso {floor} ×{mut_level}: +{fmt_int(gold)} oro, +{fmt_int(xp)} XP" + (f", {kept} objeto(s)" if kept else "") + (f", {lost} perdido(s) por mochila llena" if lost else "") + (f", nivel {level}" if gained else "")
        await self.repo.set_automation(user_id, sims=int(automation["sims"]) + mut_level, last_tick=datetime.datetime.now(datetime.timezone.utc).isoformat(), last_report=report)
        await self.bot.global_stats.register_dungeon_auto_sim(user_id, mut_level)


async def setup(bot: JoseLuisBot) -> None:
    await bot.add_cog(DungeonCog(bot))