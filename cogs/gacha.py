import asyncio
import json
import os
import random
import re
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image

from main import JoseLuisBot

CONFIG_PATH = "gacha.json"
UNITS_FOLDER = "gacha_units"
FRAMES_FOLDER = "gacha_frames"
FRAMED_FOLDER = os.path.join(UNITS_FOLDER, "framed")

UNIT_ID_RE = re.compile(r"[a-z0-9_]+")

RELEVANCE_CHOICES = ["Puntual", "Recurrente", "Principal", "Streamer"]


def _build_framed_image_sync(unit_id: str, rarity: int) -> Optional[str]:
    unit_path = os.path.join(UNITS_FOLDER, f"{unit_id}.png")
    background_path = os.path.join(FRAMES_FOLDER, f"fondo{rarity}s.png")
    frame_path = os.path.join(FRAMES_FOLDER, f"marco{rarity}s.png")

    if not (os.path.exists(unit_path) and os.path.exists(background_path) and os.path.exists(frame_path)):
        return None

    background = Image.open(background_path).convert("RGBA")
    unit_image = Image.open(unit_path).convert("RGBA")
    frame = Image.open(frame_path).convert("RGBA")

    canvas_size = (
        max(background.width, unit_image.width, frame.width),
        max(background.height, unit_image.height, frame.height),
    )

    def layered(layer: Image.Image) -> Image.Image:
        expanded = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        offset = ((canvas_size[0] - layer.width) // 2, (canvas_size[1] - layer.height) // 2)
        expanded.paste(layer, offset)
        return expanded

    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    for layer in (background, unit_image, frame):
        canvas = Image.alpha_composite(canvas, layered(layer))

    os.makedirs(FRAMED_FOLDER, exist_ok=True)
    output_path = os.path.join(FRAMED_FOLDER, f"{unit_id}_{rarity}s.png")
    canvas.save(output_path, format="PNG")
    return output_path


async def get_framed_image_path(unit_id: str, rarity: int) -> Optional[str]:
    cached_path = os.path.join(FRAMED_FOLDER, f"{unit_id}_{rarity}s.png")
    if os.path.exists(cached_path):
        return cached_path
    return await asyncio.to_thread(_build_framed_image_sync, unit_id, rarity)


class GachaRegistry:
    def __init__(self):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw_config = json.load(f)

        self.throw_cost: int = raw_config["throw_cost"]
        self.multi_throw_count: int = raw_config["multi_throw_count"]
        self.multi_throw_cost: int = raw_config["multi_throw_cost"]
        self.shards_per_unit: int = raw_config["shards_per_unit"]
        self.boost_cost_dust: int = raw_config["boost_cost_dust"]
        self.rarity_weights = {int(k): v for k, v in raw_config["rarity_weights"].items()}
        self.boosted_rarity_weights = {int(k): v for k, v in raw_config["boosted_rarity_weights"].items()}
        self.dust_per_shard = {int(k): v for k, v in raw_config["dust_per_shard"].items()}
        self.level_score_per_rarity = {int(k): v for k, v in raw_config["level_score_per_rarity"].items()}
        self.level_score_per_level: int = raw_config["level_score_per_level"]
        self.rarity_names = {int(k): v for k, v in raw_config["rarity_names"].items()}
        self.rarity_colors = {int(k): v for k, v in raw_config["rarity_colors"].items()}

    def roll_rarity(self, boosted: bool, available_rarities: set[int]) -> int:
        weights = self.boosted_rarity_weights if boosted else self.rarity_weights
        filtered = {r: w for r, w in weights.items() if r in available_rarities}
        return random.choices(list(filtered.keys()), weights=list(filtered.values()), k=1)[0]

    def compute_level(self, score: int) -> tuple[int, int, int]:
        level = 1
        remaining = score
        threshold = level * self.level_score_per_level
        while remaining >= threshold:
            remaining -= threshold
            level += 1
            threshold = level * self.level_score_per_level
        return level, remaining, threshold

    def compute_score(self, units_owned: dict[str, int], unit_definitions: dict[str, dict]) -> int:
        score = 0
        for unit_id, amount in units_owned.items():
            data = unit_definitions.get(unit_id)
            if data:
                score += self.level_score_per_rarity[data["rarity"]] * amount
        return score


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Solo quien ejecutó el comando puede confirmar esto.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Eliminar Definitivamente", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="🗑️ Eliminando...", view=self)
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Eliminación cancelada.", view=self)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(content="Eliminación cancelada (tiempo agotado).", view=self)
        except Exception:
            pass


class PaginatedEmbedView(discord.ui.View):
    def __init__(self, author_id: int, title: str, pages: list[str], color: discord.Color = discord.Color.blurple(), footer_extra: str = ""):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.title = title
        self.pages = pages
        self.color = color
        self.footer_extra = footer_extra
        self.current_page = 0
        self._update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Solo quien usó el comando puede pasar páginas.", ephemeral=True)
            return False
        return True

    def _update_buttons(self) -> None:
        self.previous_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page >= len(self.pages) - 1

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=self.title,
            description=self.pages[self.current_page],
            color=self.color
        )
        footer = f"Página {self.current_page + 1}/{len(self.pages)}"
        if self.footer_extra:
            footer += f" · {self.footer_extra}"
        embed.set_footer(text=footer)
        return embed

    @discord.ui.button(label="◀ Anterior", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Siguiente ▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception:
            pass


class CollectionView(discord.ui.View):
    def __init__(self, author_id: int, registry: GachaRegistry, target: discord.abc.User, units_owned: dict[str, int], unit_definitions: dict[str, dict[str, Any]]):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.registry = registry
        self.target = target
        self.units_owned = units_owned
        self.unit_definitions = unit_definitions
        self.current_choice = "summary"
        self.current_page = 0
        self._rarity_pages_cache: dict[int, list[str]] = {}

        self.units_by_rarity: dict[int, list[str]] = {}
        for unit_id, data in unit_definitions.items():
            self.units_by_rarity.setdefault(data["rarity"], []).append(unit_id)

        options = [discord.SelectOption(label="📋 Resumen General", value="summary", default=True)]
        for rarity in sorted(self.units_by_rarity.keys(), reverse=True):
            options.append(discord.SelectOption(label=registry.rarity_names[rarity], value=str(rarity)))

        self.select = discord.ui.Select(placeholder="Filtrar por rareza...", options=options, row=0)
        self.select.callback = self.select_callback
        self.add_item(self.select)
        self._update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Solo quien usó el comando puede interactuar con este menú.", ephemeral=True)
            return False
        return True

    def _get_rarity_pages(self, rarity: int) -> list[str]:
        if rarity in self._rarity_pages_cache:
            return self._rarity_pages_cache[rarity]

        unit_ids = sorted(self.units_by_rarity[rarity], key=lambda u: self.unit_definitions[u]["name"])

        lines = []
        for unit_id in unit_ids:
            data = self.unit_definitions[unit_id]
            if unit_id in self.units_owned:
                lines.append(f"{data['emoji']} **{data['name']}** - x{self.units_owned[unit_id]}")
            else:
                lines.append(f"❔ *{data['name']}* - *No descubierto*")

        if not lines:
            pages = ["*No hay personajes de esta rareza.*"]
        else:
            paginator = commands.Paginator(prefix="", suffix="", max_size=3500)
            for line in lines:
                paginator.add_line(line)
            pages = paginator.pages

        self._rarity_pages_cache[rarity] = pages
        return pages

    def _current_page_count(self) -> int:
        if self.current_choice == "summary":
            return 1
        return len(self._get_rarity_pages(int(self.current_choice)))

    def _update_buttons(self) -> None:
        total_pages = self._current_page_count()
        self.previous_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page >= total_pages - 1

    def build_summary_embed(self) -> discord.Embed:
        score = self.registry.compute_score(self.units_owned, self.unit_definitions)
        level, current, needed = self.registry.compute_level(score)
        progress_ratio = current / needed if needed else 0.0
        filled = int(progress_ratio * 10)
        bar = "█" * filled + "░" * (10 - filled)

        total_units = len(self.unit_definitions)
        unlocked = len(self.units_owned)

        best_rarity = max((self.unit_definitions[u]["rarity"] for u in self.units_owned if u in self.unit_definitions), default=None)
        color = discord.Color(self.registry.rarity_colors[best_rarity]) if best_rarity else discord.Color.light_grey()

        embed = discord.Embed(title=f"🏆 Colección de {self.target.display_name}", color=color)
        embed.set_thumbnail(url=self.target.display_avatar.url)
        embed.add_field(name=f"⭐ Nivel Gacha {level}", value=f"`[{bar}]` {current}/{needed}", inline=False)

        if total_units:
            embed.add_field(name="📖 Personajes Descubiertos", value=f"{unlocked}/{total_units}", inline=False)
        else:
            embed.add_field(name="📖 Personajes Descubiertos", value="*Todavía no hay personajes registrados.*", inline=False)

        for rarity in sorted(self.units_by_rarity.keys(), reverse=True):
            tier_units = self.units_by_rarity[rarity]
            owned_in_tier = [u for u in tier_units if u in self.units_owned]
            label = f"{self.registry.rarity_names[rarity]} ({len(owned_in_tier)}/{len(tier_units)})"

            if owned_in_tier:
                value = ", ".join(f"{self.unit_definitions[u]['emoji']} x{self.units_owned[u]}" for u in owned_in_tier)
            else:
                value = "*Ninguno todavía*"
            embed.add_field(name=label, value=value[:1024], inline=False)

        return embed

    def build_rarity_embed(self, rarity: int) -> discord.Embed:
        pages = self._get_rarity_pages(rarity)
        embed = discord.Embed(
            title=f"{self.registry.rarity_names[rarity]} - {self.target.display_name}",
            description=pages[self.current_page],
            color=discord.Color(self.registry.rarity_colors[rarity])
        )
        if len(pages) > 1:
            embed.set_footer(text=f"Página {self.current_page + 1}/{len(pages)}")
        return embed

    def build_current_embed(self) -> discord.Embed:
        if self.current_choice == "summary":
            return self.build_summary_embed()
        return self.build_rarity_embed(int(self.current_choice))

    async def select_callback(self, interaction: discord.Interaction):
        choice = self.select.values[0]
        for option in self.select.options:
            option.default = (option.value == choice)

        self.current_choice = choice
        self.current_page = 0
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_current_embed(), view=self)

    @discord.ui.button(label="◀ Anterior", style=discord.ButtonStyle.secondary, row=1)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_current_embed(), view=self)

    @discord.ui.button(label="Siguiente ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_current_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception:
            pass


class GachaCog(commands.Cog):
    def __init__(self, bot: JoseLuisBot):
        self.bot = bot
        self.registry = GachaRegistry()
        self.active_throws = set()

    gacha_group = app_commands.Group(
        name="gacha",
        description="Sistema de invocación de personajes gacha"
    )

    async def unit_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        current_lower = current.lower()
        all_units = await self.bot.db.gacha_get_all_unit_definitions()
        matches = [data for data in all_units.values() if current_lower in data["name"].lower()]
        matches.sort(key=lambda d: (-d["rarity"], d["name"]))
        return [
            app_commands.Choice(name=f"{data['name']} ({data['rarity']}★)", value=data["name"])
            for data in matches[:25]
        ]

    @gacha_group.command(name="fixemojis", description="Busca y arregla todos los emojis de personajes a los que les falten (Operadores)")
    async def fixemojis(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        await interaction.response.defer(thinking=True)

        app_emojis = await interaction.client.fetch_application_emojis()
        fixed = await self.bot.db.gacha_fix_missing_emojis(app_emojis)

        if fixed > 0:
            await interaction.followup.send(f"Se han actualizado los emojis de {fixed} personajes correctamente.", ephemeral=True)
        else:
            await interaction.followup.send("No se encontraron personajes sin emoji o con coincidencias pendientes.", ephemeral=True)

    @gacha_group.command(name="agregar", description="Registra un nuevo personaje en el sistema gacha")
    @app_commands.describe(
        identificador="ID único del personaje (a-z, 0-9, _). El archivo de imagen y el emoji deben llamarse igual",
        nombre="Nombre completo del personaje",
        frase="Frase o cita memorable del personaje",
        interprete="Quién interpreta al personaje",
        rareza="Rareza del personaje",
        fuente="Enlace de origen del personaje"
    )
    @app_commands.choices(
        rareza=[
            app_commands.Choice(name="⭐⭐ (2 Estrellas)", value=2),
            app_commands.Choice(name="⭐⭐⭐ (3 Estrellas)", value=3),
            app_commands.Choice(name="⭐⭐⭐⭐ (4 Estrellas)", value=4),
            app_commands.Choice(name="⭐⭐⭐⭐⭐ (5 Estrellas)", value=5),
        ],
    )
    async def add_unit(
        self,
        interaction: discord.Interaction,
        identificador: app_commands.Range[str, 1, 64],
        nombre: app_commands.Range[str, 1, 100],
        frase: app_commands.Range[str, 1, 300],
        interprete: str,
        rareza: app_commands.Choice[int],
        fuente: str,
    ):
        if await self.bot.filter_operators(interaction): return
        await interaction.response.defer(ephemeral=True)

        unit_id = identificador.strip().lower()
        if not UNIT_ID_RE.fullmatch(unit_id):
            await interaction.followup.send("⚠️ El ID solo puede contener minúsculas, números y guiones bajos.", ephemeral=True)
            return

        if not fuente.startswith(("http://", "https://")):
            await interaction.followup.send("⚠️ La fuente debe ser un enlace válido (empezando por http:// o https://).", ephemeral=True)
            return

        existing = await self.bot.db.gacha_get_unit_definition(unit_id)
        if existing:
            await interaction.followup.send(f"⚠️ Ya existe un personaje con el ID `{unit_id}`.", ephemeral=True)
            return

        existing_name = await self.bot.db.gacha_get_unit_definition_by_name(nombre)
        if existing_name:
            await interaction.followup.send(f"⚠️ Ya existe un personaje con el nombre **{nombre}**. Los nombres deben ser únicos.", ephemeral=True)
            return

        app_emojis = await self.bot.fetch_application_emojis()
        emoji_obj = discord.utils.get(app_emojis, name=unit_id)
        if not emoji_obj:
            await interaction.followup.send(
                f"⚠️ No se encontró ningún emoji de aplicación con el nombre `{unit_id}`. Debe estar registrado en el Discord Developer Portal.",
                ephemeral=True
            )
            return

        rarity = rareza.value
        created = await self.bot.db.gacha_add_unit_definition(unit_id, nombre, frase, interprete, rarity, fuente, str(emoji_obj))
        if not created:
            await interaction.followup.send(f"⚠️ Ya existe un personaje con el ID `{unit_id}`.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"{str(emoji_obj)} {nombre}",
            url=fuente,
            description=f"*\"{frase}\"*",
            color=discord.Color(self.registry.rarity_colors[rarity])
        )
        embed.add_field(name="ID", value=f"`{unit_id}`", inline=True)
        embed.add_field(name="Rareza", value=self.registry.rarity_names[rarity], inline=True)
        embed.add_field(name="Interpretado por", value=interprete, inline=True)

        await interaction.followup.send(content="✅ Personaje registrado correctamente.", embed=embed, ephemeral=True)

    @gacha_group.command(name="eliminar", description="Elimina un personaje del sistema (borra también sus fragmentos y unidades de todos los jugadores)")
    @app_commands.describe(personaje="Nombre del personaje a eliminar")
    @app_commands.autocomplete(personaje=unit_name_autocomplete)
    async def remove_unit(self, interaction: discord.Interaction, personaje: str):
        if await self.bot.filter_operators(interaction): return

        data = await self.bot.db.gacha_get_unit_definition_by_name(personaje)
        if not data:
            await interaction.response.send_message("⚠️ Ese personaje no existe. Escribe el nombre completo y exacto.", ephemeral=True)
            return

        unit_id = data["unit_id"]

        view = ConfirmDeleteView(interaction.user.id)
        await interaction.response.send_message(
            f"⚠️ **¿Seguro que quieres eliminar a {data['emoji']} {data['name']}?**\n"
            f"Esto borrará también todos los fragmentos y unidades que los jugadores tengan de este personaje. "
            f"**Esta acción no se puede deshacer.**",
            view=view,
            ephemeral=True
        )
        view.message = await interaction.original_response()
        await view.wait()

        if not view.confirmed:
            return

        await self.bot.db.gacha_delete_unit_definition(unit_id)

        for rarity in (2, 3, 4, 5):
            framed_path = os.path.join(FRAMED_FOLDER, f"{unit_id}_{rarity}s.png")
            if os.path.exists(framed_path):
                os.remove(framed_path)

        await interaction.edit_original_response(
            content=f"🗑️ **{data['name']}** ha sido eliminado del sistema gacha, junto con todos los fragmentos y unidades asociadas.",
            view=None
        )

    @gacha_group.command(name="tirar", description="Haz una tirada gacha para conseguir fragmentos de personaje")
    @app_commands.describe(
        veces="Tirada sencilla o Multitirada de 10",
        potenciar="Gasta polvo gacha para mejorar las probabilidades de esta tirada"
    )
    @app_commands.choices(veces=[
        app_commands.Choice(name="Tirada Sencilla (1000 choskris)", value=1),
        app_commands.Choice(name="Multitirada x10 (9000 choskris)", value=10),
    ])
    async def throw(self, interaction: discord.Interaction, veces: app_commands.Choice[int], potenciar: bool = False):
        user_id = interaction.user.id
        if user_id in self.active_throws:
            await interaction.response.send_message("⚠️ Ya tienes una tirada en curso.", ephemeral=True)
            return

        self.active_throws.add(user_id)
        try:
            all_units = await self.bot.db.gacha_get_all_unit_definitions()
            if not all_units:
                await interaction.response.send_message("⚠️ Todavía no hay personajes registrados en el sistema gacha.", ephemeral=True)
                return

            units_by_rarity: dict[int, list[str]] = {}
            for unit_id, data in all_units.items():
                units_by_rarity.setdefault(data["rarity"], []).append(unit_id)
            available_rarities = set(units_by_rarity.keys())

            count = veces.value
            cost = self.registry.throw_cost if count == 1 else self.registry.multi_throw_cost

            balance = await self.bot.db.economy_get_balance(user_id)
            if balance < cost:
                await interaction.response.send_message(f"⚠️ No tienes suficientes choskris. Necesitas **{cost:,}** y tienes **{balance:,}**.", ephemeral=True)
                return

            boost_total_cost = self.registry.boost_cost_dust * count
            use_boost = False
            if potenciar:
                dust = await self.bot.db.gacha_get_dust(user_id)
                if dust < boost_total_cost:
                    await interaction.response.send_message(
                        f"⚠️ No tienes suficiente polvo gacha para potenciar. Necesitas **{boost_total_cost:,}** y tienes **{dust:,}**.",
                        ephemeral=True
                    )
                    return
                use_boost = True

            await self.bot.db.economy_update_balance(user_id, -cost)
            if use_boost:
                await self.bot.db.gacha_add_dust(user_id, -boost_total_cost)
                await self.bot.global_stats.register_gacha_dust_spent(user_id, boost_total_cost)

            await self.bot.global_stats.register_gacha_throw(user_id, count, cost, use_boost)

            embed = discord.Embed(
                title="🎰 Invocando..." if count == 1 else "🎰 Invocación Múltiple...",
                description="*El portal empieza a brillar...*\n\n`[░░░░░░░░░░]`",
                color=discord.Color.dark_purple()
            )
            await interaction.response.send_message(embed=embed)

            suspense_frames = [
                ("*Algo se agita al otro lado...*", "`[███░░░░░░░]`"),
                ("*Una energía crece rápidamente...*", "`[███████░░░]`"),
                ("*¡Está a punto de emerger!*", "`[██████████]`"),
            ]
            for text, bar in suspense_frames:
                await asyncio.sleep(1.3)
                embed.description = f"{text}\n\n{bar}"
                await interaction.edit_original_response(embed=embed)

            results = []
            for _ in range(count):
                rarity = self.registry.roll_rarity(use_boost, available_rarities)
                unit_id = random.choice(units_by_rarity[rarity])
                await self.bot.db.gacha_add_shard(user_id, unit_id, 1)
                await self.bot.global_stats.register_gacha_shard_obtained(user_id, rarity)
                results.append((unit_id, rarity))

            boost_suffix = " · Tirada Potenciada ⚡" if use_boost else ""

            if count == 1:
                unit_id, rarity = results[0]
                data = all_units[unit_id]

                final_embed = discord.Embed(
                    title=f"✨ ¡{data['name']} obtenido!",
                    url=data["source"],
                    description=f"{data['emoji']} **{self.registry.rarity_names[rarity]}**\n*\"{data['phrase']}\"*",
                    color=discord.Color(self.registry.rarity_colors[rarity])
                )
                final_embed.set_footer(text=f"+1 fragmento añadido a tu inventario{boost_suffix}")

                image_path = await get_framed_image_path(unit_id, rarity)
                if image_path:
                    filename = os.path.basename(image_path)
                    file = discord.File(image_path, filename=filename)
                    final_embed.set_image(url=f"attachment://{filename}")
                    await interaction.edit_original_response(embed=final_embed, attachments=[file])
                else:
                    await interaction.edit_original_response(embed=final_embed)
            else:
                results.sort(key=lambda r: -r[1])
                best_rarity = results[0][1]

                lines = [
                    f"{all_units[unit_id]['emoji']} **{all_units[unit_id]['name']}** - {self.registry.rarity_names[rarity]}"
                    for unit_id, rarity in results
                ]

                final_embed = discord.Embed(
                    title="✨ ¡Invocación Múltiple Completada!",
                    description="\n".join(lines),
                    color=discord.Color(self.registry.rarity_colors[best_rarity])
                )
                final_embed.set_footer(text=f"+{count} fragmentos añadidos a tu inventario{boost_suffix}")
                await interaction.edit_original_response(embed=final_embed)
        finally:
            self.active_throws.discard(user_id)

    @gacha_group.command(name="destruir", description="Destruye fragmentos de un personaje para obtener polvo gacha")
    @app_commands.describe(personaje="Nombre del personaje", cantidad="Cantidad de fragmentos a destruir")
    @app_commands.autocomplete(personaje=unit_name_autocomplete)
    async def destroy_shards(self, interaction: discord.Interaction, personaje: str, cantidad: app_commands.Range[int, 1, 9999] = 1):
        data = await self.bot.db.gacha_get_unit_definition_by_name(personaje)
        if not data:
            await interaction.response.send_message("⚠️ Ese personaje no existe. Escribe el nombre completo y exacto.", ephemeral=True)
            return

        unit_id = data["unit_id"]
        removed = await self.bot.db.gacha_remove_shards(interaction.user.id, unit_id, cantidad)
        if not removed:
            owned = await self.bot.db.gacha_get_shard_count(interaction.user.id, unit_id)
            await interaction.response.send_message(
                f"⚠️ No tienes suficientes fragmentos de **{data['name']}** (tienes {owned}, necesitas {cantidad}).",
                ephemeral=True
            )
            return

        dust_gained = self.registry.dust_per_shard[data["rarity"]] * cantidad
        await self.bot.db.gacha_add_dust(interaction.user.id, dust_gained)
        await self.bot.global_stats.register_gacha_shard_destroyed(interaction.user.id, cantidad, dust_gained)

        await interaction.response.send_message(
            f"💨 Has destruido **{cantidad}x** fragmento(s) de {data['emoji']} **{data['name']}** y obtenido **{dust_gained:,}** de polvo gacha."
        )

    @gacha_group.command(name="crear", description="Convierte fragmentos en una unidad completa del personaje")
    @app_commands.describe(personaje="Nombre del personaje", cantidad="Cuántas unidades crear de una vez")
    @app_commands.autocomplete(personaje=unit_name_autocomplete)
    async def craft_unit(self, interaction: discord.Interaction, personaje: str, cantidad: app_commands.Range[int, 1, 999] = 1):
        data = await self.bot.db.gacha_get_unit_definition_by_name(personaje)
        if not data:
            await interaction.response.send_message("⚠️ Ese personaje no existe. Escribe el nombre completo y exacto.", ephemeral=True)
            return

        unit_id = data["unit_id"]
        needed = self.registry.shards_per_unit * cantidad
        removed = await self.bot.db.gacha_remove_shards(interaction.user.id, unit_id, needed)
        if not removed:
            owned = await self.bot.db.gacha_get_shard_count(interaction.user.id, unit_id)
            await interaction.response.send_message(
                f"⚠️ No tienes suficientes fragmentos de **{data['name']}** (tienes {owned}, necesitas {needed}).",
                ephemeral=True
            )
            return

        await self.bot.db.gacha_add_unit(interaction.user.id, unit_id, cantidad)
        await self.bot.global_stats.register_gacha_unit_crafted(interaction.user.id, cantidad)

        total_units = await self.bot.db.gacha_get_unit_count(interaction.user.id, unit_id)
        await interaction.response.send_message(
            f"✨ Has creado **{cantidad}x** {data['emoji']} **{data['name']}**. Ahora tienes **{total_units}** unidad(es) de este personaje."
        )

    @gacha_group.command(name="inspeccionar", description="Consulta la información y la insignia de un personaje")
    @app_commands.describe(personaje="Nombre del personaje")
    @app_commands.autocomplete(personaje=unit_name_autocomplete)
    async def inspect_unit(self, interaction: discord.Interaction, personaje: str):
        data = await self.bot.db.gacha_get_unit_definition_by_name(personaje)
        if not data:
            await interaction.response.send_message("⚠️ Ese personaje no existe. Escribe el nombre completo y exacto.", ephemeral=True)
            return

        await interaction.response.defer()

        unit_id = data["unit_id"]
        rarity = data["rarity"]
        shard_count = await self.bot.db.gacha_get_shard_count(interaction.user.id, unit_id)
        unit_count = await self.bot.db.gacha_get_unit_count(interaction.user.id, unit_id)

        embed = discord.Embed(
            title=f"{data['emoji']} {data['name']}",
            url=data["source"],
            description=f"*\"{data['phrase']}\"*",
            color=discord.Color(self.registry.rarity_colors[rarity])
        )
        embed.add_field(name="Rareza", value=self.registry.rarity_names[rarity], inline=True)
        embed.add_field(name="Interpretado por", value=data["interpreter"], inline=True)
        embed.add_field(name="Unidades Poseídas", value=str(unit_count), inline=True)
        embed.add_field(name="Fragmentos", value=f"{shard_count}/{self.registry.shards_per_unit}", inline=True)

        image_path = await get_framed_image_path(unit_id, rarity)
        if image_path:
            filename = os.path.basename(image_path)
            file = discord.File(image_path, filename=filename)
            embed.set_image(url=f"attachment://{filename}")
            await interaction.followup.send(embed=embed, file=file)
        else:
            await interaction.followup.send(embed=embed)

    @gacha_group.command(name="listar", description="Muestra el catálogo completo de personajes registrados en el sistema gacha")
    async def list_units(self, interaction: discord.Interaction):
        all_units = await self.bot.db.gacha_get_all_unit_definitions()
        if not all_units:
            await interaction.response.send_message("⚠️ Todavía no hay personajes registrados en el sistema gacha.", ephemeral=True)
            return

        sorted_units = sorted(all_units.values(), key=lambda d: (-d["rarity"], d["name"]))

        paginator = commands.Paginator(prefix="", suffix="", max_size=1000)
        last_rarity = None
        for data in sorted_units:
            if data["rarity"] != last_rarity:
                if last_rarity is not None:
                    paginator.add_line("")
                paginator.add_line(f"**{self.registry.rarity_names[data['rarity']]}**")
                last_rarity = data["rarity"]
            paginator.add_line(f"{data['emoji']} **{data['name']}** · {data['interpreter']}")

        view = PaginatedEmbedView(
            interaction.user.id,
            title="📖 Catálogo de Personajes Gacha",
            pages=paginator.pages,
            footer_extra=f"{len(all_units)} personajes registrados"
        )
        if len(view.pages) > 1:
            await interaction.response.send_message(embed=view.build_embed(), view=view)
            view.message = await interaction.original_response()
        else:
            await interaction.response.send_message(embed=view.build_embed())

    @gacha_group.command(name="coleccion", description="Muestra tu colección de personajes (unidades) ordenada por rareza")
    @app_commands.describe(usuario="Usuario cuya colección quieres ver (opcional)")
    async def collection(self, interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
        target = usuario or interaction.user
        units_owned = await self.bot.db.gacha_get_units(target.id)
        all_units = await self.bot.db.gacha_get_all_unit_definitions()

        view = CollectionView(interaction.user.id, self.registry, target, units_owned, all_units)
        embed = view.build_summary_embed()
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    @gacha_group.command(name="fragmentos", description="Muestra los fragmentos de personaje que tienes en tu inventario")
    @app_commands.describe(usuario="Usuario cuyo inventario quieres ver (opcional)")
    async def shards_inventory(self, interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
        target = usuario or interaction.user
        shards = await self.bot.db.gacha_get_shards(target.id)
        dust = await self.bot.db.gacha_get_dust(target.id)
        all_units = await self.bot.db.gacha_get_all_unit_definitions()

        if not shards:
            embed = discord.Embed(title=f"🧩 Fragmentos de {target.display_name}", color=discord.Color.blurple())
            embed.add_field(name="💨 Polvo Gacha", value=f"{dust:,}", inline=False)
            embed.add_field(name="Fragmentos", value="*No tienes fragmentos todavía.*", inline=False)
            await interaction.response.send_message(embed=embed)
            return

        units_by_rarity: dict[int, list[str]] = {}
        for unit_id, data in all_units.items():
            units_by_rarity.setdefault(data["rarity"], []).append(unit_id)

        paginator = commands.Paginator(prefix="", suffix="", max_size=1000)
        last_rarity = None
        for rarity in sorted(units_by_rarity.keys(), reverse=True):
            owned = [(u, shards[u]) for u in units_by_rarity[rarity] if u in shards]
            if not owned:
                continue

            owned.sort(key=lambda item: all_units[item[0]]["name"])
            if last_rarity is not None:
                paginator.add_line("")
            paginator.add_line(f"**{self.registry.rarity_names[rarity]}**")
            last_rarity = rarity
            for unit_id, amount in owned:
                paginator.add_line(f"{all_units[unit_id]['emoji']} {all_units[unit_id]['name']} - {amount}/{self.registry.shards_per_unit}")

        view = PaginatedEmbedView(
            interaction.user.id,
            title=f"🧩 Fragmentos de {target.display_name}",
            pages=paginator.pages,
            footer_extra=f"💨 {dust:,} polvo gacha"
        )
        if len(view.pages) > 1:
            await interaction.response.send_message(embed=view.build_embed(), view=view)
            view.message = await interaction.original_response()
        else:
            await interaction.response.send_message(embed=view.build_embed())

    @gacha_group.command(name="ranking", description="Muestra el ranking de nivel gacha o de personajes descubiertos")
    @app_commands.choices(modo=[
        app_commands.Choice(name="Nivel Gacha", value="nivel"),
        app_commands.Choice(name="Personajes Descubiertos (Pokedex)", value="coleccion"),
    ])
    async def ranking(self, interaction: discord.Interaction, modo: app_commands.Choice[str]):
        await interaction.response.defer()

        all_rows = await self.bot.db.gacha_get_all_owned_units()
        all_units = await self.bot.db.gacha_get_all_unit_definitions()
        per_user: dict[int, dict[str, int]] = {}
        for user_id, unit_id, amount in all_rows:
            per_user.setdefault(user_id, {})[unit_id] = amount

        if not per_user:
            await interaction.followup.send("Todavía no hay datos para el ranking.")
            return

        if modo.value == "nivel":
            scored = []
            for user_id, units in per_user.items():
                score = self.registry.compute_score(units, all_units)
                level, _, _ = self.registry.compute_level(score)
                scored.append((user_id, level, score))
            scored.sort(key=lambda x: (-x[1], -x[2]))

            title = "🏆 Ranking - Nivel Gacha"
            rows_display = [(user_id, f"**Nivel {level}** ({score:,} puntos)") for user_id, level, score in scored[:10]]
        else:
            total_units = len(all_units)
            counted = [(user_id, len(units)) for user_id, units in per_user.items()]
            counted.sort(key=lambda x: -x[1])

            title = f"🏆 Ranking - Personajes Descubiertos (de {total_units})"
            rows_display = [(user_id, f"**{count}/{total_units}** personajes") for user_id, count in counted[:10]]

        embed = discord.Embed(title=title, color=discord.Color.gold())
        medals = ["🥇", "🥈", "🥉"]
        description_lines = []

        for idx, (user_id, value_text) in enumerate(rows_display):
            icon = medals[idx] if idx < len(medals) else f"`#{idx + 1}`"
            member = interaction.guild.get_member(user_id) if interaction.guild else None
            user_name = member.mention if member else f"Usuario ({user_id})"
            description_lines.append(f"{icon} {user_name} - {value_text}")

        embed.description = "\n".join(description_lines)
        await interaction.followup.send(embed=embed)


async def setup(bot: JoseLuisBot):
    await bot.add_cog(GachaCog(bot))
