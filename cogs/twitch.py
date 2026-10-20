import asyncio
import json
import os
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from error_reporting import describe_arguments
from main import JoseLuisBot


class TwitchAPIError(Exception):
    def __init__(self, action: str, status: Optional[int], body: str):
        self.action = action
        self.status = status
        self.body = body
        status_text = f"HTTP {status}" if status is not None else "sin respuesta"
        super().__init__(f"Fallo al {action} ({status_text}): {body}")


class StreamerNotifierCog(commands.Cog):
    EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"

    streamer_group = app_commands.Group(
        name="streams",
        description="Gestión de notificaciones de directos"
    )

    def __init__(self, bot: JoseLuisBot):
        self.bot = bot

        self.client_id = self.bot.twitch_client
        self.client_secret = self.bot.twitch_secret
        self.tokens_file = "twitch_tokens.json"

        self.access_token: str = ""
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws_task: Optional[asyncio.Task] = None
        self.active_session_id: Optional[str] = None
        self.last_reported_error: Optional[str] = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        self.ws_task = asyncio.create_task(self._eventsub_listener_loop())

    async def cog_unload(self):
        if self.ws_task:
            self.ws_task.cancel()
        if self.session and not self.session.closed:
            await self.session.close()

    async def _report_background_error(self, error: BaseException, task_name: str) -> None:
        key = f"{type(error).__name__}: {error}"
        if key == self.last_reported_error:
            return
        self.last_reported_error = key

        guild_ids = await self.bot.db.twitch.get_tracked_guild_ids()
        reported = False
        for guild_id in guild_ids:
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            await self.bot.report_exception(
                error,
                source="tarea en segundo plano",
                command_name=task_name,
                guild=guild,
                user=None,
                channel=None,
            )
            reported = True

        if not reported:
            await self.bot.report_exception(
                error,
                source="tarea en segundo plano",
                command_name=task_name,
                guild=None,
                user=None,
                channel=None,
            )

    async def _get_user_access_token(self) -> str:
        if not os.path.exists(self.tokens_file):
            raise TwitchAPIError("leer los tokens de Twitch", None, f"Falta {self.tokens_file}")

        with open(self.tokens_file, "r") as f:
            token_data = json.load(f)

        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            raise TwitchAPIError("leer los tokens de Twitch", None, "No se encontró refresh_token en twitch_tokens.json")

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
                print("Twitch User Access Token renovado con éxito.")
                return self.access_token

            body = await resp.text()
            self.access_token = token_data.get("access_token", "")
            await self._report_background_error(TwitchAPIError("renovar el User Access Token", resp.status, body), "twitch renovar token")
            return self.access_token

    async def _get_broadcaster_id(self, username: str, retried: bool = False) -> Optional[str]:
        if not self.access_token:
            await self._get_user_access_token()

        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self.access_token}",
        }
        url = f"https://api.twitch.tv/helix/users?login={username}"
        async with self.session.get(url, headers=headers) as resp:
            if resp.status == 401 and not retried:
                await self._get_user_access_token()
                return await self._get_broadcaster_id(username, retried=True)

            if resp.status != 200:
                raise TwitchAPIError(f"buscar al usuario {username}", resp.status, await resp.text())

            data = await resp.json()
            if data.get("data"):
                return data["data"][0]["id"]
            return None

    async def _subscribe_to_streamer(self, broadcaster_id: str, session_id: str) -> None:
        if not self.access_token:
            await self._get_user_access_token()

        url = "https://api.twitch.tv/helix/eventsub/subscriptions"
        payload = {
            "type": "stream.online",
            "version": "1",
            "condition": {"broadcaster_user_id": str(broadcaster_id)},
            "transport": {
                "method": "websocket",
                "session_id": str(session_id)
            },
        }

        for attempt in range(2):
            headers = {
                "Client-ID": self.client_id,
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            }
            async with self.session.post(url, headers=headers, json=payload) as resp:
                if resp.status in (200, 202):
                    print(f"Suscrito exitosamente al broadcaster ID {broadcaster_id}")
                    return

                if resp.status == 409:
                    return

                body = await resp.text()
                if resp.status == 401 and attempt == 0:
                    await self._get_user_access_token()
                    continue

                raise TwitchAPIError(f"suscribirse al broadcaster ID {broadcaster_id}", resp.status, body)

    async def _unsubscribe_from_streamer(self, broadcaster_id: str) -> None:
        if not self.access_token:
            await self._get_user_access_token()

        url = "https://api.twitch.tv/helix/eventsub/subscriptions"
        action = f"cancelar la suscripción del broadcaster ID {broadcaster_id}"

        for attempt in range(2):
            headers = {
                "Client-ID": self.client_id,
                "Authorization": f"Bearer {self.access_token}",
            }
            params = {"type": "stream.online", "user_id": str(broadcaster_id)}
            async with self.session.get(url, headers=headers, params=params) as resp:
                if resp.status == 401 and attempt == 0:
                    await self._get_user_access_token()
                    continue

                if resp.status != 200:
                    raise TwitchAPIError(action, resp.status, await resp.text())

                data = await resp.json()
            break

        subscription_ids = [
            subscription["id"]
            for subscription in data.get("data", [])
            if subscription.get("condition", {}).get("broadcaster_user_id") == str(broadcaster_id)
        ]

        for subscription_id in subscription_ids:
            async with self.session.delete(url, headers=headers, params={"id": subscription_id}) as resp:
                if resp.status not in (204, 404):
                    raise TwitchAPIError(action, resp.status, await resp.text())

    async def sync_all_subscriptions(self, session_id: str) -> None:
        self.active_session_id = session_id

        streamers = await self.bot.db.twitch.get_tracked_streamers()

        failed = False
        for twitch_user in streamers:
            try:
                broadcaster_id = await self._get_broadcaster_id(twitch_user)
                if broadcaster_id:
                    await self._subscribe_to_streamer(broadcaster_id, session_id)
            except TwitchAPIError as error:
                failed = True
                await self._report_background_error(error, f"twitch sincronizar {twitch_user}")

        if not failed:
            self.last_reported_error = None

    async def _eventsub_listener_loop(self):
        await self.bot.wait_until_ready()

        base_delay = 15
        current_delay = base_delay
        ws_url = self.EVENTSUB_WS_URL

        while not self.bot.is_closed():
            self.active_session_id = None
            try:
                await self._get_user_access_token()

                async with self.session.ws_connect(ws_url) as ws:
                    current_delay = base_delay
                    ws_url = self.EVENTSUB_WS_URL

                    while not ws.closed:
                        msg = await ws.receive()

                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            message_type = data["metadata"]["message_type"]

                            if message_type == "session_welcome":
                                session_id = data["payload"]["session"]["id"]
                                self.active_session_id = session_id
                                await self.sync_all_subscriptions(session_id)

                            elif message_type == "notification":
                                event_type = data["metadata"]["subscription_type"]
                                if event_type == "stream.online":
                                    await self._dispatch_stream_alert(data["payload"]["event"])

                            elif message_type == "session_keepalive":
                                continue

                            elif message_type == "session_reconnect":
                                reconnect_url = data["payload"]["session"]["reconnect_url"]
                                print(f"EventSub solicitó reconexión a {reconnect_url}")
                                ws_url = reconnect_url
                                break

                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                            print("EventSub WebSocket cerrado de forma normal.")
                            break

            except aiohttp.WSServerHandshakeError as e:
                if e.status == 429:
                    current_delay = min(current_delay * 2, 120)

                ws_url = self.EVENTSUB_WS_URL
                await self._report_background_error(e, "twitch eventsub handshake")

            except Exception as e:
                ws_url = self.EVENTSUB_WS_URL
                await self._report_background_error(e, "twitch eventsub")

            print(f"Reconectando a Twitch en {current_delay} segundos...")
            await asyncio.sleep(current_delay)

    async def _dispatch_stream_alert(self, event_data: dict):
        twitch_user = event_data.get("broadcaster_user_login", "").lower()
        streamer_name = event_data.get("broadcaster_user_name", twitch_user)

        destinations = await self.bot.db.twitch.get_streamer_destinations(twitch_user)

        if not destinations:
            return

        twitch_url = f"https://twitch.tv/{twitch_user}"

        for channel_id, kick_user, everyone in destinations:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue

            kick_url = f"https://kick.com/{kick_user}" if kick_user else None

            embed = discord.Embed(title=f"🔴 ¡{streamer_name} está en directo!", url=twitch_url, color=0x9146FF)
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

        await interaction.response.defer(ephemeral=True)

        broadcaster_id = await self._get_broadcaster_id(twitch_user)
        if not broadcaster_id:
            await interaction.followup.send(f"No se pudo encontrar al usuario `{twitch_user}` en Twitch.", ephemeral=True)
            return

        await self.bot.db.twitch.add_or_update_tracked_streamer(interaction.guild_id, target_channel.id, twitch_user, kick_user, at_everyone)

        subscription_error: Optional[TwitchAPIError] = None
        if self.active_session_id:
            try:
                await self._subscribe_to_streamer(broadcaster_id, self.active_session_id)
            except TwitchAPIError as error:
                subscription_error = error
                await self.bot.report_exception(
                    error,
                    source="slash",
                    command_name="streams agregar",
                    guild=interaction.guild,
                    user=interaction.user,
                    channel=interaction.channel,
                    arguments=describe_arguments(interaction),
                )

        if subscription_error is None:
            msg = f"Notificaciones activadas para **{twitch_user}** en {target_channel.mention}."
            if kick_user:
                msg += f" (Enlace de Kick: https://kick.com/{kick_user})"
        else:
            msg = f"⚠️ Guardado **{twitch_user}**, pero falló la suscripción EventSub (HTTP {subscription_error.status})."

        await interaction.followup.send(msg, ephemeral=True)

    @streamer_group.command(name="quitar", description="Elimina un streamer de las notificaciones")
    async def remove_streamer(self, interaction: discord.Interaction, twitch: str):
        if await self.bot.filter_operators(interaction):
            return

        twitch_user = twitch.strip().lower()

        await interaction.response.defer(ephemeral=True)

        deleted = await self.bot.db.twitch.remove_tracked_streamer(interaction.guild_id, twitch_user)

        if not deleted:
            await interaction.followup.send(f"**{twitch_user}** no estaba en la lista", ephemeral=True)
            return

        unsubscribe_error: Optional[TwitchAPIError] = None
        if twitch_user not in await self.bot.db.twitch.get_tracked_streamers():
            try:
                broadcaster_id = await self._get_broadcaster_id(twitch_user)
                if broadcaster_id:
                    await self._unsubscribe_from_streamer(broadcaster_id)
            except TwitchAPIError as error:
                unsubscribe_error = error
                await self.bot.report_exception(
                    error,
                    source="slash",
                    command_name="streams quitar",
                    guild=interaction.guild,
                    user=interaction.user,
                    channel=interaction.channel,
                    arguments=describe_arguments(interaction),
                )

        if unsubscribe_error is None:
            await interaction.followup.send(f"Notificaciones desactivadas para **{twitch_user}**.", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️ Eliminado **{twitch_user}**, pero falló la cancelación de la suscripción EventSub (HTTP {unsubscribe_error.status}). El error se ha enviado al canal de depuración.", ephemeral=True)

    @streamer_group.command(name="lista", description="Muestra los streamers configurados")
    async def list_streamers(self, interaction: discord.Interaction):
        rows = await self.bot.db.twitch.get_guild_tracked_streamers(interaction.guild_id)

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