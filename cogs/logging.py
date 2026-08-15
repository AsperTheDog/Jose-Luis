import json
import os
from typing import Dict, Optional, Any
import discord
from discord import app_commands, DMChannel
from discord.ext import commands

from main import ScalableBot

CONFIG_FILE = "logging_config.json"


class LoggingCog(commands.Cog):
    logging_group = app_commands.Group(
        name="logging",
        description="Herramientas para configurar logs"
    )

    def __init__(self, bot: ScalableBot):
        self.bot = bot
        self.config: Dict[str, Dict[str, Any]] = self._load_config()

    def _load_config(self) -> Dict[str, Dict[str, Any]]:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_config(self) -> None:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=4)

    def _get_guild_config(self, guild_id: int) -> Dict[str, Any]:
        gid = str(guild_id)
        if gid not in self.config:
            self.config[gid] = {
                "log_channel_id": None,
                "events": {
                    "messages": True,
                    "members": True,
                    "moderation": True,
                    "channels": True,
                },
            }
            self._save_config()
        return self.config[gid]

    def _get_log_channel(self, guild: discord.Guild, category: str) -> Optional[discord.TextChannel]:
        cfg = self._get_guild_config(guild.id)
        channel_id = cfg.get("log_channel_id")

        if not channel_id:
            return None

        if not cfg.get("events", {}).get(category, True):
            return None

        return guild.get_channel(channel_id)

    @logging_group.command(name="activarlog", description="Pone el canal actual como canal de logs")
    async def set_log_channel(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        cfg = self._get_guild_config(interaction.guild.id)
        cfg["log_channel_id"] = interaction.channel_id
        self._save_config()

        embed = discord.Embed(
            title="Logging activado",
            description=f"Este canal ({interaction.channel.mention}) recibirá actualizaciones de la actividad del servidor.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @logging_group.command(name="desactivarlog", description="Desactiva el logging en el server")
    async def disable_logging(self, interaction: discord.Interaction):
        if await self.bot.filter_operators(interaction): return

        cfg = self._get_guild_config(interaction.guild_id)
        cfg["log_channel_id"] = None
        self._save_config()

        embed = discord.Embed(
            title="Logging desactivado",
            description="Ya no haré seguimiento de la actividad del servidor",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @logging_group.command(name="configurarlog", description="Configura los eventos que se van a logear")
    async def toggle_log_events(self, interaction: discord.Interaction, messages: bool = True, members: bool = True, moderation: bool = True, channels: bool = True):
        if await self.bot.filter_operators(interaction): return

        cfg = self._get_guild_config(interaction.guild.id)
        events = cfg["events"]
        events["messages"] = messages
        events["members"] = members
        events["moderation"] = moderation
        events["channels"] = channels

        self._save_config()

        embed = discord.Embed(title="Actualizada configuración de logs", color=discord.Color.blue())
        for cat, enabled in events.items():
            status = "Enabled" if enabled else "Disabled"
            embed.add_field(name=cat.capitalize(), value=f"`{status}`", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return

        channel = self._get_log_channel(message.guild, "messages")
        if not channel:
            return

        embed = discord.Embed(
            title="Mensaje eliminado",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=f"{message.author}", icon_url=message.author.display_avatar.url)
        embed.add_field(name="Canal", value=message.channel.mention, inline=True)
        embed.add_field(name="Contenido", value=message.content or "*Sin texto*", inline=False)
        embed.set_footer(text=f"ID del usuario: {message.author.id}")

        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.content == after.content:
            return

        channel = self._get_log_channel(before.guild, "messages")
        if not channel or channel is DMChannel:
            return

        embed = discord.Embed(
            title="Mensaje editado",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=f"{before.author}", icon_url=before.author.display_avatar.url)
        embed.add_field(name="Canal", value=before.channel.mention, inline=False)
        embed.add_field(name="Antes", value=before.content or "*Empty*", inline=False)
        embed.add_field(name="Después", value=after.content or "*Empty*", inline=False)
        embed.add_field(name="Link al mensaje", value=f"[Click Here]({after.jump_url})", inline=False)
        embed.set_footer(text=f"ID del usuario: {before.author.id}")

        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        channel = self._get_log_channel(member.guild, "members")
        if not channel:
            return

        embed = discord.Embed(
            title="Member Joined",
            description=f"{member.mention} ({member}) joined the server.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Account Created",
            value=f"<t:{int(member.created_at.timestamp())}:R>",
            inline=True,
        )
        embed.set_footer(text=f"User ID: {member.id}")

        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild

        log_channel_mod = self._get_log_channel(guild, "moderation")
        was_kicked = False

        if log_channel_mod:
            try:
                async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
                    if entry.target.id == member.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        was_kicked = True
                        embed = discord.Embed(
                            title="Miembro expulsado",
                            color=discord.Color.dark_orange(),
                            timestamp=discord.utils.utcnow(),
                        )
                        embed.set_thumbnail(url=member.display_avatar.url)
                        embed.add_field(name="Miembro", value=f"{member} ({member.id})", inline=False)
                        embed.add_field(name="Expulsado por", value=entry.user.mention, inline=True)
                        embed.add_field(name="Razón", value=entry.reason or "Sin razón", inline=True)
                        await log_channel_mod.send(embed=embed)
                        break
            except discord.Forbidden:
                pass

        if not was_kicked:
            channel_mem = self._get_log_channel(guild, "members")
            if channel_mem:
                embed = discord.Embed(
                    title="Miembro se ha ido",
                    description=f"{member} se fue del servidor.",
                    color=discord.Color.dark_grey(),
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=f"ID del usuario: {member.id}")
                await channel_mem.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = before.guild

        channel_mod = self._get_log_channel(guild, "moderation")
        if channel_mod:
            if before.timed_out_until != after.timed_out_until:
                embed = discord.Embed(timestamp=discord.utils.utcnow())
                embed.set_author(name=f"{after}", icon_url=after.display_avatar.url)

                if after.timed_out_until:
                    embed.title = "Miembro muteado"
                    embed.color = discord.Color.orange()
                    embed.add_field(
                        name="Hasta",
                        value=f"<t:{int(after.timed_out_until.timestamp())}:F>",
                        inline=False,
                    )
                else:
                    embed.title = "Miembro desmuteado"
                    embed.color = discord.Color.blue()

                embed.set_footer(text=f"ID del usuario: {after.id}")
                await channel_mod.send(embed=embed)

        channel_mem = self._get_log_channel(guild, "members")
        if channel_mem and before.roles != after.roles:
            added_roles = [r.mention for r in after.roles if r not in before.roles]
            removed_roles = [r.mention for r in before.roles if r not in after.roles]

            if added_roles or removed_roles:
                embed = discord.Embed(
                    title="Actualizados roles de miembro",
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_author(name=f"{after}", icon_url=after.display_avatar.url)
                if added_roles:
                    embed.add_field(name="Roles añadidos", value=", ".join(added_roles), inline=False)
                if removed_roles:
                    embed.add_field(name="Roles eliminados", value=", ".join(removed_roles), inline=False)
                embed.set_footer(text=f"ID del usuario: {after.id}")
                await channel_mem.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        channel = self._get_log_channel(guild, "moderation")
        if not channel:
            return

        reason = "Sin razón"
        banned_by = "Desconocido"

        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    banned_by = entry.user.mention
                    reason = entry.reason or reason
                    break
        except discord.Forbidden:
            pass

        embed = discord.Embed(
            title="Miembro Baneado",
            color=discord.Color.dark_red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Miembro", value=f"{user} ({user.id})", inline=False)
        embed.add_field(name="Baneado por", value=banned_by, inline=True)
        embed.add_field(name="Razón", value=reason, inline=True)

        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        channel = self._get_log_channel(guild, "moderation")
        if not channel:
            return

        embed = discord.Embed(
            title="Miembro desbaneado",
            description=f"{user} ({user.id}) ya no está baneado.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        log_chan = self._get_log_channel(channel.guild, "channels")
        if not log_chan:
            return

        embed = discord.Embed(
            title="Canal creado",
            description=f"Canal {channel.mention} (`{channel.name}`) ha sido creado.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Tipo de canal: ", value=str(channel.type).capitalize(), inline=True)
        await log_chan.send(embed=embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        log_chan = self._get_log_channel(channel.guild, "channels")
        if not log_chan:
            return

        embed = discord.Embed(
            title="Canal eliminado",
            description=f"El canal **#{channel.name}** ya no existe.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Tipo de canal", value=str(channel.type).capitalize(), inline=True)
        await log_chan.send(embed=embed)


async def setup(bot: ScalableBot):
    await bot.add_cog(LoggingCog(bot))