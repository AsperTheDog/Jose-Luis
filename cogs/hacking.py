import time
import asyncio
import random
from datetime import datetime, timezone, timedelta, time
from collections import deque
import discord
from discord import app_commands
from discord.ext import commands, tasks

from main import JoseLuisBot

DIFFICULTIES = {
    "easy": {
        "name": "Fácil",
        "width": 11, "height": 7,
        "proxies": 1,
        "loop_chance": 0.05,
        "time_mult": 1.3, "time_base": 10,
        "timed_payout": 100, "perfect_payout": 50,
        "max_speed_bonus": 50
    },
    "normal": {
        "name": "Normal",
        "width": 13, "height": 9,
        "proxies": 2,
        "loop_chance": 0.10,
        "time_mult": 1.3, "time_base": 10,
        "timed_payout": 150, "perfect_payout": 80,
        "max_speed_bonus": 100
    },
    "hard": {
        "name": "Difícil",
        "width": 17, "height": 9,
        "proxies": 3,
        "loop_chance": 0.15,
        "time_mult": 1.2, "time_base": 20,
        "timed_payout": 200, "perfect_payout": 150,
        "max_speed_bonus": 200
    },
    "very_hard": {
        "name": "Muy Difícil",
        "width": 21, "height": 11,
        "proxies": 4,
        "loop_chance": 0.25,
        "time_mult": 1.0, "time_base": 20,
        "timed_payout": 600, "perfect_payout": 300,
        "max_speed_bonus": 400
    }
}

WALL = '■'
EMPTY = '.'
START = 'S'
TARGET = 'T'
PROXY = 'o'
PATH_CHAR = 'x'
CRASH_CHAR = '@'


class TutorialView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=120)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Solo quien usó `/tutorial` puede interactuar con este menú.", ephemeral=True)
            return False
        return True

    @discord.ui.select(
        placeholder="📚 Selecciona una sección del manual...",
        options=[
            discord.SelectOption(label="Visión General", description="Aprende a leer el mapa ASCII", emoji="🗺️", value="symbols"),
            discord.SelectOption(label="Controles", description="Sintaxis de movimientos y envío", emoji="🎮", value="controls"),
            discord.SelectOption(label="Modos y Dificultades", description="Contrarreloj vs Perfecto y recompensas", emoji="⚡", value="modes"),
            discord.SelectOption(label="Recompensas", description="Cómo funcionan las bonificaciones y penalizaciones", emoji="💰", value="payouts"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        choice = select.values[0]

        if choice == "symbols":
            embed = discord.Embed(
                title="🗺️ Mapa",
                color=discord.Color.blurple(),
                description=(
                    "El mapa de intrusión es una cuadrícula hecha con texto. "
                    "Tu objetivo es trazar una ruta continua desde el inicio hasta el objetivo.\n\n"
                    "**Leyenda de caracteres:**\n"
                    "• `S` ➔ **Punto de Inicio (Start):** Posición inicial de tu sonda de hackeo.\n"
                    "• `T` ➔ **Núcleo Objetivo (Target):** El punto final al que debes llegar.\n"
                    "• `o` ➔ **Proxy de Datos:** Servidores intermedios obligatorios. **¡Debes recogerlos TODOS antes de llegar a `T`!**\n"
                    "• `#` ➔ **Cortafuegos (Wall):** Bloques infranqueables. Si los tocas, la sonda destruirá la conexión.\n"
                    "• `.` ➔ **Camino Libre:** Casillas transitables seguras.\n"
                    "• `x` ➔ **Ruta Recorrida:** Marca la trayectoria ejecutada por tu sonda.\n"
                    "• `@` ➔ **Punto de Colisión:** Muestra la posición exacta del choque si colisionas."
                )
            )

        elif choice == "controls":
            embed = discord.Embed(
                title="🎮 Controles",
                color=discord.Color.gold(),
                description=(
                    "Para mover la sonda, no usas botones ni comandos extra. **Escribes tu ruta en el chat directamente**.\n\n"
                    "**Direcciones válidas:**\n"
                    "• `n` ➔ Norte / Arriba (Norte)\n"
                    "• `s` ➔ Sur / Abajo (Sur)\n"
                    "• `e` ➔ Este / Derecha (Este)\n"
                    "• `o` ➔ Oeste / Izquierda (Oeste)\n\n"
                    "**Ejemplo práctico:**\n"
                    "Si deseas moverte 3 casillas a la derecha, 2 abajo y 1 a la izquierda, debes enviar el mensaje:\n"
                    "```text\neeesso\n```\n"
                    "*(No importan los espacios ni las mayúsculas; el bot ignorará cualquier carácter que no sea `n, s, e, o`)*."
                )
            )

        elif choice == "modes":
            embed = discord.Embed(
                title="⚡ Modos de Juego y Dificultades",
                color=discord.Color.purple(),
                description=(
                    "**1. Modo Contrarreloj (Timed):**\n"
                    "• Cuentas con un límite estricto de tiempo con un temporizador.\n"
                    "• Cuanto más rápido respondas, mayor será tu bonificación de velocidad.\n\n"
                    "**2. Modo Perfecto (Perfect):**\n"
                    "• Sin límite de tiempo, pero cero margen de error.\n"
                    "• Debes encontrar exactamente la ruta más corta posible. Si usas un solo paso de más, fallarás.\n\n"
                    "**Niveles de Seguridad:**\n"
                    "• **Fácil:** 1 Proxy | Recompensa base: $100\n"
                    "• **Normal:** 2 Proxies | Recompensa base: $200\n"
                    "• **Difícil:** 3 Proxies | Recompensa base: $400\n"
                    "• **Muy Difícil:** 4 Proxies | Recompensa base: $700"
                )
            )

        elif choice == "payouts":
            embed = discord.Embed(
                title="💰 Recompensas",
                color=discord.Color.green(),
                description=(
                    "La recompensa final se calcula dinámicamente según tu desempeño:\n\n"
                    "**1. Bonificación por Tiempo:**\n"
                    "• Se calcula la proporción de tiempo ahorrado respecto al límite.\n"
                    "• *Ejemplo:* Si ahorras el 80% del tiempo en Difícil, obtendrás el 80% del bono máximo ($400 × 0.80 = +$320).\n\n"
                    "**2. Penalización por Pasos Extra:**\n"
                    "• Si das pasos de más respecto a la ruta óptima, sufres una penalización basada en el porcentaje de exceso.\n"
                    "• Por ejemplo, si el óptimo eran 20 pasos y usas 25 (25% de exceso), perderás el 25% del Pago Base.\n\n"
                )
            )

        await interaction.response.edit_message(embed=embed, view=self)


class CyberHackEngine:
    def __init__(self, diff_key: str, mode: str, bot: JoseLuisBot, user_id: int):
        cfg = DIFFICULTIES[diff_key]
        self.bot = bot
        self.diff_key = diff_key
        self.diff_name = cfg["name"]
        self.mode = mode
        self.width = cfg["width"]
        self.height = cfg["height"]
        self.num_proxies = cfg["proxies"]
        self.loop_chance = cfg["loop_chance"]
        self.base_payout = cfg["timed_payout"] if mode == "timed" else cfg["perfect_payout"]
        self.user = user_id

        self.grid = []
        self.start_pos = (1, 1)
        self.target_pos = (self.width - 2, self.height - 2)
        self.proxies = []
        self.optimal_steps = 0
        self.optimal_path = []
        self.time_limit = 0
        self.generate_map(cfg)

    def generate_map(self, cfg):
        while True:
            self.grid = [[WALL for _ in range(self.width)] for _ in range(self.height)]
            stack = [self.start_pos]
            self.grid[self.start_pos[1]][self.start_pos[0]] = EMPTY

            # 1. Generar Laberinto
            while stack:
                x, y = stack[-1]
                neighbors = []
                for dx, dy in [(0, -2), (0, 2), (-2, 0), (2, 0)]:
                    nx, ny = x + dx, y + dy
                    if 0 < nx < self.width - 1 and 0 < ny < self.height - 1:
                        if self.grid[ny][nx] == WALL:
                            neighbors.append((nx, ny, dx // 2, dy // 2))

                if neighbors:
                    nx, ny, wx, wy = random.choice(neighbors)
                    self.grid[y + wy][x + wx] = EMPTY
                    self.grid[ny][nx] = EMPTY
                    stack.append((nx, ny))
                else:
                    stack.pop()

            # 2. Añadir Bucles
            for y in range(1, self.height - 1):
                for x in range(1, self.width - 1):
                    if self.grid[y][x] == WALL:
                        v_path = self.grid[y - 1][x] == EMPTY and self.grid[y + 1][x] == EMPTY
                        h_path = self.grid[y][x - 1] == EMPTY and self.grid[y][x + 1] == EMPTY
                        if (v_path and not h_path) or (h_path and not v_path):
                            if random.random() < self.loop_chance:
                                self.grid[y][x] = EMPTY

            # 3. Colocar Proxies
            dead_ends, valid_cells = [], []
            for y in range(1, self.height - 1):
                for x in range(1, self.width - 1):
                    if self.grid[y][x] == EMPTY and (x, y) != self.start_pos and (x, y) != self.target_pos:
                        valid_cells.append((x, y))
                        paths = sum(1 for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)] if self.grid[y + dy][x + dx] == EMPTY)
                        if paths == 1:
                            dead_ends.append((x, y))

            random.shuffle(dead_ends)
            random.shuffle(valid_cells)
            self.proxies = (dead_ends + valid_cells)[:self.num_proxies]

            self.grid[self.start_pos[1]][self.start_pos[0]] = START
            self.grid[self.target_pos[1]][self.target_pos[0]] = TARGET
            for px, py in self.proxies:
                self.grid[py][px] = PROXY

            res = self.solve_bfs()
            if res is not None:
                self.optimal_steps, self.optimal_path = res
                self.time_limit = int(self.optimal_steps * cfg["time_mult"]) + cfg["time_base"] + 4
                break

    def solve_bfs(self):
        queue = deque([(self.start_pos[0], self.start_pos[1], 0, 0, [self.start_pos])])
        visited = set([(self.start_pos[0], self.start_pos[1], 0)])
        target_mask = (1 << len(self.proxies)) - 1

        while queue:
            x, y, mask, steps, path = queue.popleft()
            if (x, y) == self.target_pos and mask == target_mask:
                return steps, path

            for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.width and 0 <= ny < self.height and self.grid[ny][nx] != WALL:
                    new_mask = mask
                    if (nx, ny) in self.proxies:
                        new_mask |= (1 << self.proxies.index((nx, ny)))
                    state = (nx, ny, new_mask)
                    if state not in visited:
                        visited.add(state)
                        queue.append((nx, ny, new_mask, steps + 1, path + [(nx, ny)]))
        return None

    def render_ascii(self, path_coords: list = None, crash_coord: tuple = None) -> str:
        display_grid = [row[:] for row in self.grid]

        if path_coords:
            for px, py in path_coords:
                if display_grid[py][px] not in (START, TARGET):
                    display_grid[py][px] = PATH_CHAR

        if crash_coord:
            cx, cy = crash_coord
            if 0 <= cx < self.width and 0 <= cy < self.height:
                display_grid[cy][cx] = CRASH_CHAR

        lines = ["+" + "-" * (self.width * 2 + 1) + "+"]
        for y in range(self.height):
            row = "| " + " ".join(display_grid[y][x] for x in range(self.width)) + " |"
            lines.append(row)
        lines.append("+" + "-" * (self.width * 2 + 1) + "+")
        return "\n".join(lines)

    async def simulate(self, sequence: str, elapsed_time: float):
        x, y = self.start_pos
        collected = set()
        steps = 0
        visited_path = [(x, y)]
        dirs = {'n': (0, -1), 's': (0, 1), 'e': (1, 0), 'o': (-1, 0)}

        for char in sequence.lower():
            if char not in dirs:
                continue
            dx, dy = dirs[char]
            nx, ny = x + dx, y + dy
            steps += 1

            if not (0 <= nx < self.width and 0 <= ny < self.height) or self.grid[ny][nx] == WALL:
                await self.bot.global_stats.register_hack_loss(self.user, "firewall", elapsed_time)
                return False, f"💥 **¡FALLO CRÍTICO!** La sonda chocó contra un Cortafuegos en el paso `{steps}`.", visited_path, (nx, ny)

            x, y = nx, ny
            visited_path.append((x, y))

            if (x, y) in self.proxies:
                collected.add((x, y))

        if (x, y) != self.target_pos:
            await self.bot.global_stats.register_hack_loss(self.user, "lost", elapsed_time)
            return False, f"⛔ **¡ACCESO DENEGADO!** La secuencia terminó en `({x}, {y})`, no en el Núcleo (`T`).", visited_path, None

        if len(collected) < len(self.proxies):
            await self.bot.global_stats.register_hack_loss(self.user, "lost", elapsed_time)
            return False, f"⛔ **¡ACCESO DENEGADO!** Se alcanzó el Núcleo, pero faltaron proxies de datos (`{len(collected)}/{len(self.proxies)}`).", visited_path, None

        if self.mode == "perfect" and steps > self.optimal_steps:
            await self.bot.global_stats.register_hack_loss(self.user, "lost", elapsed_time)
            return False, f"⚠️ **¡FALLO EN MODO PERFECTO!** Se usaron `{steps}` pasos (El óptimo era `{self.optimal_steps}`).", visited_path, None

        return True, steps, visited_path, None

class CyberHackCog(commands.Cog):
    def __init__(self, bot: JoseLuisBot):
        self.bot = bot
        self.active_hacks = set()
        self.daily_reset_task.start()

    hacking_group = app_commands.Group(
        name="hacking",
        description="Comandos para jugar al juego de hackeos"
    )

    @hacking_group.command(name="jugar", description="Vulnera la red central para obtener choskris")
    @app_commands.describe(
        difficulty="Selecciona la dificultad de seguridad del servidor",
        mode="Contrarreloj (Carrera contra el tiempo) o Perfecto (0 pasos extra permitidos)"
    )
    @app_commands.choices(
        difficulty=[
            app_commands.Choice(name="Fácil (1 Proxy)", value="easy"),
            app_commands.Choice(name="Normal (2 Proxies)", value="normal"),
            app_commands.Choice(name="Difícil (3 Proxies)", value="hard"),
            app_commands.Choice(name="Muy Difícil (4 Proxies)", value="very_hard"),
        ],
        mode=[
            app_commands.Choice(name="Modo Contrarreloj (Bonus por velocidad)", value="timed"),
            app_commands.Choice(name="Modo Perfecto (Sin temporizador, 0 errores)", value="perfect"),
        ]
    )
    async def hack_command(self, interaction: discord.Interaction, difficulty: app_commands.Choice[str], mode: app_commands.Choice[str] = None):
        user_id = interaction.user.id

        if user_id in self.active_hacks:
            await interaction.response.send_message("⚠️ **¡Ya tienes un hackeo en progreso!** Termina o espera a que expire tu partida actual antes de iniciar otra.", ephemeral=True)
            return

        self.active_hacks.add(user_id)
        try:
            diff_val = difficulty.value
            mode_val = mode.value if mode else "timed"

            engine = CyberHackEngine(diff_val, mode_val, self.bot, user_id)
            start_time = time.time()

            end_dt = datetime.now(timezone.utc) + timedelta(seconds=engine.time_limit)
            timer_display = discord.utils.format_dt(end_dt, style='R') if mode_val == "timed" else "`MODO PERFECTO` (Sin límite de tiempo)"

            embed = discord.Embed(
                title=f"🌐 INTRUSIÓN EN LA RED EN PROCESO [{engine.diff_name.upper()}]",
                color=discord.Color.blue() if mode_val == "timed" else discord.Color.purple()
            )

            embed.description = (
                f"```text\n{engine.render_ascii()}\n```\n"
                f"**Objetivos:**\n"
                f"1. Recolectar todos los `{engine.num_proxies}` Proxies (`{PROXY}`)\n"
                f"2. Llegar al Núcleo (`{TARGET}`)\n"
                f"3. Evitar los Firewalls (`{WALL}`)\n\n"
                f"⏳ **Tiempo Restante:** {timer_display}\n"
                f"💰 **Recompensa Base:** `${engine.base_payout:,}` choskris\n\n"
                f"👉 **Escribe tu secuencia de movimiento abajo como un mensaje** (`n, e, s, o`):"
            )

            await interaction.response.send_message(embed=embed)

            def check(msg: discord.Message):
                return msg.author.id == interaction.user.id and msg.channel.id == interaction.channel.id

            timeout_seconds = float(engine.time_limit) if mode_val == "timed" else 300.0

            try:
                user_msg = await self.bot.wait_for('message', check=check, timeout=timeout_seconds)
                elapsed_time = time.time() - start_time

                try:
                    await user_msg.delete()
                except discord.HTTPException:
                    pass

                raw_seq = user_msg.content
                success, result_data, visited_path, crash_coord = await engine.simulate(raw_seq, elapsed_time)

                result_embed = discord.Embed()

                if success:
                    player_steps = result_data
                    step_diff = player_steps - engine.optimal_steps

                    if mode_val == "timed":
                        time_left = max(0.0, engine.time_limit - elapsed_time)
                        time_saved_ratio = time_left / engine.time_limit

                        cfg_diff = DIFFICULTIES[engine.diff_key]
                        max_speed_bonus = cfg_diff.get("max_speed_bonus", 200)
                        speed_bonus = int(time_saved_ratio * max_speed_bonus)

                        step_excess_ratio = step_diff / engine.optimal_steps
                        penalty = int(step_excess_ratio * engine.base_payout)

                        payout = max(10, engine.base_payout + speed_bonus - penalty)
                    else:
                        payout = engine.base_payout

                    daily_deduct_msg = ""
                    if await self.bot.db.hacking_is_over_threshold(user_id, 3000):
                        payout *= 0.1
                        daily_deduct_msg = " (Has pasado los 3000 choskris hoy, recompensa reducida)"

                    result_embed.title = "🎉 ¡NÚCLEO INFILTRADO CON ÉXITO!"
                    result_embed.colour = discord.Color.green()
                    result_embed.description = (
                            f"```text\n{engine.render_ascii(path_coords=visited_path)}\n```\n"
                            f"**¡Acceso al sistema concedido!**\n\n"
                            f"⏱️ **Tiempo tardado:** `{elapsed_time:.1f}s`" + (f" / `{engine.time_limit}s`\n" if mode_val == "timed" else "\n") +
                            f"🐾 **Pasos usados:** `{player_steps}` (Óptimo: `{engine.optimal_steps}`)\n"
                            f"💰 **Recompensa:** **${payout:,}** choskris{daily_deduct_msg}"
                    )

                    await self.bot.db.economy_update_balance(user_id, payout)
                    await self.bot.db.hacking_add_win(user_id, payout)
                    await self.bot.global_stats.register_hack_win(user_id, diff_val, payout, elapsed_time)
                else:
                    result_embed.title = "💥 BLOQUEO DEL SISTEMA"
                    result_embed.colour = discord.Color.red()
                    result_embed.description = (
                        f"```text\n{engine.render_ascii(path_coords=visited_path, crash_coord=crash_coord)}\n```\n"
                        f"{result_data}\n\n"
                        f"💡 *Longitud de la ruta óptima:* `{engine.optimal_steps}` pasos.\n"
                        f"Tu respuesta: `{raw_seq}`"
                    )

                await interaction.edit_original_response(embed=result_embed)

            except asyncio.TimeoutError:
                await self.bot.global_stats.register_hack_loss(user_id, "timeout", elapsed_time)
                timeout_embed = discord.Embed(
                    title="⏱️ TIEMPO AGOTADO - SISTEMA BLOQUEADO",
                    color=discord.Color.dark_red(),
                    description=(
                        f"```text\n{engine.render_ascii(path_coords=engine.optimal_path)}\n```\n"
                        f"🔒 **¡Bloqueo de seguridad activado! El tiempo ha expirado.**\n\n"
                        f"✨ **Ruta Óptima (`{engine.optimal_steps}` pasos):** Mostrada arriba con `{PATH_CHAR}`"
                    )
                )
                await interaction.edit_original_response(embed=timeout_embed)
        finally:
            self.active_hacks.discard(user_id)

    @hacking_group.command(name="tutorial", description="Manual detallado de instrucciones para el minijuego CyberHack.")
    async def tutorial_command(self, interaction: discord.Interaction):
        embed_main = discord.Embed(
            title="🎮 GUÍA OFICIAL DE INTRUSIÓN CYBERHACK",
            color=discord.Color.blue(),
            description=(
                "¡Bienvenido al sistema de intrusión de red! En este minijuego tomarás el control "
                "de una sonda de hackeo para infiltrarte en servidores y robar choskris.\n\n"
                "**¿Cómo empezar?**\n"
                "Usa el comando `/hack jugar` eligiendo la dificultad y el modo de juego.\n\n"
                "👇 **Utiliza el menú desplegable abajo para explorar los manuales detallados:**"
            )
        )

        view = TutorialView(author_id=interaction.user.id)
        await interaction.response.send_message(embed=embed_main, view=view)

    @tasks.loop(time=time(hour=0, minute=0, second=0))
    async def daily_reset_task(self):
        await self.bot.db.hacking_reset_daily()

    @daily_reset_task.before_loop
    async def before_daily_interest(self):
        await self.bot.wait_until_ready()


async def setup(bot: JoseLuisBot):
    await bot.add_cog(CyberHackCog(bot))