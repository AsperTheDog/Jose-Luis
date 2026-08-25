import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

from main import JoseLuisBot


GIFTS_CATALOG = {
    "chocolate": {"name": "Caja de Chocolates", "value": 500, "emoji": "🍫"},
    "flores": {"name": "Ramo de Rosas", "value": 1000, "emoji": "🌹"},
    "peluche": {"name": "Oso de Peluche gigante", "value": 5000, "emoji": "🧸"},
    "anillo": {"name": "Anillo de Compromiso", "value": 10000, "emoji": "💍"},
    "coche": {"name": "Deportivo de Lujo", "value": 50000, "emoji": "🏎️"},
    "mansion": {"name": "Mansión Privada", "value": 100000, "emoji": "🏰"},
    "luna": {"name": "La Luna", "value": 200000, "emoji": "🌕"},
    "planeta": {"name": "Un Planeta Habitable", "value": 500000, "emoji": "🪐"},
}


class GiftQuantityModal(discord.ui.Modal):
    def __init__(self, bot, giver_id: int, target_member: discord.Member, gift_id: str, gift_data: dict):
        super().__init__(title="🎁 Comprar Regalo")
        self.bot = bot
        self.giver_id = giver_id
        self.target_member = target_member
        self.gift_id = gift_id
        self.gift_data = gift_data

        self.amount_input = discord.ui.TextInput(
            label=f"¿Cuántos '{gift_data['name']}' enviar?",
            placeholder="Introduce un número entero (mínimo 1)...",
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

        unit_value = self.gift_data["value"]
        total_cost = unit_value * amount

        balance = await self.bot.db.economy_get_balance(self.giver_id)
        if balance < total_cost:
            await interaction.followup.edit_message(
                message_id=interaction.message.id,
                content=f"❌ No tienes suficientes Choskris. **Total:** {total_cost} Choskris | **Tu saldo:** {balance} Choskris.",
                embed=None,
                view=None,
            )
            return

        await self.bot.db.economy_update_balance(self.giver_id, -total_cost)
        await self.bot.db.waifu_add_gift(
            waifu_id=self.target_member.id,
            item_name=self.gift_data["name"],
            cost_per_unit=unit_value,
            amount=amount
        )

        msg = (
            f"🎁 ¡**{interaction.user.display_name}** le ha regalado **{amount}x {self.gift_data['name']}** {self.gift_data['emoji']} "
            f"a **{self.target_member.display_name}** por **{total_cost} Choskris**!\n"
            f"📈 El valor base de **{self.target_member.display_name}** ha aumentado en **+{total_cost} Choskris**."
        )

        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            content=msg,
            embed=None,
            view=None,
        )


class GiftSelectView(discord.ui.View):
    def __init__(self, bot, giver_id: int, target_member: discord.Member, catalog: dict):
        super().__init__(timeout=60.0)
        self.bot = bot
        self.giver_id = giver_id
        self.target_member = target_member
        self.catalog = catalog
        self.message = None

        options = []
        for g_id, g_data in self.catalog.items():
            options.append(
                discord.SelectOption(
                    label=g_data["name"][:100],
                    value=g_id,
                    description=f"Precio unitario: {g_data['value']} Choskris"[:100],
                    emoji=g_data.get("emoji"),
                )
            )

        self.gift_select = discord.ui.Select(
            placeholder="Selecciona el regalo a enviar...",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.gift_select.callback = self.select_callback
        self.add_item(self.gift_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.giver_id:
            await interaction.response.send_message("No puedes interactuar con la tienda de otra persona.", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction: discord.Interaction):
        gift_id = self.gift_select.values[0]
        gift_data = self.catalog[gift_id]

        modal = GiftQuantityModal(
            bot=self.bot,
            giver_id=self.giver_id,
            target_member=self.target_member,
            gift_id=gift_id,
            gift_data=gift_data,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Compra cancelada.", embed=None, view=None)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception:
            pass


class WaifuCog(commands.Cog):
    def __init__(self, bot: JoseLuisBot):
        self.bot = bot

    waifu_group = app_commands.Group(name="waifu", description="Comandos del sistema de waifus/husbandos y reclamos")

    @waifu_group.command(name="reclamar", description="Reclama a un usuario como tu waifu/husbando usando Choskris.")
    async def claim(self, interaction: discord.Interaction, usuario: discord.Member):
        claimer_id = interaction.user.id
        target_id = usuario.id

        if claimer_id == target_id:
            await interaction.response.send_message("No puedes reclamarte a ti mismo/a.", ephemeral=True)
            return

        if usuario.bot:
            await interaction.response.send_message("No puedes reclamar a un bot.", ephemeral=True)
            return

        claimer_data = await self.bot.db.waifu_get_user(claimer_id)
        if claimer_data.get("claim") is not None:
            claimed_user = self.bot.get_user(claimer_data["claim"])
            name = claimed_user.display_name if claimed_user else f"ID {claimer_data['claim']}"
            await interaction.response.send_message(f"⚠️ Ya tienes reclamado a **{name}**. Debes usar `/waifu divorcio` antes de reclamar a alguien más.", ephemeral=True)
            return

        if await self.bot.db.waifu_is_blocked(blocker_id=target_id, blocked_id=claimer_id):
            await interaction.response.send_message(f"❌ **{usuario.display_name}** te ha bloqueado. No puedes reclamarle/a hasta que te desbloquee.", ephemeral=True)
            return

        target_data = await self.bot.db.waifu_get_user(target_id)
        cost, is_affinity = await self.bot.db.waifu_get_effective_value(target_id)

        balance = await self.bot.db.economy_get_balance(claimer_id)
        if balance < cost:
            await interaction.response.send_message(
                f"❌ No tienes suficientes Choskris para reclamar a **{usuario.display_name}**.\n"
                f"💰 **Precio:** {cost} Choskris | **Tu saldo:** {balance} Choskris.",
                ephemeral=True
            )
            return

        will_trigger_affinity = target_data.get("claim") == claimer_id
        previous_owner = await self.bot.db.waifu_get_owner(target_id)

        await self.bot.db.economy_update_balance(claimer_id, -cost)

        new_value = int(target_data["value"] * 1.2)
        await self.bot.db.waifu_claim_target(claimer_id, target_id, new_value)

        pronoun = target_data.get("pronoun", "waifu")
        msg = f"💖 ¡Has reclamado a **{usuario.display_name}** como tu **{pronoun}** por **{cost} Choskris**!"

        if previous_owner and previous_owner["user_id"] != claimer_id:
            old_owner_user = self.bot.get_user(previous_owner["user_id"])
            old_owner_name = old_owner_user.display_name if old_owner_user else f"ID {previous_owner['user_id']}"
            msg += f"\n🔥 ¡Se lo has robado a **{old_owner_name}**!"

        if is_affinity:
            msg += f"\n⚡ **Efecto pagado:** ¡Esta persona tenía la **Afinidad activa**, por lo que pagaste el doble ({cost} Choskris)!"

        if will_trigger_affinity:
            msg += f"\n✨ **¡AFINIDAD ACTIVADA!** Como **{usuario.display_name}** ya te había reclamado previamente, ¡ahora ambos se reclaman mutuamente y sus valores se han DUPLICADO!"

        msg += f"\n📈 El valor base de **{usuario.display_name}** ha aumentado a **{new_value} Choskris**."

        embed = discord.Embed(
            title="💍 ¡Nuevo Reclamo Exitoso!",
            description=msg,
            color=discord.Color.pink()
        )
        await interaction.response.send_message(embed=embed)

    @waifu_group.command(name="divorcio", description="Te divorcias de la waifu/husbando que tienes actualmente reclamado/a.")
    async def divorce(self, interaction: discord.Interaction):
        claimer_id = interaction.user.id
        claimer_data = await self.bot.db.waifu_get_user(claimer_id)

        target_id = claimer_data.get("claim")
        if not target_id:
            await interaction.response.send_message("❌ No tienes reclamado/a a nadie actualmente.", ephemeral=True)
            return

        target_user = self.bot.get_user(target_id)
        target_name = target_user.display_name if target_user else f"ID {target_id}"

        had_affinity = await self.bot.db.waifu_is_affinity_active(claimer_id, target_id)
        await self.bot.db.waifu_divorce(claimer_id)

        msg = f"💔 Te has divorciado de **{target_name}**. Ahora ambos están libres para ser reclamados."
        if had_affinity:
            msg += "\n💔 La **Afinidad** entre ambos se ha roto y sus valores han vuelto a la normalidad."

        await interaction.response.send_message(msg)

    @waifu_group.command(name="liberarse", description="Fuerzas tu propia liberación pagando tu valor actual.")
    async def unclaim(self, interaction: discord.Interaction):
        waifu_id = interaction.user.id
        owner_data = await self.bot.db.waifu_get_owner(waifu_id)

        if not owner_data:
            await interaction.response.send_message("Nadie te ha reclamado actualmente.", ephemeral=True)
            return

        owner_id = owner_data["user_id"]
        cost, had_affinity = await self.bot.db.waifu_get_effective_value(waifu_id, True)

        balance = await self.bot.db.economy_get_balance(waifu_id)
        if balance < cost:
            await interaction.response.send_message(
                f"No tienes suficientes Choskris para liberarte.\n"
                f"💰 **Coste de liberación:** {cost:,} Choskris | **Tu saldo:** {balance:,} Choskris.",
                ephemeral=True
            )
            return

        await self.bot.db.economy_update_balance(waifu_id, -cost)
        await self.bot.db.waifu_force_unclaim(waifu_id, owner_id)

        owner_user = self.bot.get_user(owner_id)
        owner_name = owner_user.display_name if owner_user else f"ID {owner_id}"

        msg = (
            f"🔓 **¡Te has liberado exitosamente!**\n"
            f"- Has pagado **{cost:,} Choskris** para desmarcarte de **{owner_name}**.\n"
            f"- **{owner_name}** ha sido bloqueado/a automáticamente y no podrá volver a reclamarte hasta que lo/a desbloquees con `/waifu desbloquear`."
        )

        if had_affinity:
            msg += "\n💔 La **Afinidad** con tu antiguo dueño se ha roto."

        await interaction.response.send_message(msg)

    @waifu_group.command(name="bloquear", description="Bloquea a un usuario preventivamente para que no pueda reclamarte.")
    async def block(self, interaction: discord.Interaction, usuario: discord.Member):
        if usuario.id == interaction.user.id:
            await interaction.response.send_message("No puedes bloquearte a ti mismo/a.", ephemeral=True)
            return

        await self.bot.db.waifu_add_block(interaction.user.id, usuario.id)
        await interaction.response.send_message(f"🚫 Has bloqueado a **{usuario.display_name}**. Ya no podrá reclamarte.", ephemeral=True)

    @waifu_group.command(name="desbloquear", description="Desbloquea a un usuario para permitirle que pueda reclamarte.")
    async def unblock(self, interaction: discord.Interaction, usuario: discord.Member):
        unblocked = await self.bot.db.waifu_remove_block(interaction.user.id, usuario.id)

        if unblocked:
            await interaction.response.send_message(f"✅ Has desbloqueado a **{usuario.display_name}**. Ahora puede volver a reclamarte.", ephemeral=True)
        else:
            await interaction.response.send_message("Ese usuario no estaba en tu lista de bloqueados.", ephemeral=True)

    @waifu_group.command(name="regalar", description="Muestra la tienda de regalos para enviarle a una waifu/husbando.")
    async def gift(self, interaction: discord.Interaction):
        await interaction.response.defer()

        owner_data = await self.bot.db.waifu_get_user(interaction.user.id)
        if not owner_data or not owner_data.get("claim"):
            await interaction.response.send_message("No has reclamado a nadie aún, debes tener a alguien reclamado para poder regalar", ephemeral=True)
            return

        user = await interaction.guild.fetch_member(owner_data["claim"])

        embed = discord.Embed(
            title=f"🎁 Tienda de Regalos para {user.display_name}",
            description="Selecciona el regalo que deseas enviar en el menú desplegable.",
            color=discord.Color.gold(),
        )

        for g_id, g_data in GIFTS_CATALOG.items():
            embed.add_field(
                name=f"{g_data['emoji']} {g_data['name']}",
                value=f"Coste: **{g_data['value']:,}** Choskris",
                inline=False,
            )

        view = GiftSelectView(
            bot=self.bot,
            giver_id=interaction.user.id,
            target_member=user,
            catalog=GIFTS_CATALOG,
        )

        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg

    @waifu_group.command(name="pronombre", description="Configura si prefieres identificarte como waifu o husbando.")
    @app_commands.choices(opcion=[
        app_commands.Choice(name="Waifu", value="waifu"),
        app_commands.Choice(name="Husbando", value="husbando")
    ])
    async def set_pronoun(self, interaction: discord.Interaction, opcion: app_commands.Choice[str]):
        await self.bot.db.waifu_set_pronoun(interaction.user.id, opcion.value)
        await interaction.response.send_message(f"👤 Tu identidad se ha actualizado a: **{opcion.name}**.", ephemeral=True)

    @waifu_group.command(name="perfil", description="Muestra el perfil detallado de waifu/husbando de un usuario.")
    async def profile(self, interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
        target = usuario or interaction.user
        target_id = target.id

        u_data = await self.bot.db.waifu_get_user(target_id)

        pronoun_raw = u_data.get("pronoun", "waifu")
        pronoun_label = "Waifu 🌸" if pronoun_raw == "waifu" else "Husbando 🕺"

        base_value = u_data["value"]
        effective_value, is_affinity = await self.bot.db.waifu_get_effective_value(target_id)

        claimed_id = u_data.get("claim")
        claimed_str = "*Nadie*"
        if claimed_id:
            claimed_user = self.bot.get_user(claimed_id)
            claimed_str = f"💖 *{claimed_user.mention}*"

        owner_data = await self.bot.db.waifu_get_owner(target_id)
        owner_str = "*Nadie (Libre)*"
        if owner_data:
            owner_user = self.bot.get_user(owner_data["user_id"])
            owner_str = f"👑 *{owner_user.mention}*"

        gifts = await self.bot.db.waifu_get_gifts(target_id)
        if gifts:
            gifts_formatted = [f"• **{item}**: x{amount}" for item, amount in gifts]
            gifts_str = "\n".join(gifts_formatted)
        else:
            gifts_str = "*Sin regalos aún*"

        embed = discord.Embed(
            title=f"✨ Perfil de {target.display_name}",
            description=f"**Rol Identificado:** {pronoun_label}",
            color=discord.Color.magenta())

        avatar_url = target.display_avatar.url
        embed.set_thumbnail(url=avatar_url)

        affinity_tag = " 🔥 **[Afinidad Activa 2x]**" if is_affinity else ""
        embed.add_field(name="📊 Estado de Mercado",
            value=(
                f"🏷️ *Valor Base:* `{base_value:,}` Choskris\n"
                f"💎 *Valor de Reclamo:* `{effective_value:,}` Choskris{affinity_tag}\n"
            ), inline=False)

        embed.add_field(name="💍 Relaciones",
            value=(
                f"👤 *Dueño/a actual:* {owner_str}\n"
                f"👤 *Reclamo actual:* {claimed_str}"
            ), inline=False)

        embed.add_field(name="🎁 Inventario de Regalos Recibidos", value=gifts_str, inline=False)

        await interaction.response.send_message(embed=embed)

    @waifu_group.command(name="top", description="Muestra la clasificación de las waifus y husbandos de mayor valor.")
    async def top(self, interaction: discord.Interaction):
        await interaction.response.defer()

        top_users = await self.bot.db.waifu_get_top_users(limit=10)

        if not top_users:
            await interaction.followup.send("🏆 Aún no hay registrado ningún usuario en el sistema de waifus.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🏆 Clasificación de Waifus & Husbandos",
            color=discord.Color.gold()
        )

        medals = ["🥇", "🥈", "🥉"]
        ranking_lines = []

        for index, u_data in enumerate(top_users, start=1):
            user_id = u_data["user_id"]
            user = self.bot.get_user(user_id)
            user_name = user.display_name if user else f"Usuario ({user_id})"

            medal = medals[index - 1] if index <= 3 else f"`#{index}`"
            pronoun_emoji = "🌸" if u_data["pronoun"] == "waifu" else "🕺"
            affinity_tag = " 🔥" if u_data["is_affinity"] else ""

            value_formatted = f"{u_data['effective_value']:,}".replace(",", ".")

            line = f"{medal} {pronoun_emoji} **{user_name}** - **{value_formatted}** Choskris{affinity_tag}"
            ranking_lines.append(line)

        embed.add_field(
            name="",
            value="\n".join(ranking_lines),
            inline=False
        )

        await interaction.followup.send(embed=embed)


async def setup(bot: JoseLuisBot):
    await bot.add_cog(WaifuCog(bot))