import asyncio
import json
import logging
import sqlite3
import os
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from main import JoseLuisBot

logger = logging.getLogger(__name__)


class StreamerNotifierCog(commands.Cog):
    EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"

    streamer_group = app_commands.Group(
        name="streams",
        description="Gestión de notificaciones de directos"
    )

    def __init__(self, bot: JoseLuisBot, db_path: str = "bot_data.db"):
        self.bot = bot
        self.db_path = db_path

        self.client_id = self.bot.twitchClient
        self.client_secret = self.bot.twitchSecret
        self.tokens_file = "twitch_tokens.json"

        self.access_token: str = ""
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws_task: Optional[asyncio.Task] = None
        self.active_session_id: Optional[str] = None

        self._init_sqlite()

    def _init_sqlite(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                           CREATE TABLE IF NOT EXISTS tracked_streamers
                           (
                               id              INTEGER PRIMARY KEY AUTOINCREMENT,
                               guild_id        INTEGER NOT NULL,
                               channel_id      INTEGER NOT NULL,
                               twitch_username TEXT    NOT NULL,
                               kick_username   TEXT,
                               everyone        BOOL,
                               UNIQUE (guild_id, twitch_username)
                           )
                           """)
            conn.commit()

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        self.ws_task = asyncio.create_task(self._eventsub_listener_loop())

    async def cog_unload(self):
        if self.ws_task:
            self.ws_task.cancel()
        if self.session and not self.session.closed:
            await self.session.close()

    async def _get_user_access_token(self) -> str:
        if not os.path.exists(self.tokens_file):
            logger.error(f"¡Falta {self.tokens_file}! Ejecuta el script de autorización primero.")
            return ""

        with open(self.tokens_file, "r") as f:
            token_data = json.load(f)

        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            logger.error("No se encontró refresh_token en twitch_tokens.json")
            return ""

        url = "https://id.twitch.tv/oauth2/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        async with self.session.post(url, data=payload) as resp:
            if resp.status == 200:
                new_tokens = await resp.json()

                if "refresh_token" not in new_tokens:
                    new_tokens["refresh_token"] = refresh_token

                with open(self.tokens_file, "w") as f:
                    json.dump(new_tokens, f, indent=2)

                self.access_token = new_tokens["access_token"]
                logger.info("Twitch User Access Token renovado con éxito.")
                return self.access_token
            else:
                body = await resp.text()
                logger.error(f"Fallo al renovar User Access Token ({resp.status}): {body}")
                self.access_token = token_data.get("access_token", "")
                return self.access_token

    async def _get_broadcaster_id(self, username: str) -> Optional[str]:
        if not self.access_token:
            await self._get_user_access_token()

        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self.access_token}",
        }
        url = f"https://api.twitch.tv/helix/users?login={username}"
        async with self.session.get(url, headers=headers) as resp:
            if resp.status == 401:
                await self._get_user_access_token()
                return await self._get_broadcaster_id(username)

            data = await resp.json()
            if data.get("data"):
                return data["data"][0]["id"]
            return None

    async def _subscribe_to_streamer(self, broadcaster_id: str, session_id: str) -> bool:
        if not self.access_token:
            await self._get_user_access_token()

        url = "https://api.twitch.tv/helix/eventsub/subscriptions"
        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "type": "stream.online",
            "version": "1",
            "condition": {"broadcaster_user_id": str(broadcaster_id)},
            "transport": {
                "method": "websocket",
                "session_id": str(session_id)
            },
        }

        async with self.session.post(url, headers=headers, json=payload) as resp:
            if resp.status == 401:
                logger.warning("Token no autorizado (401) en EventSub. Renovando token...")
                await self._get_user_access_token()
                headers["Authorization"] = f"Bearer {self.access_token}"

                async with self.session.post(url, headers=headers, json=payload) as retry_resp:
                    if retry_resp.status in (200, 202):
                        logger.info(f"Suscrito exitosamente al broadcaster ID {broadcaster_id} (tras reintento)")
                        return True
                    else:
                        body = await retry_resp.text()
                        logger.error(
                            f"Fallo de suscripción EventSub tras reintento para ID {broadcaster_id}: {retry_resp.status} - {body}")
                        return False

            body = await resp.text()
            if resp.status in (200, 202):
                logger.info(f"Suscrito exitosamente al broadcaster ID {broadcaster_id}")
                return True
            else:
                logger.error(f"Fallo de suscripción EventSub para ID {broadcaster_id}: {resp.status} - {body}")
                return False

    async def sync_all_subscriptions(self, session_id: str):
        self.active_session_id = session_id

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT twitch_username FROM tracked_streamers")
            rows = cursor.fetchall()

        for (twitch_user,) in rows:
            broadcaster_id = await self._get_broadcaster_id(twitch_user)
            if broadcaster_id:
                await self._subscribe_to_streamer(broadcaster_id, session_id)

    async def _eventsub_listener_loop(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            self.active_session_id = None
            try:
                await self._get_user_access_token()

                async with self.session.ws_connect(self.EVENTSUB_WS_URL) as ws:
                    logger.info("Conectado a Twitch EventSub WebSocket")

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            message_type = data["metadata"]["message_type"]

                            if message_type == "session_welcome":
                                session_id = data["payload"]["session"]["id"]
                                logger.info(f"EventSub session welcome recibido. Session ID: {session_id}")
                                await self.sync_all_subscriptions(session_id)

                            elif message_type == "notification":
                                event_type = data["metadata"]["subscription_type"]
                                if event_type == "stream.online":
                                    await self._dispatch_stream_alert(data["payload"]["event"])

                            elif message_type == "session_keepalive":
                                continue

                            elif message_type == "session_reconnect":
                                reconnect_url = data["payload"]["session"]["reconnect_url"]
                                logger.info(f"EventSub solicitó reconexión a {reconnect_url}")
                                break

                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logger.warning("EventSub WebSocket cerrado o encontró un error")
                            break

            except Exception as e:
                logger.error(f"Error en Twitch EventSub: {e}. Reconectando en 15 segundos...")
                await asyncio.sleep(15)

    async def _dispatch_stream_alert(self, event_data: dict):
        twitch_user = event_data.get("broadcaster_user_login", "").lower()
        streamer_name = event_data.get("broadcaster_user_name", twitch_user)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT channel_id, kick_username, everyone FROM tracked_streamers WHERE twitch_username = ?", (twitch_user,))
            destinations = cursor.fetchall()

        if not destinations:
            return

        twitch_url = f"https://twitch.tv/{twitch_user}"

        for channel_id, kick_user, everyone in destinations:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue

            kick_url = f"https://kick.com/{kick_user}" if kick_user else None

            embed = discord.Embed(
                title=f"🔴 ¡{streamer_name} está en directo!",
                url=twitch_url,
                color=0x9146FF
            )
            embed.add_field(name="Twitch", value=f"[Ver en Twitch]({twitch_url})", inline=True)

            if kick_url:
                embed.add_field(name="Kick", value=f"[Ver en Kick]({kick_url})", inline=True)

            if everyone:
                at_everyone = "@everyone "
            else:
                at_everyone = ""

            content = f"{at_everyone}¡Atención! {streamer_name} ha iniciado directo: {twitch_url}"
            if kick_url:
                content += f" (También en Kick: {kick_url})"

            await channel.send(content=content, embed=embed)

    @streamer_group.command(name="agregar", description="Añade un streamer para notificar en este canal")
    async def add_streamer(self, interaction: discord.Interaction, twitch: str, kick: Optional[str] = None, canal: Optional[discord.TextChannel] = None, at_everyone: bool = False):
        if await self.bot.filter_operators(interaction):
            return

        target_channel = canal or interaction.channel
        twitch_user = twitch.strip().lower()
        kick_user = kick.strip().lower() if kick else None

        broadcaster_id = await self._get_broadcaster_id(twitch_user)
        if not broadcaster_id:
            await interaction.response.send_message(f"No se pudo encontrar al usuario `{twitch_user}` en Twitch.", ephemeral=True)
            return

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                           INSERT INTO tracked_streamers (guild_id, channel_id, twitch_username, kick_username, everyone)
                           VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT(guild_id, twitch_username) DO UPDATE SET channel_id    = excluded.channel_id,
                                                                                kick_username = excluded.kick_username
                           """, (interaction.guild_id, target_channel.id, twitch_user, kick_user, at_everyone))
            conn.commit()

        sub_success = True
        if self.active_session_id:
            sub_success = await self._subscribe_to_streamer(broadcaster_id, self.active_session_id)

        if sub_success:
            msg = f"Notificaciones activadas para **{twitch_user}** en {target_channel.mention}."
            if kick_user:
                msg += f" (Enlace de Kick: https://kick.com/{kick_user})"
        else:
            msg = f"⚠️ Guardado **{twitch_user}**, pero falló la suscripción EventSub. Se reintentará al reconectar."

        await interaction.response.send_message(msg, ephemeral=True)

    @streamer_group.command(name="quitar", description="Elimina un streamer de las notificaciones")
    async def remove_streamer(self, interaction: discord.Interaction, twitch: str):
        if await self.bot.filter_operators(interaction):
            return

        twitch_user = twitch.strip().lower()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tracked_streamers WHERE guild_id = ? AND twitch_username = ?", (interaction.guild_id, twitch_user))
            conn.commit()

        await interaction.response.send_message(f"Notificaciones desactivadas para **{twitch_user}**.", ephemeral=True)

    @streamer_group.command(name="lista", description="Muestra los streamers configurados")
    async def list_streamers(self, interaction: discord.Interaction):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT twitch_username, kick_username, channel_id FROM tracked_streamers WHERE guild_id = ?", (interaction.guild_id,))
            rows = cursor.fetchall()

        if not rows:
            await interaction.response.send_message("No hay streamers configurados en este servidor.", ephemeral=True)
            return

        embed = discord.Embed(title="📺 Streamers Monitorizados", color=0x9146FF)
        for twitch, kick, ch_id in rows:
            links = f"[Twitch](https://twitch.tv/{twitch})"
            if kick:
                links += f" | [Kick](https://kick.com/{kick})"
            embed.add_field(name=f"• {twitch}", value=f"Canal: <#{ch_id}>\nLinks: {links}", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: JoseLuisBot):
    await bot.add_cog(StreamerNotifierCog(bot))