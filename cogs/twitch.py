import asyncio
import datetime
import json
import os
import random
import sys
import time
from collections import deque
from typing import Any, Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from error_reporting import describe_arguments
from main import JoseLuisBot


class TwitchAPIError(Exception):
    def __init__(self, action: str, status: Optional[int], body: str, transient: Optional[bool] = None):
        self.action = action
        self.status = status
        self.body = body
        if transient is None:
            transient = status is not None and (status == 429 or status >= 500)
        self.transient = transient
        status_text = f"HTTP {status}" if status is not None else "sin respuesta"
        super().__init__(f"Fallo al {action} ({status_text}): {body}")


class StreamerNotifierCog(commands.Cog):
    EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"
    HELIX_URL = "https://api.twitch.tv/helix"
    TOKEN_URL = "https://id.twitch.tv/oauth2/token"

    DEFAULT_KEEPALIVE_TIMEOUT = 30
    KEEPALIVE_MARGIN = 10
    CONNECT_TIMEOUT = 20
    REQUEST_TIMEOUT = 20
    REQUEST_ATTEMPTS = 4
    SEND_ATTEMPTS = 3
    BASE_RECONNECT_DELAY = 5
    MAX_RECONNECT_DELAY = 300
    RATE_LIMITED_RECONNECT_DELAY = 60
    HEALTHY_SESSION_SECONDS = 60
    ESCALATION_FAILURES = 5
    IDLE_RECHECK_SECONDS = 60
    RESYNC_SECONDS = 1800
    TOKEN_RETRY_SECONDS = 300
    SYNC_CONCURRENCY = 5
    REPORT_COOLDOWN_SECONDS = 3600
    REPORT_MEMORY_LIMIT = 200
    SEEN_MESSAGES_LIMIT = 500
    ANNOUNCED_STREAMS_LIMIT = 200

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
        self.next_token_refresh: float = 0.0
        self.token_lock = asyncio.Lock()
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws_task: Optional[asyncio.Task] = None
        self.sync_task: Optional[asyncio.Task] = None
        self.active_session_id: Optional[str] = None
        self.welcomed_at: Optional[float] = None
        self.last_alive_at: Optional[datetime.datetime] = None
        self.streamers_changed = asyncio.Event()
        self.unloading = False
        self.reported_at: dict[str, float] = {}
        self.seen_message_ids: deque[str] = deque(maxlen=self.SEEN_MESSAGES_LIMIT)
        self.announced_stream_ids: deque[str] = deque(maxlen=self.ANNOUNCED_STREAMS_LIMIT)

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession()
        self._start_listener()

    async def cog_unload(self) -> None:
        self.unloading = True
        for task in (self.ws_task, self.sync_task):
            if task:
                task.cancel()
        if self.session and not self.session.closed:
            await self.session.close()

    def _start_listener(self) -> None:
        self.ws_task = asyncio.create_task(self._eventsub_listener_loop())
        self.ws_task.add_done_callback(self._on_listener_done)

    def _on_listener_done(self, task: asyncio.Task) -> None:
        if self.unloading or task.cancelled() or self.bot.is_closed():
            return
        self.ws_task = asyncio.create_task(self._restart_listener(task.exception()))

    async def _restart_listener(self, error: Optional[BaseException]) -> None:
        print(f"EventSub: listener stopped unexpectedly ({error!r}), restarting")
        if error is not None:
            await self._report_background_error(error, "twitch eventsub listener")
        await asyncio.sleep(self.BASE_RECONNECT_DELAY)
        if not self.unloading and not self.bot.is_closed():
            self._start_listener()

    async def _report_background_error(self, error: BaseException, task_name: str, guild: Optional[discord.Guild] = None) -> None:
        key = f"{task_name}|{type(error).__name__}: {error}"
        now = time.monotonic()
        last_report = self.reported_at.get(key)
        if last_report is not None and now - last_report < self.REPORT_COOLDOWN_SECONDS:
            return

        if len(self.reported_at) >= self.REPORT_MEMORY_LIMIT:
            self.reported_at = {
                known_key: reported
                for known_key, reported in self.reported_at.items()
                if now - reported < self.REPORT_COOLDOWN_SECONDS
            }
        self.reported_at[key] = now

        try:
            guilds = [guild] if guild is not None else await self._get_tracked_guilds()
            for target in guilds or [None]:
                try:
                    await self.bot.report_exception(
                        error,
                        source="tarea en segundo plano",
                        command_name=task_name,
                        guild=target,
                        user=None,
                        channel=None,
                    )
                except Exception as report_error:
                    print(f"EventSub: could not report error to guild: {report_error!r}", file=sys.stderr)
        except Exception as report_error:
            print(f"EventSub: could not report error: {report_error!r} (original: {error!r})", file=sys.stderr)

    async def _get_tracked_guilds(self) -> list[discord.Guild]:
        guild_ids = await self.bot.db.twitch.get_tracked_guild_ids()
        guilds = [self.bot.get_guild(guild_id) for guild_id in guild_ids]
        return [guild for guild in guilds if guild is not None]

    @staticmethod
    def _is_transient(error: BaseException) -> bool:
        if isinstance(error, TwitchAPIError):
            return error.transient
        return isinstance(error, (aiohttp.ClientError, asyncio.TimeoutError, OSError))

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        return float(min(2 ** attempt, 16))

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def _get_user_access_token(self) -> str:
        async with self.token_lock:
            return await self._refresh_user_access_token()

    async def _refresh_user_access_token(self) -> str:
        try:
            with open(self.tokens_file, "r") as f:
                token_data = json.load(f)
        except FileNotFoundError:
            raise TwitchAPIError("leer los tokens de Twitch", None, f"Falta {self.tokens_file}") from None
        except (OSError, ValueError) as error:
            raise TwitchAPIError("leer los tokens de Twitch", None, f"{self.tokens_file} ilegible: {error}") from error

        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            raise TwitchAPIError("leer los tokens de Twitch", None, "No se encontró refresh_token en twitch_tokens.json")

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        for attempt in range(self.REQUEST_ATTEMPTS):
            try:
                new_tokens = await self._request_token_refresh(payload)
                break
            except TwitchAPIError as error:
                if not error.transient or attempt + 1 == self.REQUEST_ATTEMPTS:
                    raise
                await asyncio.sleep(self._retry_delay(attempt))

        new_tokens.setdefault("refresh_token", refresh_token)
        self.access_token = new_tokens["access_token"]
        self.next_token_refresh = time.monotonic() + float(new_tokens.get("expires_in") or 14400) * 0.75

        temporary_file = f"{self.tokens_file}.tmp"
        try:
            with open(temporary_file, "w") as f:
                json.dump(new_tokens, f, indent=2)
            os.replace(temporary_file, self.tokens_file)
        except OSError as error:
            await self._report_background_error(
                TwitchAPIError("guardar los tokens de Twitch", None, str(error)),
                "twitch guardar tokens",
            )

        print("Twitch User Access Token renovado con éxito.")
        return self.access_token

    async def _request_token_refresh(self, payload: dict[str, str]) -> dict[str, Any]:
        action = "renovar el User Access Token"
        try:
            async with self._ensure_session().post(
                self.TOKEN_URL,
                data=payload,
                timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT),
            ) as resp:
                status = resp.status
                body = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            raise TwitchAPIError(action, None, repr(error), transient=True) from error

        if status != 200:
            raise TwitchAPIError(action, status, body)

        try:
            tokens = json.loads(body)
            tokens["access_token"]
        except (ValueError, KeyError, TypeError) as error:
            raise TwitchAPIError(action, status, "Respuesta inválida al renovar el token", transient=True) from error
        return tokens

    async def _refresh_token_if_due(self) -> None:
        if time.monotonic() < self.next_token_refresh:
            return
        try:
            await self._get_user_access_token()
        except TwitchAPIError as error:
            self.next_token_refresh = time.monotonic() + self.TOKEN_RETRY_SECONDS
            print(f"EventSub: scheduled token refresh failed: {error}")
            await self._report_background_error(error, "twitch renovar token")

    async def _request(
        self,
        method: str,
        path: str,
        action: str,
        *,
        params: Optional[dict[str, str] | list[tuple[str, str]]] = None,
        json_body: Optional[dict[str, Any]] = None,
        ok_statuses: tuple[int, ...] = (200,),
    ) -> dict[str, Any]:
        if not self.access_token:
            await self._get_user_access_token()

        last_error: Optional[TwitchAPIError] = None
        for attempt in range(self.REQUEST_ATTEMPTS):
            used_token = self.access_token
            headers = {
                "Client-ID": self.client_id,
                "Authorization": f"Bearer {used_token}",
            }
            wait = self._retry_delay(attempt)
            try:
                async with self._ensure_session().request(
                    method,
                    f"{self.HELIX_URL}{path}",
                    headers=headers,
                    params=params,
                    json=json_body,
                    timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT),
                ) as resp:
                    status = resp.status
                    body = await resp.text()
                    rate_limit_reset = resp.headers.get("Ratelimit-Reset")
            except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                last_error = TwitchAPIError(action, None, repr(error), transient=True)
            else:
                if status in ok_statuses:
                    try:
                        parsed = json.loads(body) if body else {}
                    except ValueError:
                        parsed = {}
                    return parsed if isinstance(parsed, dict) else {}

                last_error = TwitchAPIError(action, status, body)
                if status == 401:
                    if self.access_token == used_token:
                        await self._get_user_access_token()
                    continue
                if not last_error.transient:
                    raise last_error
                if status == 429 and rate_limit_reset:
                    try:
                        wait = min(max(float(rate_limit_reset) - time.time(), 1.0), 30.0)
                    except ValueError:
                        pass

            if attempt + 1 < self.REQUEST_ATTEMPTS:
                await asyncio.sleep(wait)

        raise last_error or TwitchAPIError(action, None, "sin respuesta", transient=True)

    async def _get_broadcaster_id(self, username: str) -> Optional[str]:
        data = await self._request("GET", "/users", f"buscar al usuario {username}", params={"login": username})
        users = data.get("data")
        if users:
            return users[0]["id"]
        return None

    async def _subscribe_to_streamer(self, broadcaster_id: str, session_id: str) -> None:
        payload = {
            "type": "stream.online",
            "version": "1",
            "condition": {"broadcaster_user_id": str(broadcaster_id)},
            "transport": {
                "method": "websocket",
                "session_id": str(session_id)
            },
        }
        await self._request(
            "POST",
            "/eventsub/subscriptions",
            f"suscribirse al broadcaster ID {broadcaster_id}",
            json_body=payload,
            ok_statuses=(200, 202, 409),
        )

    async def _unsubscribe_from_streamer(self, broadcaster_id: str) -> None:
        action = f"cancelar la suscripción del broadcaster ID {broadcaster_id}"
        data = await self._request("GET", "/eventsub/subscriptions", action, params={"user_id": str(broadcaster_id)})

        subscription_ids = [
            subscription["id"]
            for subscription in data.get("data", [])
            if subscription.get("type") == "stream.online"
            and subscription.get("condition", {}).get("broadcaster_user_id") == str(broadcaster_id)
        ]

        for subscription_id in subscription_ids:
            await self._request("DELETE", "/eventsub/subscriptions", action, params={"id": subscription_id}, ok_statuses=(204, 404))

    async def sync_all_subscriptions(self, session_id: str) -> None:
        streamers = await self.bot.db.twitch.get_tracked_streamers()
        semaphore = asyncio.Semaphore(self.SYNC_CONCURRENCY)

        async def sync_streamer(twitch_user: str) -> None:
            async with semaphore:
                try:
                    broadcaster_id = await self._get_broadcaster_id(twitch_user)
                    if broadcaster_id is None:
                        raise TwitchAPIError(f"buscar al usuario {twitch_user}", 404, "El usuario no existe en Twitch")
                    await self._subscribe_to_streamer(broadcaster_id, session_id)
                except Exception as error:
                    print(f"EventSub: could not subscribe to {twitch_user}: {error}")
                    await self._report_background_error(error, f"twitch sincronizar {twitch_user}")

        await asyncio.gather(*(sync_streamer(twitch_user) for twitch_user in streamers))

    async def _catch_up_live_streamers(self, since: datetime.datetime) -> None:
        streamers = await self.bot.db.twitch.get_tracked_streamers()
        for start in range(0, len(streamers), 100):
            chunk = streamers[start:start + 100]
            data = await self._request(
                "GET",
                "/streams",
                "consultar los directos activos",
                params=[("user_login", twitch_user) for twitch_user in chunk],
            )
            for stream in data.get("data", []):
                if stream.get("type") != "live":
                    continue
                if datetime.datetime.fromisoformat(stream["started_at"]) <= since:
                    continue
                print(f"EventSub: catching up missed stream of {stream['user_login']}")
                await self._dispatch_stream_alert({
                    "id": stream["id"],
                    "broadcaster_user_login": stream["user_login"],
                    "broadcaster_user_name": stream["user_name"],
                })

    async def _run_session_sync(self, session_id: str, catch_up_since: Optional[datetime.datetime]) -> None:
        try:
            await self.sync_all_subscriptions(session_id)
            if catch_up_since is not None:
                await self._catch_up_live_streamers(catch_up_since)
        except Exception as error:
            print(f"EventSub: session sync failed: {error!r}")
            await self._report_background_error(error, "twitch sincronizar")

    def _start_session_sync(self, session_id: str, catch_up_since: Optional[datetime.datetime]) -> None:
        if self.sync_task is not None and not self.sync_task.done():
            self.sync_task.cancel()
        self.sync_task = asyncio.create_task(self._run_session_sync(session_id, catch_up_since))

    async def _wait_for_streamers(self) -> None:
        try:
            await asyncio.wait_for(self.streamers_changed.wait(), self.IDLE_RECHECK_SECONDS)
        except asyncio.TimeoutError:
            pass

    async def _close_quietly(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        try:
            await ws.close()
        except Exception as error:
            print(f"EventSub: error closing WebSocket: {error!r}")

    async def _run_session(self, ws_url: str) -> Optional[str]:
        await self._get_user_access_token()
        catch_up_since = self.last_alive_at
        ws = await asyncio.wait_for(self._ensure_session().ws_connect(ws_url), self.CONNECT_TIMEOUT)

        keepalive_timeout = self.DEFAULT_KEEPALIVE_TIMEOUT
        next_resync = time.monotonic() + self.RESYNC_SECONDS
        try:
            while not ws.closed:
                await self._refresh_token_if_due()

                if self.active_session_id is not None and time.monotonic() >= next_resync:
                    next_resync = time.monotonic() + self.RESYNC_SECONDS
                    if self.sync_task is None or self.sync_task.done():
                        self._start_session_sync(self.active_session_id, None)

                try:
                    msg = await ws.receive(timeout=keepalive_timeout + self.KEEPALIVE_MARGIN)
                except asyncio.TimeoutError:
                    print(f"EventSub: no messages for {keepalive_timeout + self.KEEPALIVE_MARGIN}s, reconnecting")
                    return None

                self.last_alive_at = discord.utils.utcnow()

                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        metadata = data["metadata"]
                        message_type = metadata["message_type"]

                        message_id = metadata.get("message_id")
                        if message_id is not None:
                            if message_id in self.seen_message_ids:
                                continue
                            self.seen_message_ids.append(message_id)

                        if message_type == "session_welcome":
                            session = data["payload"]["session"]
                            keepalive_timeout = int(session.get("keepalive_timeout_seconds") or self.DEFAULT_KEEPALIVE_TIMEOUT)
                            self.active_session_id = session["id"]
                            self.welcomed_at = time.monotonic()
                            next_resync = self.welcomed_at + self.RESYNC_SECONDS
                            print(f"EventSub: session {self.active_session_id} started (keepalive {keepalive_timeout}s)")
                            self._start_session_sync(self.active_session_id, catch_up_since)

                        elif message_type == "notification":
                            if metadata.get("subscription_type") == "stream.online":
                                await self._dispatch_stream_alert(data["payload"]["event"])

                        elif message_type == "revocation":
                            subscription = data["payload"]["subscription"]
                            print(f"EventSub: subscription revoked ({subscription.get('type')}: {subscription.get('status')})")
                            await self._report_background_error(
                                TwitchAPIError("mantener una suscripción EventSub", None, f"Revocada: {subscription.get('status')}"),
                                "twitch eventsub revocation",
                            )
                            return None

                        elif message_type == "session_reconnect":
                            reconnect_url = data["payload"]["session"]["reconnect_url"]
                            print(f"EventSub solicitó reconexión a {reconnect_url}")
                            return reconnect_url

                    except Exception as error:
                        print(f"EventSub: failed to process message: {error!r}")
                        await self._report_background_error(error, "twitch eventsub mensaje")

                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
                    print(f"EventSub: connection closed (code {ws.close_code})")
                    return None

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    raise ConnectionError(f"WebSocket error: {ws.exception()!r}")

            return None
        finally:
            self.active_session_id = None
            if self.sync_task is not None and not self.sync_task.done():
                self.sync_task.cancel()
            await self._close_quietly(ws)

    async def _eventsub_listener_loop(self) -> None:
        await self.bot.wait_until_ready()

        ws_url = self.EVENTSUB_WS_URL
        failures = 0

        while not self.bot.is_closed():
            self.active_session_id = None
            self.welcomed_at = None
            error: Optional[Exception] = None
            reconnect_url: Optional[str] = None

            try:
                self.streamers_changed.clear()
                if not await self.bot.db.twitch.get_tracked_streamers():
                    ws_url = self.EVENTSUB_WS_URL
                    failures = 0
                    await self._wait_for_streamers()
                    continue
                reconnect_url = await self._run_session(ws_url)
            except Exception as caught:
                error = caught

            if reconnect_url is not None:
                ws_url = reconnect_url
                failures = 0
                continue

            ws_url = self.EVENTSUB_WS_URL
            healthy = self.welcomed_at is not None and time.monotonic() - self.welcomed_at >= self.HEALTHY_SESSION_SECONDS
            failures = 0 if healthy and error is None else failures + 1

            if error is not None:
                print(f"EventSub: session failed: {error!r}")
                if not self._is_transient(error) or failures >= self.ESCALATION_FAILURES:
                    await self._report_background_error(error, "twitch eventsub")
            elif failures >= self.ESCALATION_FAILURES:
                await self._report_background_error(
                    TwitchAPIError("mantener la conexión con EventSub", None, "La conexión se cierra repetidamente; se sigue reintentando"),
                    "twitch eventsub",
                )

            delay = min(self.BASE_RECONNECT_DELAY * 2 ** min(max(failures - 1, 0), 10), self.MAX_RECONNECT_DELAY)
            if isinstance(error, aiohttp.WSServerHandshakeError) and error.status == 429:
                delay = max(delay, self.RATE_LIMITED_RECONNECT_DELAY)
            delay += random.uniform(0, 3)

            print(f"Reconectando a Twitch en {delay:.0f} segundos...")
            await asyncio.sleep(delay)

    async def _fetch_destinations(self, twitch_user: str) -> list[tuple[int, int, str | None, int]]:
        for attempt in range(self.SEND_ATTEMPTS):
            try:
                return await self.bot.db.twitch.get_streamer_destinations(twitch_user)
            except Exception:
                if attempt + 1 == self.SEND_ATTEMPTS:
                    raise
                await asyncio.sleep(self._retry_delay(attempt))
        return []

    async def _resolve_channel(self, channel_id: int) -> discord.abc.Messageable:
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError(f"El canal {channel_id} no admite mensajes")
        return channel

    async def _send_with_retries(self, channel: discord.abc.Messageable, content: str, embed: discord.Embed) -> None:
        for attempt in range(self.SEND_ATTEMPTS):
            try:
                await channel.send(content=content, embed=embed)
                return
            except (discord.Forbidden, discord.NotFound):
                raise
            except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError):
                if attempt + 1 == self.SEND_ATTEMPTS:
                    raise
                await asyncio.sleep(self._retry_delay(attempt))

    async def _dispatch_stream_alert(self, event_data: dict[str, Any]) -> None:
        twitch_user = event_data.get("broadcaster_user_login", "").lower()
        streamer_name = event_data.get("broadcaster_user_name", twitch_user)

        stream_id = event_data.get("id")
        if stream_id is not None:
            if stream_id in self.announced_stream_ids:
                print(f"EventSub: stream {stream_id} of {twitch_user} already announced")
                return
            self.announced_stream_ids.append(stream_id)

        print(f"EventSub: stream.online received for {twitch_user}")
        destinations = await self._fetch_destinations(twitch_user)

        if not destinations:
            print(f"EventSub: no destinations configured for {twitch_user}")
            return

        twitch_url = f"https://twitch.tv/{twitch_user}"

        for guild_id, channel_id, kick_user, everyone in destinations:
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

            try:
                channel = await self._resolve_channel(channel_id)
                await self._send_with_retries(channel, content, embed)
            except Exception as error:
                print(f"EventSub: could not announce {twitch_user} in channel {channel_id}: {error!r}")
                await self._report_background_error(error, f"twitch alerta {twitch_user}", guild=self.bot.get_guild(guild_id))

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
        self.streamers_changed.set()

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
