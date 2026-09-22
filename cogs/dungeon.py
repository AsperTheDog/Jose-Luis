import datetime
import json
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from dungeon_engine import DEFEND_KEY, BattleState, DungeonEngine, fmt_int, progress_bar
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


GLOSSARY_SECTIONS = {
    "combate": ("⚔️", "Combate", "Cómo se pelea: daño, crítico, defensa, pociones y la vida entre combates."),
    "ranuras": ("🎲", "Ranuras", "Cuándo se dispara cada efecto, y por qué unas cifras son más grandes que otras."),
    "condiciones": ("🔎", "Condiciones", "Los «si…» que puede llevar una ranura."),
    "efectos": ("✨", "Efectos", "Qué hace cada ranura."),
    "estados": ("🩸", "Estados", "Venenos, debufos y bufos: pilas, duración y qué ignoran."),
    "equipo": ("🎒", "Equipo", "Rarezas, ranuras de equipo y venta."),
    "progresion": ("🗺️", "Progresión", "Pisos, jefes, mutaciones, anomalías y prestigio."),
    "economia": ("💰", "Economía", "Fragmentos, mejoras, trofeos y Choskris."),
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
    def __init__(
        self,
        cog: "DungeonCog",
        user_id: int,
        potions: int,
        no_potions: bool = False,
        skill_name: str = "Habilidad",
        ended: bool = False,
        skill_id: str = "",
        cooldowns: Optional[dict] = None,
        log: Optional[list[str]] = None,
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.message: Optional[discord.Message] = None
        self.log = list(log) if log is not None else None
        cooldowns = cooldowns or {}
        defend_left = int(cooldowns.get(DEFEND_KEY, 0))
        skill_left = int(cooldowns.get(skill_id, 0))

        self._add("Atacar", "⚔️", discord.ButtonStyle.danger, "attack", ended, row=0)
        self._add(f"Defender{self._cooldown_suffix(defend_left)}", "🛡️", discord.ButtonStyle.primary, "defend", ended or defend_left > 0, row=0)
        self._add(f"{skill_name[:56]}{self._cooldown_suffix(skill_left)}", "✨", discord.ButtonStyle.success, "skill", ended or skill_left > 0, row=0)
        self._add(f"Poción ({potions})", "🧪", discord.ButtonStyle.secondary, "potion", ended or no_potions or potions <= 0, row=0)
        self._add("Huir", "🏃", discord.ButtonStyle.secondary, "flee", ended, row=1)

        log_button = discord.ui.Button(label="Bitácora", emoji="📜", style=discord.ButtonStyle.secondary, row=1)
        log_button.callback = self._open_log
        self.add_item(log_button)

    @staticmethod
    def _cooldown_suffix(turns: int) -> str:
        return f" ({turns}t)" if turns > 0 else ""

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

    async def _open_log(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Estos botones no son para ti.", color=discord.Color.red()),
                ephemeral=True,
            )
            return
        entries = self.log
        if entries is None:
            battle = await self.cog.repo.get_battle_log(self.user_id)
            entries = (battle or {}).get("log") or []
        view = BattleLogView(self.cog, self.user_id, entries, interaction.message, self)
        await interaction.response.edit_message(embed=view.page_embed(), view=view)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class BattleLogView(discord.ui.View):
    PAGE_SIZE = 10

    def __init__(self, cog: "DungeonCog", user_id: int, entries: list[str], message: Optional[discord.Message], back_view: CombatView, page: int = 0):
        super().__init__(timeout=600)
        self.cog = cog
        self.user_id = user_id
        self.entries = list(entries)
        self.message = message
        self.back_view = back_view
        self.back_embed = message.embeds[0] if message and message.embeds else None
        self.pages = max(1, -(-len(self.entries) // self.PAGE_SIZE))
        self.page = max(0, min(page, self.pages - 1))

        previous = discord.ui.Button(label="Anterior", emoji="◀️", style=discord.ButtonStyle.secondary, disabled=self.page <= 0, row=0)
        previous.callback = lambda interaction: self._move(interaction, -1)
        following = discord.ui.Button(label="Siguiente", emoji="▶️", style=discord.ButtonStyle.secondary, disabled=self.page >= self.pages - 1, row=0)
        following.callback = lambda interaction: self._move(interaction, 1)
        back = discord.ui.Button(label="Volver al combate", emoji="↩️", style=discord.ButtonStyle.primary, row=1)
        back.callback = self._back
        self.add_item(previous)
        self.add_item(following)
        self.add_item(back)

    def page_embed(self) -> discord.Embed:
        start = self.page * self.PAGE_SIZE
        chunk = self.entries[start:start + self.PAGE_SIZE]
        embed = discord.Embed(
            title="📜 Bitácora del combate",
            description="\n".join(line[:200] for line in chunk)[:4000] or "*La mazmorra guarda silencio...*",
            color=DEFAULT_ACCENT,
        )
        embed.set_footer(text=f"Página {self.page + 1}/{self.pages} · {len(self.entries)} líneas")
        return embed

    async def _move(self, interaction: discord.Interaction, delta: int) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Estos botones no son para ti.", color=discord.Color.red()),
                ephemeral=True,
            )
            return
        view = BattleLogView(self.cog, self.user_id, self.entries, interaction.message, self.back_view, page=self.page + delta)
        view.back_embed = self.back_embed
        await interaction.response.edit_message(embed=view.page_embed(), view=view)

    async def _back(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Estos botones no son para ti.", color=discord.Color.red()),
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(embed=self.back_embed, view=self.back_view)

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
                    label=f"{item['name']} (+{fmt_int(item_value(item))} {cog.coin})"[:100],
                    value=item["item_uid"],
                    description=f"Vender · {cog.slot_name(item['slot'])} · {item['rarity']}"[:100],
                    emoji=cog.coin_emoji,
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
        await self.cog.sync_vitals(self.user_id)
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
        await self.cog.send_inventory(interaction, edit=True, note=f"{self.cog.coin_emoji} Has vendido **{item['name']}** por **{fmt_int(value)}** {self.cog.coin}.")

    async def _unequip_callback(self, interaction: discord.Interaction) -> None:
        item_uid = interaction.data["values"][0]
        item = await self.cog.repo.get_item(self.user_id, item_uid)
        if not item:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Ese objeto ya no existe.", color=discord.Color.red()), ephemeral=True)
            return
        await self.cog.repo.unequip_item(self.user_id, item_uid)
        await self.cog.sync_vitals(self.user_id)
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
        buy = discord.ui.Button(label="Comprar", emoji=cog.coin_emoji, style=discord.ButtonStyle.success)
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


class RerollAllView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, force: bool):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        self.force = force
        confirm = discord.ui.Button(label="Rerolear todo", emoji="🎲", style=discord.ButtonStyle.danger)
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
        await self.cog.do_reroll_all(interaction, self.force)

    async def _cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=discord.Embed(description="❌ Reroll global cancelado.", color=discord.Color.red()), view=None)


class GlossaryView(discord.ui.View):
    def __init__(self, cog: "DungeonCog", user_id: int, section: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        options = [discord.SelectOption(label=label, value=key, emoji=emoji, description=blurb[:100], default=key == section) for key, (emoji, label, blurb) in GLOSSARY_SECTIONS.items()]
        select = discord.ui.Select(placeholder="Elige una sección del glosario", options=options[:25])
        select.callback = self._pick
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ Este glosario no es tuyo.", color=discord.Color.red()), ephemeral=True)
            return False
        return True

    async def _pick(self, interaction: discord.Interaction) -> None:
        await self.cog.send_glossary(interaction, interaction.data["values"][0], edit=True)


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

    @property
    def coin(self) -> str:
        return self.engine.data.get("terms", {}).get("currency", {}).get("name", "Fragmentos")

    @property
    def coin_emoji(self) -> str:
        return self.engine.data.get("terms", {}).get("currency", {}).get("emoji", "💠")

    @property
    def boss_coin(self) -> str:
        return self.engine.data.get("terms", {}).get("boss_currency", {}).get("name", "Núcleos")

    @property
    def boss_coin_emoji(self) -> str:
        return self.engine.data.get("terms", {}).get("boss_currency", {}).get("emoji", "⚛️")

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
            return f"si tu escudo {sign} {cond.get('pct') or cond.get('value')}% de tu vida"
        if ctype == "IS_CRITICAL":
            return "si el último golpe fue crítico"
        if ctype == "HAS_STATUS":
            spec = self.engine.data["statuses"].get(cond.get("tag", ""), {})
            stacks = int(cond.get("stacks", 1))
            suffix = f" x{stacks}+" if stacks > 1 else ""
            return f"si {who} {'tiene' if target == 'foe' else 'tienes'} {spec.get('name', cond.get('tag', ''))}{suffix}"
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
            return f"infliges {_pct(effect.get('ratio', 0))} de daño {kind} al enemigo"
        if etype == "APPLY_STATUS":
            spec = self.engine.data["statuses"].get(effect.get("tag", ""), {})
            name = f"{spec.get('name', effect.get('tag', ''))} x{effect.get('stacks', 1)}"
            return f"aplica {name} al enemigo" if effect.get("target") == "foe" else f"te aplica {name}"
        if etype == "GAIN_SHIELD":
            return f"obtienes un escudo del {_pct(effect.get('ratio', 0))} de tu vida"
        if etype == "HEAL_HP":
            return f"te curas {_pct(effect.get('ratio', 0))} de tu vida"
        if etype == "REFUND_ENERGY":
            return f"recuperas {effect.get('value')} de energía"
        if etype == "STEAL_ENERGY":
            return f"le robas {effect.get('value')} de energía al enemigo"
        if etype == "LIFESTEAL":
            return f"te curas un {_pct(effect.get('ratio', 0))} del último golpe del combate"
        if etype == "PURGE_STATUS":
            spec = self.engine.data["statuses"].get(effect.get("tag", ""), {})
            return f"purga {spec.get('name', effect.get('tag', ''))} del enemigo"
        if etype == "CLEANSE":
            count = int(effect.get("value", 1))
            plural = "s" if count != 1 else ""
            return f"te limpia {count} estado{plural} negativo{plural}"
        if etype == "GAIN_GOLD":
            return f"ganas {fmt_int(effect.get('value', 0))} {self.coin}"
        if etype == "GRANT_XP":
            return f"ganas {effect.get('value')} de XP"
        if etype == "EXECUTE":
            return f"ejecutas al enemigo si está por debajo del {_pct(effect.get('pct', 0))} de vida"
        if etype == "REFLECT":
            spec = self.engine.data["statuses"].get(effect.get("tag", "THORNS"), {})
            return f"te aplica {spec.get('name', 'Espinas')} x{effect.get('stacks', 1)}"
        if etype == "EXTRA_TURN":
            return f"vuelves a atacar ({_pct(effect.get('chance', 0))} de probabilidad)"
        return str(etype).lower()

    def describe_mod(self, mod: dict) -> str:
        trigger = self.engine.data["trigger_tags"].get(mod.get("on"), {}).get("name", str(mod.get("on", "?")))
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

    def glossary_fields(self, section: str) -> list[tuple[str, str]]:
        data = self.engine.data
        cfg = self.engine.cfg
        if section == "combate":
            return [
                ("⚔️ Cómo se resuelve un golpe", (f"Cada turno eliges **Atacar**, **Defender**, tu **Habilidad**, **Poción** o **Huir**.\nEl daño se reduce por la defensa de quien lo recibe: `defensa / (defensa + ataque del atacante)`.\nLos estados de daño (quemadura, sangrado, veneno) sufren la mitad de esa reducción, y el **veneno** además ignora los escudos.")),
                ("🧱 Tipos de daño y resistencias", "Cada golpe lleva un tipo: **físico**, **fuego**, **hielo**, **rayo**, **veneno** o **arcano**. Algunos enemigos son **resistentes** a un tipo (por ejemplo el Gólem de Piedra, que encaja muy mal el daño físico) y el registro de combate lo marca. Cambiar de habilidad o de elementos es la forma de saltarse esa coraza."),
                ("🎯 Crítico y esquive", (f"Crítico base **{_pct(cfg['crit_chance_base'])}**; un crítico multiplica el daño por **{cfg['crit_multiplier']:g}** (tope {_pct(cfg['crit_cap'])}).\nEsquive base **{_pct(cfg['dodge_base'])}**: si esquivas, el golpe no hace nada.")),
                ("🛡️ Defender, energía y habilidad", (f"**Defender** te da un escudo del **{_pct(cfg['defend_shield_ratio'])}** de tu vida máxima, bloquea el **{_pct(cfg['defend_block'])}** del daño de ese turno y te devuelve **{cfg['defend_energy']}** de energía.\nTanto **Defender** (`{cfg['defend_cooldown']}` turnos) como tu **habilidad** tienen enfriamiento: verás los turnos que faltan en los propios botones.\nLos escudos no pasan del **{_pct(cfg['player_shield_cap_pct'])}** de tu vida máxima.\nEmpiezas con **{cfg['player_base_energy']}** de energía y recuperas **{cfg['player_energy_regen']}** por turno.")),
                ("⏳ Duración y retirada", (f"Un combate dura como mucho **{cfg['max_turns']}** turnos: si se alarga, te retiras agotado.\n**Huir** no da recompensas: pierdes el **{_pct(cfg['flee_hp_penalty_pct'])}** de tu vida máxima (nunca te deja por debajo de 1 PV) y conservas el resto de las heridas.")),
                ("🧪 Pociones", (f"En combate gastan el turno y curan **{_pct(cfg['potion_heal_ratio'])}** de tu vida máxima.\nFuera de combate se usan con `/mazmorra pocion`, sin gastar turno.")),
                ("❤️ Vida entre combates", (f"La vida se guarda entre combates y se regenera **{cfg['hp_regen_pct_per_minute']:g}%/min**, o **{cfg['hp_regen_recovery_pct_per_minute']:g}%/min** mientras te recuperas de una derrota.\nAl morir quedas **en recuperación**: no puedes combatir hasta estar al máximo, y las pociones aceleran la cura.")),
                ("📜 Bitácora", "El botón **Bitácora** de la pelea abre el registro completo del combate, con páginas, y sigue disponible cuando el combate ya ha terminado."),
            ]
        if section == "ranuras":
            table = data["tag_rules"]["power_by_frequency"]
            rows = []
            for freq, titulo in (("very_frequent", "Muy frecuentes"), ("frequent", "Frecuentes"), ("rare", "Poco frecuentes"), ("once", "Una vez por combate")):
                entries = [spec for spec in data["trigger_tags"].values() if freq in spec["tags"]]
                rows.append((f"{titulo} · presupuesto {int(table.get(freq, 1))}", "\n".join(f"**{spec['name']}** - {spec['desc']}" for spec in entries)))
            rows.append(("📏 Por qué unas cifras son más grandes que otras", "Cuanto más a menudo salta un disparador, **más pequeña** es la cifra máxima que puede llevar su efecto, y al contrario: el mismo efecto lleva números pequeños en *Al atacar* y puede llevar los más grandes en *Al matar* o *Al empezar el combate*.\nUna condición restrictiva (por ejemplo «si tu vida < 30%») sube un escalón ese presupuesto, y algunas parejas imposibles o redundantes no se generan nunca."))
            return rows
        if section == "condiciones":
            groups = (("Sobre ti", ("HP_BELOW", "HP_ABOVE", "ENERGY_BELOW", "ENERGY_ABOVE", "SHIELD_ABOVE", "SHIELD_BELOW", "SELF_HAS_STATUS")), ("Sobre el enemigo", ("FOE_HP_BELOW", "TARGET_HAS_STATUS", "STATUS_STACKS_ABOVE")), ("Sobre la situación", ("IS_CRITICAL", "RANDOM", "TURN_ABOVE", "FLOOR_ABOVE")))
            return [(titulo, "\n".join(f"**{data['condition_templates'][key]['name']}** - {data['condition_templates'][key]['desc']}" for key in keys if key in data["condition_templates"])) for titulo, keys in groups]
        if section == "efectos":
            priority = (("Defensivos y sustento", ("sustain", "heal", "buff", "defense", "mitigation")), ("Ofensivos", ("damage", "offense", "control")), ("Utilidad y economía", ("utility", "energy", "economy", "tempo", "progression")))
            grouped: dict[str, list[str]] = {titulo: [] for titulo, _ in priority}
            seen: set[str] = set()
            for titulo, tags in priority:
                for key in data["enabled_effects"]:
                    if key in seen or key not in data["effect_templates"]:
                        continue
                    if set(data["effect_templates"][key].get("tags", [])) & set(tags):
                        seen.add(key)
                        grouped[titulo].append(key)
            order = ("Ofensivos", "Defensivos y sustento", "Utilidad y economía")
            return [(titulo, "\n".join(f"**{data['effect_templates'][key]['name']}** - {data['effect_templates'][key]['desc']}" for key in grouped[titulo])) for titulo in order]
        if section == "estados":
            def linea(spec: dict) -> str:
                extra = []
                if int(spec.get("max_stacks", 1)) > 1:
                    extra.append(f"máx {spec['max_stacks']} pilas")
                if spec.get("turns"):
                    extra.append(f"{spec['turns']} turno" + ("s" if int(spec["turns"]) != 1 else ""))
                if spec.get("pierce"):
                    extra.append("ignora escudos")
                return f"{spec['emoji']} **{spec['name']}** - {spec['desc']}" + (f" ({', '.join(extra)})" if extra else "")
            negativos = [spec for spec in data["statuses"].values() if spec.get("kind") in ("dot", "debuff", "control")]
            positivos = [spec for spec in data["statuses"].values() if spec.get("kind") in ("buff", "shield")]
            todos = [spec for spec in data["statuses"].values() if spec.get("kind") not in ("dot", "debuff", "control", "buff", "shield")]
            rows = [("Negativos", "\n".join(linea(spec) for spec in negativos)), ("Positivos", "\n".join(linea(spec) for spec in positivos + todos)), ("Pilas y duración", "Los estados se acumulan en **pilas**: más pilas, más efecto. Cada aplicación refresca la duración y hay un tope de pilas por estado.")]
            return rows
        if section == "equipo":
            labels = {"attack": "ataque", "defense": "defensa", "max_hp": "vida", "max_energy": "energía", "crit": "crítico"}
            raridades = "\n".join(f"{spec['emoji']} **{spec['name']}** - {spec['sockets']} ranura" + ("s" if int(spec['sockets']) != 1 else "") + f", potencia de efecto ×{spec['power']:g}, estadísticas ×{spec['stat_mult']:g}" for spec in data["rarities"].values())
            slots = "\n".join(f"{spec['emoji']} **{spec['name']}** - sobre todo {labels[max(spec['stats'], key=spec['stats'].get)]}" for spec in data["gear_slots"].values())
            return [
                ("🎲 Rarezas", raridades),
                ("🎒 Ranuras de equipo", slots),
                ("📊 Estadísticas", f"**ATQ** ataque · **DEF** defensa · **VID** vida máxima · **ENE** energía máxima · **CRIT** probabilidad de crítico.\nPuedes llevar **{cfg['inventory_cap']}** objetos contando los equipados; lo que no quepa se pierde."),
                (f"{self.coin_emoji} Vender", "Desde `/mazmorra inventario` puedes equipar, desequipar y vender **solo lo que está en el zurrón**: lo equipado no se vende."),
            ]
        if section == "progresion":
            return [
                ("🗺️ Pisos", f"Cada piso pide derrotar **{cfg['enemies_per_floor']}** enemigos. Los pisos múltiplos de **{cfg['boss_interval']}** están bloqueados por un jefe (`/mazmorra jefe`); tras ganar hay **{cfg['boss_cooldown_hours']}h** de espera."),
                ("⭐ Nivel y XP", "La XP de los enemigos sube tu nivel, y el nivel sube ataque, vida, defensa y crítico (cada uno con su tope)."),
                ("🧬 Mutaciones", "Reescriben reglas del juego: sala de entrenamiento, ranuras cuánticas, automatización, pisos alternativos, desplazamientos... Se compran con Polvo."),
                ("🎓 Entrenar y practicar", "`/mazmorra entrenar` acumula XP pasiva mientras no juegas.\n`/mazmorra practicar` es un simulacro sin recompensas contra un muñeco que no puede morir."),
                ("🌀 Anomalías y alteraciones", "`/mazmorra anomalia` abre un piso alternativo con recompensa extra.\n`/mazmorra alteraciones` activa afijos que cambian las reglas del combate a cambio de una desventaja."),
                ("✨ Prestigio", f"`/mazmorra prestigio` reinicia piso, nivel, {self.coin} y equipo a cambio de **Polvo**: el piso máximo dividido entre 5, y el resultado elevado a {cfg['dust_exponent']:g}.\nEl Polvo compra **Ecos** permanentes en `/mazmorra ecos`: cuando los pisos se vuelven letales, esa es la forma de volver más fuerte."),
                ("💀 Muerte", f"Perder cuesta un 10% de tus {self.coin} y te deja en recuperación hasta curarte del todo; conservas piso y equipo."),
            ]
        if section == "economia":
            mejoras = "\n".join(f"{spec['emoji']} **{spec['name']}** - {spec['desc']} (desde {fmt_int(spec['cost'])} {self.coin}, ×{spec['growth']:g} por nivel, máx {cfg['upgrade_max_level']})" for spec in data["upgrades"].values())
            return [
                (f"{self.coin_emoji} {self.coin}", f"{data['terms']['currency']['desc']} Se gana matando ({fmt_int(cfg['gold_base'])} × {cfg['gold_growth']:g} por piso) y con efectos de {self.coin}."),
                ("⭐ Mejoras", mejoras),
                ("🧪 Pociones", f"Cuestan **{fmt_int(cfg['potion_price_base'])} × {cfg['potion_price_growth']:g}** por nivel y curan {_pct(cfg['potion_heal_ratio'])} de tu vida máxima."),
                (f"{self.boss_coin_emoji} {self.boss_coin}", f"{data['terms']['boss_currency']['desc']} Cada jefe superado da **{cfg['boss_coin_per_tier']}** por su nivel, y se gastan en `/mazmorra trofeos`: insignias, acentos y enclaves."),
                ("💱 Canjear", f"1 {self.boss_coin_emoji} = **{cfg['conversion_rate']}** Choskris. Cada día cambias **{fmt_int(cfg['conversion_soft_cap_base'])}** Choskris a ritmo completo (ese tramo crece ×{cfg['conversion_soft_cap_growth']:g} por jefe superado, hasta {fmt_int(cfg['conversion_soft_cap_max'])}), y a partir de ahí cada tramo va a **{_pct(cfg['conversion_decay'])}** del anterior: el día se acerca a un techo en vez de cortarse." + ("" if cfg.get("conversion_enabled", True) else " *Ahora mismo está en mantenimiento.*")),
                ("✨ Polvo", "Se gana al renacer (`/mazmorra prestigio`) y se gasta en mutaciones y Ecos."),
            ]
        return []

    async def send_glossary(self, interaction: discord.Interaction, section: str = "combate", edit: bool = False) -> None:
        key = section if section in GLOSSARY_SECTIONS else "combate"
        emoji, label, blurb = GLOSSARY_SECTIONS[key]
        embed = discord.Embed(title=f"{emoji} Glosario · {label}", description=blurb, color=discord.Color.dark_teal())
        for name, value in self.glossary_fields(key):
            if value:
                embed.add_field(name=name[:256], value=value[:1024], inline=False)
        embed.set_footer(text="Usa el menú para cambiar de sección · /mazmorra ayuda para la guía rápida")
        view = GlossaryView(self, interaction.user.id, key)
        if edit:
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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
        user = await self.sync_vitals(user_id)
        return (user, await self.repo.get_inventory(user_id), await self.repo.get_mutations(user_id), await self.repo.get_echoes(user_id))

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

    def regen_rate(self, recovering: bool) -> float:
        key = "hp_regen_recovery_pct_per_minute" if recovering else "hp_regen_pct_per_minute"
        return max(0.0, float(self.engine.cfg.get(key, 0.0)))

    async def sync_vitals(self, user_id: int, hp: Optional[int] = None, dead: bool = False, full: bool = False) -> dict:
        user = await self.repo.get_user(user_id)
        items = await self.repo.get_inventory(user_id)
        mutations = await self.repo.get_mutations(user_id)
        echoes = await self.repo.get_echoes(user_id)
        stats = self.engine.player_stats(user, items, mutations, echoes)
        max_hp = max(1, int(stats["max_hp"]))
        now = datetime.datetime.now(datetime.timezone.utc)
        stored_max = int(user.get("max_hp") or 0)
        current = int(user.get("hp") or 0)
        recovering = bool(int(user.get("recovering") or 0))
        stamp = parse_dt(user.get("hp_at"))

        if dead:
            current, recovering, stamp = 0, True, now
        elif full:
            current, recovering, stamp = max_hp, False, now
        elif hp is not None:
            current, stamp = int(hp), now
        elif stored_max <= 0:
            current, stamp = max_hp, now
        else:
            if stored_max != max_hp:
                current = int(round(current / stored_max * max_hp))
            if current < max_hp:
                elapsed = max(0.0, (now - (stamp or now)).total_seconds() / 60.0)
                healed = int(max_hp * self.regen_rate(recovering) * elapsed / 100.0)
                if healed > 0:
                    current = min(max_hp, current + healed)
                    stamp = now
            else:
                stamp = now

        current = max(0, min(max_hp, current))
        if current >= max_hp:
            recovering = False
        updates = {
            "hp": current,
            "max_hp": max_hp,
            "max_energy": int(stats["max_energy"]),
            "energy": int(stats["max_energy"]),
            "recovering": 1 if recovering else 0,
            "hp_at": (stamp or now).isoformat(),
        }
        await self.repo.update_user(user_id, **updates)
        user.update(updates)
        return user

    def recovery_note(self, user: dict) -> Optional[str]:
        if not int(user.get("recovering") or 0):
            return None
        max_hp = max(1, int(user.get("max_hp") or 0))
        hp = int(user.get("hp") or 0)
        per_minute = max(1.0, max_hp * self.regen_rate(True) / 100.0)
        minutes = int((max_hp - hp) / per_minute) + 1
        return (f"💀 Te recuperas de una derrota: **{fmt_int(hp)}/{fmt_int(max_hp)}** PV.\n" f"Necesitas la vida al máximo para volver a combatir (≈**{minutes} min**).\n" f"Acelera la cura bebiendo pociones con `/mazmorra pocion`.")

    async def block_if_recovering(self, interaction: discord.Interaction, user: dict) -> bool:
        note = self.recovery_note(user)
        if not note:
            return False
        await interaction.response.send_message(
            embed=discord.Embed(title="💀 Recuperación", description=note, color=discord.Color.dark_red()),
            ephemeral=True,
        )
        return True

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

    def render_combat(self, state: BattleState, accent: discord.Color, ended: bool = False, progress: Optional[tuple[int, int]] = None, summary_fields: Optional[list[tuple[str, str]]] = None, progress_notes: Optional[list[str]] = None) -> discord.Embed:
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

        embed.add_field(name="🗺️ Contexto", value=self.context_str(state, progress, ended, progress_notes)[:1024], inline=False)

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
        cooldowns = "" if ended else self.cooldowns_str(state)
        if cooldowns:
            player_value += f"\n\n{cooldowns}"
        embed.add_field(name="🧙 Tú", value=player_value[:1024], inline=False)

        recent = [line[:140] for line in state.log[-7:]]
        log_text = "\n".join(recent) if recent else "*La mazmorra guarda silencio...*"
        embed.add_field(name="📜 Bitácora", value=log_text[:1024], inline=False)

        skill = self.skills_of(state)
        embed.set_footer(text=f"Turno {state.turn} · 🧪 {state.potions} · 🎯 {skill.get('name', '?')} · Pulsa 📜 para el registro completo"[:2048])
        return embed

    def context_str(self, state: BattleState, progress: Optional[tuple[int, int]] = None, ended: bool = False, notes: Optional[list[str]] = None) -> str:
        mode = "Exploración"
        if state.is_boss:
            mode = "Jefe"
        elif state.is_anomaly:
            mode = "Anomalía"
        elif state.training:
            mode = "Simulacro"
        elif state.farm:
            mode = "Repetición"
        lines = [f"🗺️ **Piso {state.floor}** · {mode}"]
        if state.training:
            lines[0] += " · sin recompensas"
        elif state.farm:
            lines[0] += " · no cuenta para el progreso"
        elif not ended and not (state.is_boss or state.is_anomaly) and progress:
            lines.append(f"👹 Enemigos del piso: **{progress[0]}/{progress[1]}**")
        for shift_id in state.shifts:
            spec = self.engine.data["shifts"].get(shift_id)
            if not spec:
                continue
            detail = f"{spec.get('emoji', '')} **{spec.get('name', shift_id)}**"
            if spec.get("desc"):
                detail += f": {spec['desc']}"
            lines.append(detail)
        lines.extend(note for note in (notes or []) if note)
        return "\n".join(lines)

    def cooldowns_str(self, state: BattleState) -> str:
        parts = []
        defend_left = int(state.cooldowns.get(DEFEND_KEY, 0))
        if defend_left:
            parts.append(f"🛡️ Defender ({defend_left}t)")
        skill = self.skills_of(state)
        skill_left = int(state.cooldowns.get(state.skill_id, 0))
        if skill_left:
            parts.append(f"{skill.get('emoji', '✨')} {skill.get('name', 'Habilidad')} ({skill_left}t)")
        return ("⏳ En enfriamiento: " + " · ".join(parts)) if parts else ""

    def combat_view(self, user_id: int, state: BattleState, ended: bool = False, message: Optional[discord.Message] = None) -> CombatView:
        if ended:
            view = CombatView(self, user_id, 0, ended=True)
        else:
            skill = self.skills_of(state)
            view = CombatView(
                self,
                user_id,
                state.potions,
                state.no_potions,
                skill.get("name", "Habilidad"),
                skill_id=state.skill_id,
                cooldowns=state.cooldowns,
                log=state.log,
            )
        view.message = message
        return view

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
        current_message = getattr(interaction, "message", None)
        if state.stage == "active":
            await self.repo.save_fight(user_id, state.to_dict())
            new_view = self.combat_view(user_id, state, message=current_message)
            await interaction.response.edit_message(embed=self.render_combat(state, accent, progress=await self.floor_progress(user_id)), view=new_view)
        elif state.stage == "victory":
            sections = await self.apply_victory(user_id, state)
            embed = self.render_combat(state, accent, ended=True, progress=await self.floor_progress(user_id), summary_fields=[("🎁 Botín", "\n".join(sections["loot"]))], progress_notes=sections["progress"])
            await interaction.response.edit_message(embed=embed, view=self.combat_view(user_id, state, ended=True, message=current_message))
        elif state.stage in ("fled", "timeout"):
            note = await self.apply_retreat(user_id, state)
            embed = self.render_combat(state, accent, ended=True, progress=await self.floor_progress(user_id), summary_fields=[("🏃 Retirada", note)])
            await interaction.response.edit_message(embed=embed, view=self.combat_view(user_id, state, ended=True, message=current_message))
        else:
            note = await self.apply_defeat(user_id, state)
            embed = self.render_combat(state, accent, ended=True, progress=await self.floor_progress(user_id), summary_fields=[("💀 Derrota", note)])
            await interaction.response.edit_message(embed=embed, view=self.combat_view(user_id, state, ended=True, message=current_message))

    async def remember_battle(self, user_id: int, state: BattleState) -> None:
        await self.repo.save_battle_log(
            user_id,
            {
                "stage": state.stage,
                "floor": state.floor,
                "enemy": f"{state.enemy.emoji} {state.enemy.name}".strip(),
                "log": state.log,
            },
        )

    async def apply_victory(self, user_id: int, state: BattleState) -> dict[str, list[str]]:
        await self.remember_battle(user_id, state)
        if state.training:
            await self.repo.clear_fight(user_id)
            return {"loot": [], "progress": []}
        user = await self.repo.get_user(user_id)
        rewards = state.rewards
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        updates: dict = {"potions": state.potions, "runs": int(user["runs"]) + 1}
        loot = [f"{self.coin_emoji} **+{fmt_int(rewards['gold'])}** {self.coin}", f"⭐ **+{fmt_int(rewards['xp'])}** XP"]
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
            loot.append(f"{self.boss_coin_emoji} **+{fmt_int(rewards['coins'])}** {self.boss_coin}")

        if rewards.get("dust"):
            await self.repo.add_dust(user_id, rewards["dust"])
            loot.append(f"✨ **+{fmt_int(rewards['dust'])}** Polvo")

        if rewards.get("gold"):
            await self.repo.add_gold(user_id, rewards["gold"])

        if state.is_boss:
            tier = self.engine.boss_tier_for_floor(state.floor)
            highest = max(int(user["highest_floor"]), state.floor)
            updates.update(floor=state.floor + 1, highest_floor=highest, boss_tier=tier, last_boss_at=now, last_boss_floor=state.floor)
            await self.bot.global_stats.register_dungeon_depth(user_id, highest)
            await self.bot.global_stats.register_dungeon_floor_cleared(user_id)
            await self.bot.global_stats.register_dungeon_boss(user_id, tier, rewards["coins"])
            await self.repo.add_log(user_id, "boss", f"Derrotaste al jefe del piso {state.floor}.")
        elif state.is_anomaly:
            updates["last_alt_at"] = now
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
        await self.sync_vitals(user_id, hp=state.player.hp)

        await self.bot.global_stats.register_dungeon_loot(user_id, rewards["gold"], 1 if item_added else 0)
        if not state.training:
            await self.bot.global_stats.register_dungeon_kill(user_id)
        await self.bot.global_stats.register_dungeon_combat(user_id, state.damage_dealt, state.damage_taken)
        return {"loot": loot, "progress": progress}

    async def apply_defeat(self, user_id: int, state: BattleState) -> str:
        await self.remember_battle(user_id, state)
        user = await self.repo.get_user(user_id)
        penalty = int(int(user["gold"]) * 0.10)
        await self.repo.spend_gold(user_id, penalty)
        await self.repo.update_user(user_id, potions=state.potions)
        await self.repo.clear_fight(user_id)
        await self.sync_vitals(user_id, dead=True)
        await self.bot.global_stats.register_dungeon_death(user_id)
        await self.bot.global_stats.register_dungeon_combat(user_id, state.damage_dealt, state.damage_taken)
        await self.repo.add_log(user_id, "death", f"Caíste en el piso {state.floor}.")
        return (f"Pierdes **{fmt_int(penalty)}** {self.coin}, pero conservas tu piso {user['floor']}.\n" f"Vuelve a intentarlo cuando quieras.")

    async def apply_retreat(self, user_id: int, state: BattleState) -> str:
        await self.remember_battle(user_id, state)
        await self.repo.update_user(user_id, potions=state.potions)
        await self.repo.clear_fight(user_id)
        if state.training:
            await self.sync_vitals(user_id)
            wound = ""
        else:
            wound = self.flee_wound(state)
            await self.sync_vitals(user_id, hp=max(1, state.player.hp - self.flee_wound_value(state)))
        await self.bot.global_stats.register_dungeon_retreat(user_id)
        if state.stage == "timeout":
            reason = "El combate se alargó demasiado y tuviste que retirarte."
        else:
            reason = "Te retiraste del combate."
        return (f"{reason} Conservas tu piso y tu equipo, pero no ganas recompensas." + (f"\n{wound}" if wound else ""))

    def flee_wound_value(self, state: BattleState) -> int:
        if state.stage != "fled":
            return 0
        return int(state.player.max_hp * float(self.engine.cfg.get("flee_hp_penalty_pct", 0.0)))

    def flee_wound(self, state: BattleState) -> str:
        loss = self.flee_wound_value(state)
        if loss <= 0:
            return ""
        remaining = max(1, state.player.hp - loss)
        return f"🩸 Huir desangra: pierdes **{fmt_int(loss)}** PV y te quedas con **{fmt_int(remaining)}/{fmt_int(state.player.max_hp)}**."

    async def resolve_finished_fight(self, interaction: discord.Interaction, state: BattleState, accent: discord.Color) -> None:
        user_id = interaction.user.id
        notes: list[str] = []
        if state.stage == "victory":
            sections = await self.apply_victory(user_id, state)
            fields = [("🎁 Botín", "\n".join(sections["loot"]))]
            notes = sections["progress"]
        elif state.stage == "defeat":
            fields = [("💀 Derrota", await self.apply_defeat(user_id, state))]
        else:
            fields = [("🏃 Retirada", await self.apply_retreat(user_id, state))]
        embed = self.render_combat(state, accent, ended=True, progress=await self.floor_progress(user_id), summary_fields=fields, progress_notes=notes)
        view = self.combat_view(user_id, state, ended=True)
        await interaction.response.send_message(embed=embed, view=view)
        try:
            view.message = await interaction.original_response()
        except discord.HTTPException:
            pass

    async def start_fight_message(self, interaction: discord.Interaction, state: BattleState) -> None:
        user_id = interaction.user.id
        accent = await self.accent_color(user_id)
        if state.stage != "active":
            await self.resolve_finished_fight(interaction, state, accent)
            return
        await self.repo.save_fight(user_id, state.to_dict())
        view = self.combat_view(user_id, state)
        await interaction.response.send_message(embed=self.render_combat(state, accent, progress=await self.floor_progress(user_id)), view=view)
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
            view = self.combat_view(user_id, state)
            await interaction.response.send_message(embed=self.render_combat(state, accent, progress=await self.floor_progress(user_id)), view=view)
            view.message = await interaction.original_response()
            return

        user, items, mutations, echoes = await self.profile_of(user_id)
        shifts = _json_list(user.get("shifts"))
        if await self.block_if_recovering(interaction, user):
            return

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

    @mazmorra_group.command(name="pocion", description="Bebe una poción fuera de combate para recuperar vida.")
    async def drink_potion(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        if await self.active_fight(user_id) is not None:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="⚠️ Estás en combate: usa el botón **Poción**, que gasta el turno.",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        user = await self.sync_vitals(user_id)
        potions = int(user["potions"])
        max_hp = max(1, int(user["max_hp"]))
        hp = int(user["hp"])
        if potions <= 0:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ No te quedan pociones. Cómpralas con `/mazmorra mejoras`.", color=discord.Color.red()),
                ephemeral=True,
            )
            return
        if hp >= max_hp:
            await interaction.response.send_message(
                embed=discord.Embed(description="⚠️ Ya tienes la vida al máximo.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return

        healed = max(1, int(max_hp * float(self.engine.cfg["potion_heal_ratio"])))
        new_hp = min(max_hp, hp + healed)
        recovering = 1 if int(user.get("recovering") or 0) and new_hp < max_hp else 0
        await self.repo.update_user(
            user_id,
            potions=potions - 1,
            hp=new_hp,
            max_hp=max_hp,
            recovering=recovering,
            hp_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        lines = [
            f"Recuperas **{fmt_int(new_hp - hp)}** PV: **{fmt_int(new_hp)}/{fmt_int(max_hp)}** ❤️",
            f"Te quedan **{fmt_int(potions - 1)}** pociones.",
        ]
        if recovering:
            lines.append(f"Sigues en recuperación: necesitas la vida al máximo para volver a combatir.")
        await interaction.response.send_message(
            embed=discord.Embed(title="🧪 Poción de Vida", description="\n".join(lines), color=discord.Color.green()),
            ephemeral=True,
        )

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

        user = await self.sync_vitals(user_id)
        if await self.block_if_recovering(interaction, user):
            return
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
        user = await self.sync_vitals(user_id)
        items = await self.repo.get_inventory(user_id)
        mutations = await self.repo.get_mutations(user_id)
        cosmetics = await self.repo.get_cosmetics(user_id)
        stats = self.engine.player_stats(user, items, mutations)
        level = int(user["level"])
        xp_needed = self.engine.level_xp_needed(level)
        tier = int(user["boss_tier"])
        cap = self.engine.conversion_soft_cap(tier)
        techo = self.engine.conversion_daily_max(tier)
        today = datetime.date.today().isoformat()
        used = int(user["conversion_used"]) if user.get("conversion_date") == today else 0

        embed = discord.Embed(title=f"🏰 Perfil de {interaction.user.display_name}", color=await self.accent_color(user_id))
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(
            name=f"🧙 Nivel {level}",
            value=f"`[{progress_bar(int(user['xp']), xp_needed)}]` {fmt_int(int(user['xp']))}/{fmt_int(xp_needed)} XP",
            inline=False,
        )
        hp = int(user["hp"])
        max_hp = int(stats["max_hp"])
        embed.add_field(
            name="⚔️ Combate",
            value=(f"**Ataque:** {fmt_int(stats['attack'])}\n**Defensa:** {fmt_int(stats['defense'])}\n"
                   f"**Vida:** {fmt_int(hp)}/{fmt_int(max_hp)} `[{progress_bar(hp, max_hp)}]`\n**Energía:** {fmt_int(stats['max_energy'])}\n"
                   f"**Crítico:** {stats['crit'] * 100:.1f}%\n**Pociones:** {fmt_int(int(user['potions']))}\n"
                   f"**Regeneración:** {self.regen_rate(bool(int(user.get('recovering') or 0))):g}%/min"),
            inline=True,
        )
        recovery = self.recovery_note(user)
        if recovery:
            embed.add_field(name="💀 Recuperación", value=recovery, inline=False)
        embed.add_field(
            name="🗺️ Progreso",
            value=(f"**Piso actual:** {int(user['floor'])} ({int(user['floor_kills'])}/{max(1, int(self.engine.cfg['enemies_per_floor']))} enemigos)\n**Piso máximo:** {int(user['highest_floor'])}\n"
                   f"**Combates ganados:** {fmt_int(int(user['runs']))}\n**Avance automático:** {'sí' if bool(user['auto_advance']) else 'no'}\n**Jefes superados:** {tier}\n**Polvo:** {fmt_int(int(user['dust']))}"),
            inline=True,
        )
        ritmo = f"**Ritmo completo hoy:** {fmt_int(used)}/{fmt_int(cap)} Choskris" if used < cap else f"**Ritmo completo hoy:** agotado ({fmt_int(cap)} Choskris)"
        embed.add_field(
            name="💰 Economía",
            value=(f"**{self.coin}:** {fmt_int(int(user['gold']))}\n"
                   f"**{self.boss_coin}:** {fmt_int(int(user['boss_coins']))}\n"
                   f"**Cambio:** 1 {self.boss_coin_emoji} = {self.engine.cfg['conversion_rate']} Choskris\n"
                   f"{ritmo}\n"
                   f"**Techo del día:** ~{fmt_int(techo)} Choskris"),
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

        history = await self.history_field(user_id)
        if history:
            embed.add_field(name="📖 Últimos acontecimientos", value=history, inline=False)

        await interaction.response.send_message(embed=embed)

    HISTORY_EMOJI = {"floor": "🚪", "boss": "👑", "anomaly": "🌀", "death": "💀", "prestige": "✨"}

    async def history_field(self, user_id: int, limit: int = 8) -> str:
        entries = await self.repo.recent_log(user_id, limit)
        lines = []
        for entry in entries:
            emoji = self.HISTORY_EMOJI.get(str(entry.get("kind")), "•")
            stamp = parse_dt(entry.get("created_at"))
            when = f" · {discord.utils.format_dt(stamp, 'R')}" if stamp else ""
            lines.append(f"{emoji} {str(entry.get('message', ''))[:80]}{when}")
        return "\n".join(lines)[:1024]

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
                   f"**Solo se venden objetos desequipados**: usa el menú de abajo para desequipar lo que quieras soltar."),
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

    @mazmorra_group.command(name="mejoras", description="Compra pociones y mejoras permanentes.")
    async def market(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        user = await self.repo.get_user(user_id)
        level = int(user["level"])
        upgrades = _json_dict(user.get("upgrades"))
        potion_spec = self.engine.data["market"]["potions"]
        options = [
            discord.SelectOption(
                label=f"{potion_spec['name']} ({fmt_int(self.engine.potion_price(level))} {self.coin})"[:100],
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
                description=f"{spec['desc']} Coste: {fmt_int(cost)} {self.coin}."[:100],
                emoji=spec["emoji"],
            ))
        embed = discord.Embed(
            title="🏪 Mejoras",
            description=(f"Pociones y mejoras permanentes compradas con **{self.coin}**.\n\n"
                         f"{self.coin} disponibles: **{fmt_int(int(user['gold']))}**\n"
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
                    embed=discord.Embed(description=f"❌ Necesitas **{fmt_int(cost)}** {self.coin}.",
                                        color=discord.Color.red()),
                    ephemeral=True,
                )
                return
            new_potions = int(user["potions"]) + amount
            await self.repo.update_user(user_id, potions=new_potions)
            message = f"🧪 Has comprado **{amount}** poción(es) por **{fmt_int(cost)}** {self.coin}. Ahora tienes **{new_potions}**."
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
                    embed=discord.Embed(description=f"❌ Necesitas **{fmt_int(cost)}** {self.coin}.",
                                        color=discord.Color.red()),
                    ephemeral=True,
                )
                return
            upgrades[upgrade_key] = current + amount
            await self.repo.update_user(user_id, upgrades=json.dumps(upgrades))
            await self.sync_vitals(user_id)
            spec = self.engine.data["upgrades"][upgrade_key]
            message = (f"{spec['emoji']} **{spec['name']}** sube a nivel **{current + amount}** " f"por **{fmt_int(cost)}** {self.coin}.")
        await interaction.response.edit_message(embed=discord.Embed(description=message, color=discord.Color.green()), view=None)

    @mazmorra_group.command(name="trofeos", description="Gasta lo que sueltan los jefes en insignias, acentos y enclaves.")
    async def shop(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        user = await self.repo.get_user(user_id)
        cosmetics = await self.repo.get_cosmetics(user_id)
        options = []
        for entry_id, spec in self.engine.data["boss_shop"].items():
            owned = entry_id in cosmetics
            label = f"{spec['name']} · {fmt_int(spec['cost'])} {self.boss_coin_emoji}"
            if owned and spec.get("type") != "socket":
                label = f"{spec['name']} (en propiedad)"
            options.append(discord.SelectOption(
                label=label[:100],
                value=entry_id,
                description=spec["desc"][:100],
                emoji=spec.get("emoji", self.boss_coin_emoji),
            ))
        embed = discord.Embed(
            title="👑 Trofeos de Jefe",
            description=(f"Insignias, acentos y enclaves comprados con **{self.boss_coin}**.\n"
                         f"{self.boss_coin_emoji} {self.boss_coin} disponibles: **{fmt_int(int(user['boss_coins']))}**\n"
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
                embed=discord.Embed(description=f"❌ Necesitas **{fmt_int(spec['cost'])}** {self.boss_coin}.",
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
            await self.sync_vitals(user_id)
            message = (f"🔷 **{target['name']}** gana una ranura nueva " f"(`{mod['on']} → {mod['then']['type']}`). Ahora tiene **{len(sockets)}**.")
        else:
            await self.repo.add_cosmetic(user_id, entry_id)
            group = [cid for cid, other in self.engine.data["boss_shop"].items() if other.get("type") == spec["type"]]
            await self.repo.equip_cosmetic(user_id, entry_id, group)
            message = f"{spec.get('emoji', self.boss_coin_emoji)} Has adquirido **{spec['name']}**."
            if spec["type"] == "accent":
                message += " Tus embeds de mazmorra ya usan este acento."

        await interaction.response.edit_message(embed=discord.Embed(description=message, color=discord.Color.green()), view=None)

    async def pick_socket_target(self, user_id: int) -> Optional[dict]:
        items = [item for item in await self.repo.get_inventory(user_id) if item.get("is_equipped")]
        if not items:
            return None
        order = {name: index for index, name in enumerate(self.engine.data["rarities"].keys())}
        return min(items, key=lambda item: (len(item["sockets"]), -order.get(item["rarity"], 0)))

    @mazmorra_group.command(name="canjear", description="Canjea lo que sueltan los jefes por Choskris (tope diario).")
    @app_commands.describe(cantidad="Cuánto quieres canjear.")
    async def convert(self, interaction: discord.Interaction, cantidad: app_commands.Range[int, 1, 1_000_000]) -> None:
        if not bool(self.engine.cfg.get("conversion_enabled", True)):
            await interaction.response.send_message("🔧 Este comando está en mantenimiento 🔧", ephemeral=True)
            return

        user_id = interaction.user.id
        user = await self.repo.get_user(user_id)
        tier = int(user["boss_tier"])
        cap = self.engine.conversion_soft_cap(tier)
        rate = int(self.engine.cfg["conversion_rate"])
        today = datetime.date.today().isoformat()
        used = int(user["conversion_used"]) if user.get("conversion_date") == today else 0
        coins = min(int(cantidad), int(user["boss_coins"]))
        if coins <= 0:
            await interaction.response.send_message(embed=discord.Embed(description=f"⚠️ No tienes {self.boss_coin} suficientes.", color=discord.Color.orange()), ephemeral=True)
            return
        money = self.engine.conversion_value(coins, used, tier)
        if money <= 0:
            await interaction.response.send_message(embed=discord.Embed(description="⚠️ Ya has exprimido el cambio de hoy: mañana vuelve a empezar a ritmo completo.", color=discord.Color.orange()), ephemeral=True)
            return
        usable = self.engine.conversion_usable_coins(coins, used, tier)
        sobra = coins - usable
        coins = usable
        if not await self.repo.spend_boss_coins(user_id, coins):
            await interaction.response.send_message(embed=discord.Embed(description=f"⚠️ No tienes {self.boss_coin} suficientes.", color=discord.Color.orange()), ephemeral=True)
            return
        spent_value = used + coins * rate
        await self.repo.update_user(user_id, conversion_date=today, conversion_used=spent_value)
        await self.bot.db.economy.update_balance(user_id, money)
        await self.bot.global_stats.register_dungeon_conversion(user_id, coins, money)
        balance = await self.bot.db.economy.get_balance(user_id)
        detalle = f"\nHoy llevas **{fmt_int(spent_value)}** de {fmt_int(cap)} a ritmo completo." if spent_value <= cap else f"\nYa pasaste el tramo completo ({fmt_int(cap)}): el resto ha ido bajando de ritmo."
        aviso = f"\n⚠️ Más allá de ahí el cambio ya no paga nada, así que te has quedado con **{fmt_int(sobra)}** {self.boss_coin_emoji} intactos." if sobra else ""
        await interaction.response.send_message(
            embed=discord.Embed(
                title="💱 Canje completado",
                description=(f"Canjeaste **{fmt_int(coins)}** {self.boss_coin_emoji} por **{fmt_int(money)}** Choskris.{detalle}{aviso}\n"
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
        await self.sync_vitals(user_id)
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
            mark = "✅ " if skill["id"] == self.engine.resolve_skill_id(user.get("active_skill"), int(user["level"])) else ""
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
        await self.sync_vitals(user_id)
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
        user = await self.sync_vitals(user_id)
        if await self.block_if_recovering(interaction, user):
            return
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
        user = await self.sync_vitals(user_id)
        if await self.block_if_recovering(interaction, user):
            return
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
        last_tick = parse_dt(automation.get("last_tick"))
        embed = discord.Embed(
            title=f"{self.engine.data['mutations']['gambit_automator']['emoji']} {self.mutation_name('gambit_automator')}",
            description=(f"Estado: **{'activo' if automation['enabled'] else 'inactivo'}**\n"
                         f"Pisos simulados por ciclo de 10 min: **{mut_level}**\n"
                         f"Ratio de recompensa: **{ratio * 100:.0f}%**\n"
                         f"Simulaciones totales: **{fmt_int(int(automation['sims']))}**\n"
                         f"Última simulación: {discord.utils.format_dt(last_tick, 'R') if last_tick else '*todavía ninguna*'}"),
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

    @mazmorra_group.command(name="rerolear", description="Fuerza un reroll de las ranuras de TODOS los objetos de TODOS los jugadores (operadores).")
    @app_commands.describe(bloqueos="Respeta las ranuras que los jugadores tienen bloqueadas.")
    async def reroll_all(self, interaction: discord.Interaction, bloqueos: bool = False) -> None:
        if await self.bot.filter_operators(interaction): return

        items = await self.repo.all_items()
        if not items:
            await interaction.response.send_message(embed=discord.Embed(description="⚠️ Todavía no hay objetos en la mazmorra.", color=discord.Color.orange()), ephemeral=True)
            return
        sockets = sum(len(item.get("sockets") or []) for item in items)
        owners = len({int(item["user_id"]) for item in items})
        locked = sum(1 for item in items for mod in (item.get("sockets") or []) if mod.get("locked"))
        detalle = f"Se respetan las ranuras bloqueadas ({locked})." if bloqueos else f"Se ignoran los bloqueos: también cambian las bloqueadas ({locked})."
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🎲 Reroll global de ranuras",
                description=(f"**{len(items)}** objetos de **{owners}** jugadores · **{sockets}** ranuras en total.\n{detalle}\n\nNo se puede deshacer. ¿Seguro?"),
                color=discord.Color.dark_gold(),
            ),
            view=RerollAllView(self, interaction.user.id, not bloqueos),
            ephemeral=True,
        )

    async def do_reroll_all(self, interaction: discord.Interaction, force: bool) -> None:
        rng = random.SystemRandom()
        updates: list[tuple[str, list[dict]]] = []
        changed = kept = 0
        for item in await self.repo.all_items():
            sockets = list(item.get("sockets") or [])
            if not sockets:
                continue
            fresh = self.engine.reroll_sockets(item, rng, force=force)
            if fresh == sockets:
                continue
            for old, new in zip(sockets, fresh):
                if old == new:
                    kept += 1
                else:
                    changed += 1
            updates.append((item["item_uid"], fresh))
        await self.repo.save_item_sockets(updates)
        resumen = f"**{len(updates)}** objetos reroleados · **{changed}** ranuras nuevas"
        if kept:
            resumen += f" · **{kept}** sin tocar por bloqueo"
        await interaction.response.edit_message(
            embed=discord.Embed(title="🎲 Reroll completado", description=resumen + ".", color=discord.Color.green()),
            view=None,
        )

    @mazmorra_group.command(name="ayuda", description="Cómo funciona la Mazmorra RPG.")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🏰 Mazmorra RPG - Guía rápida",
            description=("Un dungeon crawler incremental exclusivo para suscriptores!"),
            color=discord.Color.dark_teal(),
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
            value=(f"Los {self.coin} se quedan dentro del sistema. Los {self.boss_coin} se pueden canjear por Choskris "
                   "con `/mazmorra canjear`: cada día hay un tramo a ritmo completo y, pasado ese tramo, el cambio va bajando de ritmo en vez de cortarse."),
            inline=False,
        )
        embed.add_field(
            name="✨ Ecos",
            value="`/mazmorra ecos` - mejoras permanentes compradas con Polvo.",
            inline=False,
        )
        embed.add_field(
            name="🌌 alteraciones",
            value="`/mazmorra alteraciones` - activa afijos que alteran las reglas del combate a cambio de una desventaja.",
            inline=False,
        )
        embed.add_field(
            name="❤️ Vida, pociones y muerte",
            value=(f"Tu vida **no se rellena** entre combates: se regenera poco a poco con el tiempo "
                   f"(**{self.engine.cfg['hp_regen_pct_per_minute']}%** por minuto, o "
                   f"**{self.engine.cfg['hp_regen_recovery_pct_per_minute']}%** mientras te recuperas de una derrota).\n"
                   "`/mazmorra pocion` - bebe una poción **fuera de combate** (en combate se usa el botón, que gasta el turno).\n"
                   "Si mueres quedas **en recuperación**: no puedes volver a combatir hasta estar al máximo."),
            inline=False,
        )
        embed.add_field(
            name="🏃 Supervivencia",
            value=("Durante el combate puedes **Huir** en cualquier momento: conservas piso y equipo, "
                   f"pero no ganas recompensas y pierdes el **{_pct(self.engine.cfg['flee_hp_penalty_pct'])}** de tu vida máxima. Ningún combate puede eternizarse."),
            inline=False,
        )
        embed.add_field(
            name="✨ Prestigio",
            value=f"`/mazmorra prestigio` reinicia piso, nivel, {self.coin} y equipo, pero te da Polvo para mutaciones y Ecos permanentes.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @mazmorra_group.command(name="glosario", description="Chuleta de términos y mecánicas de la mazmorra.")
    @app_commands.describe(seccion="Sección concreta del glosario.")
    @app_commands.choices(seccion=[app_commands.Choice(name=f"{emoji} {label}", value=key) for key, (emoji, label, _) in GLOSSARY_SECTIONS.items()])
    async def glossary(self, interaction: discord.Interaction, seccion: Optional[app_commands.Choice[str]] = None) -> None:
        await self.send_glossary(interaction, seccion.value if seccion else "combate")

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
                         f"**Se reinicia:** piso actual, piso máximo, nivel, XP, {self.coin}, pociones, mejoras y equipo.\n"
                         f"**Se conserva:** Polvo, {self.boss_coin}, mutaciones y cosméticos."),
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
        )
        await self.sync_vitals(user_id, full=True)
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
        await self.sync_vitals(user_id)
        automation = await self.repo.get_automation(user_id)
        report = f"Piso {floor} ×{mut_level}: +{fmt_int(gold)} {self.coin}, +{fmt_int(xp)} XP" + (f", {kept} objeto(s)" if kept else "") + (f", {lost} perdido(s) por mochila llena" if lost else "") + (f", nivel {level}" if gained else "")
        await self.repo.set_automation(user_id, sims=int(automation["sims"]) + mut_level, last_tick=datetime.datetime.now(datetime.timezone.utc).isoformat(), last_report=report)
        await self.bot.global_stats.register_dungeon_auto_sim(user_id, mut_level)


async def setup(bot: JoseLuisBot) -> None:
    await bot.add_cog(DungeonCog(bot))