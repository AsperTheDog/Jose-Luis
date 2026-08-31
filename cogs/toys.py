import random
import re
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from main import JoseLuisBot


class ToysCog(commands.Cog):
    def __init__(self, bot: JoseLuisBot):
        self.bot = bot

    toys_group = app_commands.Group(
        name="juegos",
        description="Comandos de entretenimiento, dados y minijuegos"
    )

    eightball_group = app_commands.Group(
        name="8ball",
        description="Comandos de la bola 8 mágica",
        parent=toys_group
    )

    @eightball_group.command(name="pregunta", description="Hazle una pregunta a la Bola 8 Mágica.")
    @app_commands.describe(pregunta="La pregunta que quieres hacer a la bola 8")
    async def eightball_ask(self, interaction: discord.Interaction, pregunta: str):
        await interaction.response.defer()

        default_phrases = [
            ("Sí", "positive"),
            ("No", "negative"),
        ]

        phrases = await self.bot.db.eightball_get_all_phrases()
        if not phrases:
            phrase, category = random.choice(default_phrases)
        else:
            phrase, category = random.choice(phrases)

        colors = {
            "positive": discord.Color.green(),
            "neutral": discord.Color.gold(),
            "negative": discord.Color.red(),
        }

        embed = discord.Embed(
            title="🎱 Bola 8 Mágica",
            color=colors.get(category, discord.Color.purple())
        )
        embed.add_field(name="❓ Pregunta", value=pregunta, inline=False)
        embed.add_field(name="🔮 Respuesta", value=phrase, inline=False)
        embed.set_footer(text=f"Solicitado por {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

        await interaction.followup.send(embed=embed)

    @eightball_group.command(name="agregar", description="Añade una nueva frase a la Bola 8 (Operadores).")
    @app_commands.describe(
        frase="La frase de respuesta a agregar",
        tipo="Tipo de respuesta (Positiva, Neutral, Negativa)"
    )
    @app_commands.choices(tipo=[
        app_commands.Choice(name="🟢 Positiva", value="positive"),
        app_commands.Choice(name="🟡 Neutral", value="neutral"),
        app_commands.Choice(name="🔴 Negativa", value="negative")
    ])
    async def eightball_add(self, interaction: discord.Interaction, frase: str, tipo: str):
        if await self.bot.filter_operators(interaction): return

        await self.bot.db.eightball_add_phrase(frase, tipo)
        embed = discord.Embed(
            description=f"✅ Frase '{frase}' ({tipo}) añadida correctamente a la 8Ball  ",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @eightball_group.command(name="eliminar", description="Elimina una frase de la Bola 8 (Operadores).")
    @app_commands.describe(frase="La frase a eliminar", tipo="La categoría de la frase")
    @app_commands.choices(tipo=[
        app_commands.Choice(name="🟢 Positiva", value="positive"),
        app_commands.Choice(name="🟡 Neutral", value="neutral"),
        app_commands.Choice(name="🔴 Negativa", value="negative")
    ])
    async def eightball_remove(self, interaction: discord.Interaction, frase: int, tipo: str):
        if await self.bot.filter_operators(interaction): return

        deleted = await self.bot.db.eightball_remove_phrase(frase, tipo)
        if deleted:
            embed = discord.Embed(description=f"🗑️ Frase '{frase}' ({tipo}) eliminada de la 8Ball.", color=discord.Color.green())
        else:
            embed = discord.Embed(description=f"❌ No se encontró ninguna frase como esa.", color=discord.Color.red())

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @eightball_group.command(name="lista", description="Muestra las respuestas registradas en la Bola 8.")
    async def eightball_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        phrases = await self.bot.db.eightball_get_all_phrases()
        if not phrases:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ No hay frases personalizadas registradas en la base de datos.", color=discord.Color.red()),
                ephemeral=True
            )
            return

        lines = [f"[{cat.upper()}] {text}" for text, cat in phrases[:25]]
        embed = discord.Embed(
            title="📜 Frases registradas en la 8Ball",
            description="\n".join(lines),
            color=discord.Color.blurple()
        )
        if len(phrases) > 25:
            embed.set_footer(text=f"Mostrando 25 de {len(phrases)} frases totales.")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @toys_group.command(name="moneda", description="Lanza una moneda al aire (Cara o Cruz).")
    async def coin_flip(self, interaction: discord.Interaction):
        await interaction.response.defer()

        result = random.choice(["Cara", "Cruz"])
        emoji = "🪙" if result == "Cara" else "⚜️"

        embed = discord.Embed(
            title="🪙 Lanzamiento de Moneda",
            description=f"La moneda gira en el aire y cae en...\n\n# ¡**{result}**! {emoji}",
            color=discord.Color.gold()
        )
        await interaction.followup.send(embed=embed)

    @toys_group.command(name="tirardados", description="Lanza dados de rol estilo DnD (d4, d6, d8, d10, d12, d20, d100 o personalizado).")
    @app_commands.describe(
        tipo="Tipo de dado estándar de DnD",
        cantidad="Número de dados a lanzar (por defecto 1)",
        modificador="Modificador a añadir o restar al total (ej. +3 o -2)",
        formula_custom="Fórmula personalizada de dados (ej. '3d20+5' o '2d6'). Sobrescribe los otros campos."
    )
    @app_commands.choices(tipo=[
        app_commands.Choice(name="d4", value=4),
        app_commands.Choice(name="d6", value=6),
        app_commands.Choice(name="d8", value=8),
        app_commands.Choice(name="d10", value=10),
        app_commands.Choice(name="d12", value=12),
        app_commands.Choice(name="d20", value=20),
        app_commands.Choice(name="d100", value=100),
    ])
    async def roll_dice(
        self,
        interaction: discord.Interaction,
        tipo: int = 6,
        cantidad: int = 1,
        modificador: int = 0,
        formula_custom: Optional[str] = None
    ):
        await interaction.response.defer()

        num_dice = cantidad
        sides = tipo
        mod = modificador

        if formula_custom:
            match = re.match(r"^(\d+)?d(\d+)([+\-]\d+)?$", formula_custom.lower().strip())
            if not match:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="🎲 Lanzamiento de Dados",
                        description="❌ Formato de fórmula inválido. Usa formatos como `1d20`, `3d6+2` o `2d10-1`.",
                        color=discord.Color.red()
                    )
                )
                return
            num_dice = int(match.group(1)) if match.group(1) else 1
            sides = int(match.group(2))
            mod = int(match.group(3)) if match.group(3) else 0

        if num_dice < 1 or num_dice > 50:
            await interaction.followup.send(embed=discord.Embed(
                title="🎲 Lanzamiento de Dados",
                description="❌ La cantidad de dados debe estar entre 1 y 50.",
                color=discord.Color.red()
            ))
            return

        if sides < 2 or sides > 1000:
            await interaction.followup.send(embed=discord.Embed(
                title="🎲 Lanzamiento de Dados",
                description="❌ El número de caras del dado debe estar entre 2 y 1000.",
                color=discord.Color.red()
            ))
            return

        rolls = [random.randint(1, sides) for _ in range(num_dice)]
        total = sum(rolls) + mod

        rolls_str = ", ".join(map(str, rolls))
        if len(rolls_str) > 500:
            rolls_str = rolls_str[:500] + "..."

        mod_str = f" {'+' if mod >= 0 else ''}{mod}" if mod != 0 else ""
        title = f"🎲 Tirada: {num_dice}d{sides}{mod_str}"

        embed = discord.Embed(title=title, color=discord.Color.blue())
        embed.add_field(name="🎯 Resultados", value=f"`[{rolls_str}]`", inline=False)
        if mod != 0:
            embed.add_field(name="➕ Modificador", value=f"`{mod:+d}`", inline=True)
        embed.add_field(name="📊 Total", value=f"**{total}**", inline=True)

        if sides == 20 and num_dice == 1:
            if rolls[0] == 20:
                embed.description = "🔥 **¡ÉXITO CRÍTICO! (NAT 20)** 🔥"
                embed.colour = discord.Color.green()
            elif rolls[0] == 1:
                embed.description = "💀 **¡PIFIA CRÍTICA! (NAT 1)** 💀"
                embed.colour = discord.Color.red()

        await interaction.followup.send(embed=embed)

    @toys_group.command(name="piedrapapeltijeras", description="Juega a Piedra, Papel o Tijeras.")
    @app_commands.describe(eleccion="Tu jugada")
    @app_commands.choices(eleccion=[
        app_commands.Choice(name="🪨 Piedra", value="piedra"),
        app_commands.Choice(name="📄 Papel", value="papel"),
        app_commands.Choice(name="✂️ Tijeras", value="tijeras")
    ])
    async def rock_paper_scissors(self, interaction: discord.Interaction, eleccion: str):
        bot_choice = random.choice(["piedra", "papel", "tijeras"])
        emojis = {"piedra": "🪨", "papel": "📄", "tijeras": "✂️"}

        if eleccion == bot_choice:
            result = "¡Es un empate!"
            color = discord.Color.gold()
        elif (
            (eleccion == "piedra" and bot_choice == "tijeras") or
            (eleccion == "papel" and bot_choice == "piedra") or
            (eleccion == "tijeras" and bot_choice == "papel")
        ):
            result = "¡Has ganado! 🎉"
            color = discord.Color.green()
        else:
            result = "¡He ganado yo! 😈"
            color = discord.Color.red()

        embed = discord.Embed(title="🎮 Piedra, Papel o Tijeras", description=f"## {result}", color=color)
        embed.add_field(name="Tu elección", value=f"{emojis[eleccion]} {eleccion.capitalize()}", inline=True)
        embed.add_field(name="Mi elección", value=f"{emojis[bot_choice]} {bot_choice.capitalize()}", inline=True)

        await interaction.response.send_message(embed=embed)

    @toys_group.command(name="bofetada", description="Dale una bofetada a alguien en el servidor.")
    @app_commands.describe(usuario="El usuario al que quieres darle una bofetada", razon="Razón de la bofetada")
    async def slap(self, interaction: discord.Interaction, usuario: discord.User, razon: str = "porque sí"):
        if usuario.id == interaction.user.id:
            await interaction.response.send_message("❌ No te des bofetadas a ti mismo...", ephemeral=True)
            return

        slap_verbs = [
            "le ha dado una bofetada mesopotámica a",
            "le ha soltado un guantazo con una mano abierta a",
            "ha golpeado con una trucha fresca a",
            "le ha propinado un bofetón legendario a"
        ]
        verb = random.choice(slap_verbs)

        embed = discord.Embed(
            description=f"🖐️ {interaction.user.mention} {verb} {usuario.mention} **{razon}**!",
            color=discord.Color.dark_orange()
        )
        await interaction.response.send_message(content=usuario.mention, embed=embed)

    @toys_group.command(name="compatibilidad", description="Calcula el porcentaje de amor/compatibilidad entre dos usuarios.")
    @app_commands.describe(usuario1="Primer usuario", usuario2="Segundo usuario (opcional, por defecto tú)")
    async def love_calculator(self, interaction: discord.Interaction, usuario1: discord.User, usuario2: Optional[discord.User] = None):
        target1 = interaction.user if usuario2 is None else usuario1
        target2 = usuario1 if usuario2 is None else usuario2

        seed = target1.id + target2.id
        gen = random.Random(seed)
        percentage = gen.randint(0, 100)

        filled = int(percentage / 10)
        bar = "❤️" * filled + "🖤" * (10 - filled)

        if percentage > 85:
            msg = "💖 ¡Pareja perfecta! El destino los quiere juntos."
        elif percentage > 60:
            msg = "💕 Hay mucha química aquí."
        elif percentage > 30:
            msg = "💛 Podría funcionar con algo de esfuerzo."
        else:
            msg = "💔 Mejor ser solo conocidos..."

        embed = discord.Embed(
            title="💘 Medidor de Compatibilidad",
            description=f"**{target1.display_name}**  x  **{target2.display_name}**\n\n**{percentage}%** `[{bar}]`\n\n*{msg}*",
            color=discord.Color.pink()
        )
        await interaction.response.send_message(embed=embed)

    @toys_group.command(name="elegir", description="Elige al azar entre varias opciones separadas por comas.")
    @app_commands.describe(opciones="Opciones separadas por comas (ej. Pizza, Hamburguesa, Tacos)")
    async def choose(self, interaction: discord.Interaction, opciones: str):
        choices_list = [opt.strip() for opt in opciones.split(",") if opt.strip()]

        if len(choices_list) < 2:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Por favor, proporciona al menos 2 opciones separadas por comas.", color=discord.Color.red()),
                ephemeral=True
            )
            return

        selected = random.choice(choices_list)
        embed = discord.Embed(
            title="🤔 Elección Aleatoria",
            description=f"Entre las opciones proporcionadas, elijo:\n\n# 🎯 **{selected}**",
            color=discord.Color.teal()
        )
        embed.set_footer(text=f"Opciones evaluadas: {len(choices_list)}")
        await interaction.response.send_message(embed=embed)


async def setup(bot: JoseLuisBot):
    await bot.add_cog(ToysCog(bot))