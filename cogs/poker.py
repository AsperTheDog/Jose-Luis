import asyncio
import random
import itertools
from collections import Counter
from typing import List, Dict, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from main import JoseLuisBot

RANK_VALUES = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
SUITS = ['♠', '♥', '♦', '♣']
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']


def evaluate_hand(cards: List[str]) -> Tuple:
    parsed_cards = []
    for card in cards:
        suit = card[-1]
        rank = card[:-1]
        parsed_cards.append((RANK_VALUES[rank], suit))

    best_rank = (0,)
    for combo in itertools.combinations(parsed_cards, 5):
        combo = sorted(combo, key=lambda x: x[0], reverse=True)
        vals = [c[0] for c in combo]
        suits = [c[1] for c in combo]

        is_flush = len(set(suits)) == 1
        is_straight = False

        if len(set(vals)) == 5 and vals[0] - vals[-1] == 4:
            is_straight = True
        elif vals == [14, 5, 4, 3, 2]:
            is_straight = True
            vals = [5, 4, 3, 2, 1]

        counts = Counter(vals)
        counts_sorted = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)

        pattern = tuple(c[1] for c in counts_sorted)
        primary_vals = tuple(c[0] for c in counts_sorted)

        score = 0
        if is_straight and is_flush:
            score = 8
        elif pattern == (4, 1):
            score = 7
        elif pattern == (3, 2):
            score = 6
        elif is_flush:
            score = 5
        elif is_straight:
            score = 4
        elif pattern == (3, 1, 1):
            score = 3
        elif pattern == (2, 2, 1):
            score = 2
        elif pattern == (2, 1, 1, 1):
            score = 1
        else:
            score = 0

        current_rank = (score,) + primary_vals
        if current_rank > best_rank:
            best_rank = current_rank

    return best_rank


def format_score_name(score: int) -> str:
    names = {
        8: "Escalera de Color", 7: "Póker", 6: "Full House", 5: "Color",
        4: "Escalera", 3: "Trío", 2: "Doble Pareja", 1: "Pareja", 0: "Carta Alta"
    }
    return names.get(score, "Carta Alta")


class PlayerState:
    def __init__(self, user: discord.Member, stack: int):
        self.user = user
        self.stack = stack
        self.bet = 0
        self.total_invested = 0
        self.folded = False
        self.all_in = False
        self.hand = []


class PokerGame:
    def __init__(self, host: discord.Member, buy_in: int):
        self.host = host
        self.buy_in = buy_in
        self.players: List[PlayerState] = [PlayerState(host, buy_in)]

        self.deck = [f"{r}{s}" for s in SUITS for r in RANKS]
        random.shuffle(self.deck)

        self.community_cards = []
        self.pot = 0
        self.current_bet = 0

        self.phase = 0
        self.turn_idx = 0
        self.players_acted = 0

    def start_game(self):
        # Repartir 2 cartas a cada jugador
        for p in self.players:
            p.hand = [self.deck.pop(), self.deck.pop()]

    def active_players(self):
        return [p for p in self.players if not p.folded]

    def players_can_act(self):
        return [p for p in self.active_players() if not p.all_in]

    def current_player(self) -> PlayerState:
        return self.players[self.turn_idx]

    def advance_turn(self):
        self.players_acted += 1
        active = self.active_players()

        if len(active) == 1:
            self.phase = 4
            return

        can_act = self.players_can_act()
        if self.players_acted >= len(can_act):
            all_matched = all(p.bet == self.current_bet for p in can_act)
            if all_matched or len(can_act) <= 1:
                self.next_phase()
                return

        attempts = 0
        while attempts < len(self.players):
            self.turn_idx = (self.turn_idx + 1) % len(self.players)
            p = self.players[self.turn_idx]
            if not p.folded and not p.all_in:
                break
            attempts += 1

    def next_phase(self):
        for p in self.players:
            self.pot += p.bet
            p.bet = 0
        self.current_bet = 0
        self.players_acted = 0
        self.phase += 1

        if self.phase == 1:  # Flop
            self.community_cards.extend([self.deck.pop(), self.deck.pop(), self.deck.pop()])
        elif self.phase == 2:  # Turn
            self.community_cards.append(self.deck.pop())
        elif self.phase == 3:  # River
            self.community_cards.append(self.deck.pop())

        if self.phase == 4:
            return

        self.turn_idx = 0
        while self.players[self.turn_idx].folded or self.players[self.turn_idx].all_in:
            self.turn_idx = (self.turn_idx + 1) % len(self.players)
            if self.turn_idx == 0: break


class RaiseModal(discord.ui.Modal, title='Subir Apuesta'):
    amount_input = discord.ui.TextInput(
        label='Cantidad a subir (Choskris)',
        placeholder='Ej: 500',
        required=True,
        min_length=1,
        max_length=10,
        style=discord.TextStyle.short
    )

    def __init__(self, view_ref: 'PokerTableControl'):
        super().__init__()
        self.view_ref = view_ref

    async def on_submit(self, interaction: discord.Interaction):
        game = self.view_ref.game
        p = game.current_player()

        try:
            raise_amount = int(self.amount_input.value)
        except ValueError:
            await interaction.response.send_message("Por favor, introduce un número válido.", ephemeral=True)
            return

        if raise_amount <= 0:
            await interaction.response.send_message("La subida debe ser mayor a 0.", ephemeral=True)
            return

        to_call = game.current_bet - p.bet
        total_needed = to_call + raise_amount

        if total_needed > p.stack:
            await interaction.response.send_message(f"No tienes suficientes fichas. Tu stack es **{p.stack}**.", ephemeral=True)
            return

        p.stack -= total_needed
        p.bet += total_needed
        game.current_bet = p.bet

        game.players_acted = 0

        if p.stack == 0:
            p.all_in = True

        game.advance_turn()
        msg = f"📈 **{interaction.user.display_name}** sube la apuesta a (`{game.current_bet}`)."
        await self.view_ref.update_table(interaction, msg)


class PokerTableControl(discord.ui.View):
    def __init__(self, game: PokerGame, bot):
        super().__init__(timeout=None)
        self.game = game
        self.bot = bot

    def format_cards(self, cards: List[str]) -> str:
        if not cards:
            return "` 🎴 ` ` 🎴 ` ` 🎴 ` ` 🎴 ` ` 🎴 `"
        return " ".join([f"` {c} `" for c in cards])

    def build_embed(self) -> discord.Embed:
        phases = [
            "Pre-Flop (Reparto)",
            "Flop (3 cartas)",
            "Turn (4ª carta)",
            "River (5ª carta)",
            "Showdown"
        ]
        colors = [
            discord.Color.blue(),
            discord.Color.green(),
            discord.Color.gold(),
            discord.Color.orange(),
            discord.Color.red()
        ]

        embed = discord.Embed(title=f"🎰 Texas Hold'em  |  Fase: {phases[self.game.phase]}", color=colors[self.game.phase])
        total_pot = self.game.pot + sum(p.bet for p in self.game.players)

        comm_cards_visual = self.format_cards(self.game.community_cards)
        embed.description = (
            f"### 💰 Bote Total: `{total_pot:,}` choskris\n"
            f"**Apuesta a igualar:** 🪙 `{self.game.current_bet:,}`\n\n"
            f"**Cartas Comunitarias:**\n{comm_cards_visual}\n"
            f"──────────────────────────────"
        )

        for p in self.game.players:
            if p.folded:
                status = "❌ *Se ha retirado*"
            elif p.all_in:
                status = f"🔥 **ALL-IN** (Total invertido: `{p.total_invested:,}`)"
            else:
                status = f"🪙 Stack: `{p.stack:,}` | 💵 Apuesta ronda: `{p.bet:,}`"

            is_turn = p.user.id == self.game.current_player().user.id and not p.folded and self.game.phase < 4
            turn_indicator = "🔴 **[ES SU TURNO]**" if is_turn else ""

            embed.add_field(
                name=f"👤 {p.user.display_name} {turn_indicator}",
                value=status,
                inline=False
            )

        return embed

    async def update_table(self, interaction: discord.Interaction, status_msg: str = ""):
        if self.game.phase == 4:
            await self.end_game(interaction)
            return

        embed = self.build_embed()

        current_p_mention = self.game.current_player().user.mention
        content = ""
        if status_msg:
            content += f"> 📢 **Última Acción:** {status_msg}\n\n"
        content += f"👉 **¡Te toca jugar, {current_p_mention}!**"

        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(content=content, embed=embed, view=self)
            else:
                await interaction.edit_original_response(content=content, embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.message.edit(content=content, embed=embed, view=self)

    @discord.ui.button(label="Ver mis Cartas", style=discord.ButtonStyle.secondary, emoji="👁️", row=0)
    async def view_cards(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = next((p for p in self.game.players if p.user.id == interaction.user.id), None)
        if not p or not p.hand:
            await interaction.response.send_message("No tienes cartas asignadas.", ephemeral=True)
            return

        cards_visual = self.format_cards(p.hand)
        await interaction.response.send_message(f"🤫 **Tus cartas ocultas:** {cards_visual}", ephemeral=True)

    @discord.ui.button(label="Pasar / Igualar", style=discord.ButtonStyle.success, row=1)
    async def call_check(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.game.current_player()
        if interaction.user.id != p.user.id:
            await interaction.response.send_message("❌ No es tu turno.", ephemeral=True)
            return

        to_call = self.game.current_bet - p.bet

        if to_call > 0:
            pay_amount = min(to_call, p.stack)
            p.stack -= pay_amount
            p.bet += pay_amount
            p.total_invested += pay_amount

            if p.stack == 0:
                p.all_in = True
                msg = f"🔥 **{interaction.user.display_name}** va **ALL-IN** con `{p.bet:,}` choskris."
            else:
                msg = f"🪙 **{interaction.user.display_name}** iguala la apuesta (`{pay_amount:,}`)."

        else:
            if p.stack == 0:
                p.all_in = True
                msg = f"🔥 **{interaction.user.display_name}** está **ALL-IN** (`{p.bet:,}`)."
            else:
                msg = f"✅ **{interaction.user.display_name}** pasa la mano (Check)."

        self.game.advance_turn()
        await self.update_table(interaction, msg)

    @discord.ui.button(label="Subir (Raise)", style=discord.ButtonStyle.primary, row=1)
    async def raise_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.game.current_player()
        if interaction.user.id != p.user.id:
            await interaction.response.send_message("❌ No es tu turno.", ephemeral=True)
            return

        if p.stack <= 0:
            await interaction.response.send_message("Estás All-In, no puedes subir.", ephemeral=True)
            return

        await interaction.response.send_modal(RaiseModal(self))

    @discord.ui.button(label="Retirarse (Fold)", style=discord.ButtonStyle.danger, row=1)
    async def fold(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.game.current_player()
        if interaction.user.id != p.user.id:
            await interaction.response.send_message("❌ No es tu turno.", ephemeral=True)
            return

        p.folded = True
        msg = f"🏳️ **{interaction.user.display_name}** se ha retirado."
        self.game.advance_turn()
        await self.update_table(interaction, msg)

    async def end_game(self, interaction: discord.Interaction):
        self.stop()

        for p in self.game.players:
            self.game.pot += p.bet
            p.bet = 0

        active = self.game.active_players()

        embed = discord.Embed(title="🏆 ¡Showdown! Fin de la Partida", color=discord.Color.red())
        comm_cards = self.format_cards(self.game.community_cards) if self.game.community_cards else "`Ninguna`"
        embed.add_field(name="Cartas Comunitarias", value=comm_cards, inline=False)

        if len(active) == 1:
            winner = active[0]
            embed.description = f"🎉 {winner.user.mention} gana el bote de 💰 **`{self.game.pot:,}`** choskris por abandono."
            winner.stack += self.game.pot
        else:
            best_score = None
            winners = []
            results_text = []

            for p in active:
                full_hand = p.hand + self.game.community_cards
                score_tuple = evaluate_hand(full_hand)
                hand_name = format_score_name(score_tuple[0])
                p_cards = self.format_cards(p.hand)
                results_text.append(f"👤 **{p.user.display_name}**: {p_cards} ➔ *{hand_name}*")

                if best_score is None or score_tuple > best_score:
                    best_score = score_tuple
                    winners = [p]
                elif score_tuple == best_score:
                    winners.append(p)

            embed.add_field(name="Manos Reveladas", value="\n".join(results_text), inline=False)

            win_amount = self.game.pot // len(winners)
            win_mentions = " y ".join(w.user.mention for w in winners)
            embed.description = f"### 🎉 ¡Ganador: {win_mentions}!\nSe lleva(n) 💰 **`{win_amount:,}`** choskris con **{format_score_name(best_score[0])}**."

            for w in winners:
                w.stack += win_amount

        refunds_text = []
        for p in self.game.players:
            if p.stack > 0:
                await self.bot.db.poker_add_balance(p.user.id, p.stack)
                net_change = p.stack - self.game.buy_in
                sign = "+" if net_change >= 0 else ""
                refunds_text.append(f"• **{p.user.display_name}**: Devueltos `{p.stack:,}` ({sign}{net_change})")

        embed.add_field(name="Resumen de Stacks Deueltos", value="\n".join(refunds_text), inline=False)

        content = "🏁 **¡La partida ha finalizado!**"

        if not interaction.response.is_done():
            await interaction.response.edit_message(content=content, embed=embed, view=None)
        else:
            await interaction.edit_original_response(content=content, embed=embed, view=None)


class PokerLobbyView(discord.ui.View):
    def __init__(self, game: PokerGame, bot):
        super().__init__(timeout=300.0)
        self.game = game
        self.bot = bot

    @discord.ui.button(label="Unirse a la Mesa", style=discord.ButtonStyle.primary, emoji="🎲")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if any(p.user.id == interaction.user.id for p in self.game.players):
            await interaction.response.send_message("Ya estás en la sala.", ephemeral=True)
            return

        if len(self.game.players) >= 6:
            await interaction.response.send_message("La mesa está llena (Max 6).", ephemeral=True)
            return

        balance = await self.bot.db.poker_get_balance(interaction.user.id)
        if balance < self.game.buy_in:
            await interaction.response.send_message(
                f"No tienes choskris suficientes (**{self.game.buy_in:,}** requeridos).", ephemeral=True)
            return

        success = await self.bot.db.poker_remove_balance(interaction.user.id, self.game.buy_in)
        if not success:
            await interaction.response.send_message("Hubo un error procesando tu saldo.", ephemeral=True)
            return

        self.game.players.append(PlayerState(interaction.user, self.game.buy_in))

        embed = interaction.message.embeds[0]
        players_fmt = "\n".join([f"• {p.user.mention}" for p in self.game.players])
        embed.set_field_at(1, name=f"Jugadores ({len(self.game.players)}/6)", value=players_fmt, inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Empezar Partida", style=discord.ButtonStyle.success, emoji="▶️")
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host.id:
            await interaction.response.send_message("Solo el creador puede iniciar la partida.", ephemeral=True)
            return

        if len(self.game.players) < 2:
            await interaction.response.send_message("Se necesitan al menos 2 jugadores.", ephemeral=True)
            return

        self.stop()
        self.game.start_game()

        table_view = PokerTableControl(self.game, self.bot)
        embed = table_view.build_embed()
        await interaction.response.edit_message(embed=embed, view=table_view)

class PokerCog(commands.Cog):
    def __init__(self, bot: JoseLuisBot):
        self.bot = bot
        self.active_channels = set()

    poker_group = app_commands.Group(name="poker", description="Juegos de póker (Texas Hold'em) de Casino")

    @poker_group.command(name="crear", description="Crea una mesa de póker multijugador.")
    @app_commands.describe(buy_in="Fichas requeridas para entrar (Stack inicial)")
    async def crear_poker(self, interaction: discord.Interaction, buy_in: int):
        await interaction.response.defer()

        if buy_in < 100:
            await interaction.followup.send("La entrada mínima es de 100 choskris.")
            return

        balance = await self.bot.db.poker_get_balance(interaction.user.id)
        if balance < buy_in:
            await interaction.followup.send(f"No tienes fondos suficientes (**{buy_in:,}** requeridos). Tienes **{balance:,}**.")
            return

        await self.bot.db.poker_remove_balance(interaction.user.id, buy_in)

        game = PokerGame(host=interaction.user, buy_in=buy_in)

        embed = discord.Embed(
            title="♠️ Sala de Texas Hold'em",
            description=f"{interaction.user.mention} ha abierto una mesa. ¡Únete antes de que empiece!",
            color=discord.Color.gold()
        )
        embed.add_field(name="Buy-in (Entrada)", value=f"💰 **{buy_in:,}** choskris", inline=False)
        embed.add_field(name="Jugadores (1/6)", value=f"• {interaction.user.mention}", inline=False)

        view = PokerLobbyView(game, self.bot)
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot: JoseLuisBot):
    await bot.add_cog(PokerCog(bot))