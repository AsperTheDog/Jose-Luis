import itertools
import random
from typing import Optional, List, Tuple, Counter

import discord
from discord import app_commands
from discord.ext import commands

from main import JoseLuisBot

SYMBOLS = {
    "🍒": {"weight": 45, "payout_3": 3.0, "payout_2": 0.5},
    "🍋": {"weight": 28, "payout_3": 5.0, "payout_2": 1.0},
    "🔔": {"weight": 15, "payout_3": 12.0, "payout_2": 1.2},
    "💎": {"weight": 8, "payout_3": 30.0, "payout_2": 2.0},
    "7️⃣": {"weight": 4, "payout_3": 100.0, "payout_2": 4.0},
}


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


class MayorMenorView(discord.ui.View):
    def __init__(self, user: discord.User, bet_amount: int, bot):
        super().__init__(timeout=60)
        self.user = user
        self.bet = bet_amount
        self.current_win = bet_amount
        self.bot = bot
        self.streak = 0

        self.current_card = random.randint(1, 13)
        self.deck_names = {1: "A", 11: "J", 12: "Q", 13: "K"}

        self.stop_game.disabled = True

    def get_card_name(self, value: int) -> str:
        return self.deck_names.get(value, str(value))

    def calculate_multipliers(self, card_val: int):
        higher_prob = (13 - card_val) / 13.0
        lower_prob = (card_val - 1) / 13.0

        mult_higher = min(5.0, max(1.05, round((1 / higher_prob) * 0.85, 2))) if higher_prob > 0 else 0
        mult_lower = min(5.0, max(1.05, round((1 / lower_prob) * 0.85, 2))) if lower_prob > 0 else 0

        return mult_higher, mult_lower

    def update_button_labels(self):
        mult_higher, mult_lower = self.calculate_multipliers(self.current_card)

        if mult_higher > 0:
            self.mayor.label = f"Mayor (x{mult_higher})"
            self.mayor.disabled = False
        else:
            self.mayor.label = "Mayor (Imposible)"
            self.mayor.disabled = True

        if mult_lower > 0:
            self.menor.label = f"Menor (x{mult_lower})"
            self.menor.disabled = False
        else:
            self.menor.label = "Menor (Imposible)"
            self.menor.disabled = True

        if self.streak >= 2:
            self.stop_game.disabled = False
            self.stop_game.label = f"💰 Retirarse ({self.current_win:,} choskris)"
        else:
            self.stop_game.disabled = True
            self.stop_game.label = f"🔒 Retirarse (Racha: {self.streak}/2)"

    async def update_embed(self, interaction: discord.Interaction, result_msg: str):
        self.update_button_labels()

        embed = discord.Embed(
            title="🃏 Mayor o Menor (Modo Desafío)",
            description=f"Carta actual: **[{self.get_card_name(self.current_card)}]**",
            color=discord.Color.gold()
        )
        embed.add_field(name="💰 Acumulado", value=f"`{self.current_win:,}` choskris", inline=True)
        embed.add_field(name="🔥 Racha", value=f"`{self.streak}` aciertos", inline=True)
        embed.set_footer(text=result_msg)

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Mayor", style=discord.ButtonStyle.success)
    async def mayor(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ No es tu partida.", color=discord.Color.red()),
                ephemeral=True
            )
            return

        mult_higher, _ = self.calculate_multipliers(self.current_card)
        next_card = self.current_card
        while next_card == self.current_card:
            next_card = random.randint(1, 13)

        if next_card > self.current_card:
            self.streak += 1
            self.current_win = int(self.current_win * mult_higher)
            self.current_card = next_card
            await self.update_embed(interaction, f"✅ ¡Correcto! Salió un {self.get_card_name(next_card)}.")
        else:
            await self.end_game(interaction, won=False, card=next_card)

    @discord.ui.button(label="Menor", style=discord.ButtonStyle.danger)
    async def menor(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ No es tu partida.", color=discord.Color.red()),
                ephemeral=True
            )
            return

        _, mult_lower = self.calculate_multipliers(self.current_card)
        next_card = self.current_card
        while next_card == self.current_card:
            next_card = random.randint(1, 13)

        if next_card < self.current_card:
            self.streak += 1
            self.current_win = int(self.current_win * mult_lower)
            self.current_card = next_card
            await self.update_embed(interaction, f"✅ ¡Correcto! Salió un {self.get_card_name(next_card)}.")
        else:
            await self.end_game(interaction, won=False, card=next_card)

    @discord.ui.button(label="🔒 Retirarse", style=discord.ButtonStyle.primary)
    async def stop_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ No es tu partida.", color=discord.Color.red()),
                ephemeral=True
            )
            return

        await self.end_game(interaction, won=True)

    async def end_game(self, interaction: discord.Interaction, won: bool, card: int = None):
        self.stop()
        for child in self.children:
            child.disabled = True

        if won:
            await self.bot.global_stats.register_cards_win(self.user.id, self.current_win, self.bet)
            await self.bot.db.economy_update_balance(self.user.id, self.current_win)
            msg = f"🏆 **{self.user.display_name}** se retira con **{self.current_win:,}** choskris tras {self.streak} aciertos."
            embed_color = discord.Color.green()
            title = "¡Victoria!"
        else:
            await self.bot.global_stats.register_cards_loss(self.user.id, self.bet)
            reason = "Empate" if card == self.current_card else f"Salió un {self.get_card_name(card)}"
            msg = f"💥 **{self.user.display_name}** falló. ({reason}). Ha perdido la apuesta."
            embed_color = discord.Color.red()
            title = "¡Mala suerte!"

        await interaction.response.edit_message(content=None, embed=discord.Embed(title=title, description=msg, color=embed_color), view=self)


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

        embed.add_field(name="Resumen de Stacks Devueltos", value="\n".join(refunds_text), inline=False)

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
        self.message: discord.Message | None = None

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

    async def on_timeout(self):
        self.stop()

        refunds_text = []
        for p in self.game.players:
            await self.bot.db.poker_add_balance(p.user.id, self.game.buy_in)
            refunds_text.append(f"• {p.user.mention}: Devueltos `{p.game.buy_in:,}` choskris")

        embed = discord.Embed(
            title="⏳ Sala Cancelada por Inactividad",
            description="La sala de Texas Hold'em ha expirado porque la partida no se inició a tiempo.",
            color=discord.Color.red()
        )
        if refunds_text:
            embed.add_field(
                name="💰 Reembolsos Realizados",
                value="\n".join(refunds_text),
                inline=False
            )

        mentions = " ".join(p.user.mention for p in self.game.players)
        content = f"⚠️ {mentions} La partida fue cancelada por inactividad." if mentions else ""

        if self.message:
            try:
                await self.message.edit(content=content, embed=embed, view=None)
            except discord.HTTPException:
                pass


class BlackjackCard:
    def __init__(self, rank: str, suit: str, value: int):
        self.rank = rank
        self.suit = suit
        self.value = value

    def __str__(self):
        return f"{self.rank}{self.suit}"


class BlackjackView(discord.ui.View):
    def __init__(self, user: discord.User, bet: int, bot):
        super().__init__(timeout=90)
        self.user = user
        self.bet = bet
        self.bot = bot
        self.total_bet = bet

        # Create a realistic 6-deck shoe using standard Unicode suit symbols (matching Poker)
        suits = ['♠', '♥', '♦', '♣']
        ranks = [
            ("2", 2), ("3", 3), ("4", 4), ("5", 5), ("6", 6),
            ("7", 7), ("8", 8), ("9", 9), ("10", 10),
            ("J", 10), ("Q", 10), ("K", 10), ("A", 11)
        ]
        self.deck: list[BlackjackCard] = [
            BlackjackCard(r, s, v) for _ in range(6) for s in suits for r, v in ranks
        ]
        random.shuffle(self.deck)

        self.player_hand: list[BlackjackCard] = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand: list[BlackjackCard] = [self.deck.pop(), self.deck.pop()]

    @staticmethod
    def calculate_score(hand: list[BlackjackCard]) -> tuple[int, bool]:
        """Returns total score and whether the hand is 'soft' (contains active Ace as 11)."""
        total = sum(card.value for card in hand)
        aces = sum(1 for card in hand if card.rank == "A")

        while total > 21 and aces > 0:
            total -= 10
            aces -= 1

        is_soft = aces > 0 and total <= 21
        return total, is_soft

    def format_hand(self, hand: list[BlackjackCard], hide_second: bool = False) -> str:
        if hide_second:
            return f"` {hand[0]} ` ` 🎴 ` *(Total: **{hand[0].value}**)*"

        score, is_soft = self.calculate_score(hand)
        cards_str = " ".join([f"` {card} `" for card in hand])
        soft_str = " (Suave)" if is_soft else ""
        return f"{cards_str} *(Total: **{score}**{soft_str})*"

    def is_blackjack(self, hand: list[BlackjackCard]) -> bool:
        return len(hand) == 2 and self.calculate_score(hand)[0] == 21

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ No puedes jugar en la partida de otro usuario.", color=discord.Color.red()),
                ephemeral=True
            )
            return False
        return True

    async def update_board(self, interaction: discord.Interaction, title: str = "🃏 Blackjack (21)", color: discord.Color = discord.Color.blue()):
        embed = discord.Embed(title=title, color=color)
        embed.description = f"💰 **Apuesta en mesa:** `{self.total_bet:,}` choskris\n──────────────────────────────"
        embed.add_field(name="👤 Tu Mano", value=self.format_hand(self.player_hand), inline=False)
        embed.add_field(name="🎰 Mano del Crupier", value=self.format_hand(self.dealer_hand, hide_second=True), inline=False)

        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Pedir", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Double down is only available on first turn
        self.double_down.disabled = True

        self.player_hand.append(self.deck.pop())
        p_score, _ = self.calculate_score(self.player_hand)

        if p_score > 21:
            await self.end_game(interaction, result_type="bust")
        elif p_score == 21:
            await self.stand_logic(interaction)
        else:
            await self.update_board(interaction)

    @discord.ui.button(label="Plantarse", style=discord.ButtonStyle.success, emoji="🛑")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.stand_logic(interaction)

    @discord.ui.button(label="Doblar", style=discord.ButtonStyle.danger, emoji="🪙")
    async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_balance = await self.bot.db.economy_get_balance(self.user.id)
        if user_balance < self.bet:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ No tienes suficiente saldo para doblar la apuesta.", color=discord.Color.red()),
                ephemeral=True
            )
            return

        # Deduct extra bet for double down
        await self.bot.db.economy_update_balance(self.user.id, -self.bet)
        self.total_bet += self.bet

        self.player_hand.append(self.deck.pop())
        p_score, _ = self.calculate_score(self.player_hand)

        if p_score > 21:
            await self.end_game(interaction, result_type="bust")
        else:
            await self.stand_logic(interaction)

    async def stand_logic(self, interaction: discord.Interaction):
        # Dealer draws until reaching 17 or higher
        while True:
            d_score, _ = self.calculate_score(self.dealer_hand)
            if d_score >= 17:
                break
            self.dealer_hand.append(self.deck.pop())

        p_score, _ = self.calculate_score(self.player_hand)
        d_score, _ = self.calculate_score(self.dealer_hand)

        if d_score > 21:
            await self.end_game(interaction, result_type="dealer_bust")
        elif p_score > d_score:
            await self.end_game(interaction, result_type="win")
        elif p_score < d_score:
            await self.end_game(interaction, result_type="loss")
        else:
            await self.end_game(interaction, result_type="push")

    async def end_game(self, interaction: discord.Interaction, result_type: str):
        self.stop()
        for child in self.children:
            child.disabled = True

        payout = 0
        p_score, _ = self.calculate_score(self.player_hand)
        d_score, _ = self.calculate_score(self.dealer_hand)

        if result_type == "natural_bj":
            payout = int(self.total_bet * 2.5)  # 3:2 payout on Natural Blackjack
            title = "🎉 ¡BLACKJACK NATURAL!"
            description = f"¡Obtuviste un Blackjack natural! Cobras **`{payout:,}`** choskris (pago 3:2)."
            color = discord.Color.gold()
            await self.bot.global_stats.register_cards_win(self.user.id, payout, self.total_bet)
            await self.bot.global_stats.register_blackjack_win(self.user.id, payout, self.total_bet, natural=True)

        elif result_type == "dealer_bust":
            payout = self.total_bet * 2
            title = "🏆 ¡VICTORIA!"
            description = f"El crupier se ha pasado de 21 (**{d_score}**). ¡Ganas **`{payout:,}`** choskris!"
            color = discord.Color.green()
            await self.bot.global_stats.register_cards_win(self.user.id, payout, self.total_bet)
            await self.bot.global_stats.register_blackjack_win(self.user.id, payout, self.total_bet)

        elif result_type == "win":
            payout = self.total_bet * 2
            title = "🏆 ¡VICTORIA!"
            description = f"Tu mano (**{p_score}**) supera a la del crupier (**{d_score}**). ¡Ganas **`{payout:,}`** choskris!"
            color = discord.Color.green()
            await self.bot.global_stats.register_cards_win(self.user.id, payout, self.total_bet)
            await self.bot.global_stats.register_blackjack_win(self.user.id, payout, self.total_bet)

        elif result_type == "push":
            payout = self.total_bet  # Return original stake
            title = "🤝 EMPATE (PUSH)"
            description = f"Ambos tienen **{p_score}**. Se te devuelven tus **`{payout:,}`** choskris."
            color = discord.Color.gold()
            await self.bot.global_stats.register_blackjack_push(self.user.id, self.total_bet)

        elif result_type == "bust":
            title = "💥 TE HAS PASADO"
            description = f"Te has pasado de 21 (**{p_score}**). Pierdes tu apuesta de **`{self.total_bet:,}`** choskris."
            color = discord.Color.red()
            await self.bot.global_stats.register_cards_loss(self.user.id, self.total_bet)
            await self.bot.global_stats.register_blackjack_loss(self.user.id, self.total_bet)

        else:  # loss
            title = "❌ DERROTA"
            description = f"La mano del crupier (**{d_score}**) supera a la tuya (**{p_score}**). Pierdes **`{self.total_bet:,}`** choskris."
            color = discord.Color.red()
            await self.bot.global_stats.register_cards_loss(self.user.id, self.total_bet)
            await self.bot.global_stats.register_blackjack_loss(self.user.id, self.total_bet)

        if payout > 0:
            await self.bot.db.economy_update_balance(self.user.id, payout)

        current_balance = await self.bot.db.economy_get_balance(self.user.id)
        description += f"\n\n💰 Saldo actual: **`{current_balance:,}`** choskris\n──────────────────────────────"

        embed = discord.Embed(title=title, description=description, color=color)
        embed.add_field(name="👤 Tu Mano", value=self.format_hand(self.player_hand), inline=False)
        embed.add_field(name="🎰 Mano del Crupier", value=self.format_hand(self.dealer_hand, hide_second=False), inline=False)

        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.followup.send(embed=embed)


class CasinoCog(commands.Cog):
    casino_group = app_commands.Group(
        name="casino",
        description="Comandos para jugar juegos de azar"
    )

    def __init__(self, bot: JoseLuisBot):
        self.bot = bot
        self.active_channels = set()

    @casino_group.command(name="ruleta", description="Juega a la ruleta. Puedes apostar a color, a número, o a ambos (ej. 0 Verde o 17 Negro).")
    @app_commands.describe(
        apuesta="Cantidad de choskris a apostar",
        color="Color al que quieres apostar (Rojo, Negro o Verde)",
        numero="Número específico al que quieres apostar (0 a 36)"
    )
    @app_commands.choices(color=[
        app_commands.Choice(name="🔴 Rojo", value="rojo"),
        app_commands.Choice(name="⚫ Negro", value="negro"),
        app_commands.Choice(name="🟢 Verde", value="verde")
    ])
    async def spin(self, interaction: discord.Interaction, apuesta: int, color: Optional[str] = None, numero: Optional[int] = None):
        await interaction.response.defer()

        phrase = await self.bot.db.global_get_random_phrase("gamble", "error")
        if apuesta <= 0:
            await interaction.followup.send(embed=discord.Embed(title="🎡 Ruleta", description=f"{phrase}La apuesta debe ser mayor a 0.", color=discord.Color.red()))
            return

        if color is None and numero is None:
            await interaction.followup.send(embed=discord.Embed(title="🎡 Ruleta", description=f"{phrase}Debes elegir al menos una opción: un color, un número, o ambos.", color=discord.Color.red()))
            return

        if numero is not None and not (0 <= numero <= 36):
            await interaction.followup.send(embed=discord.Embed(title="🎡 Ruleta", description=f"{phrase}El número debe estar entre 0 y 36.", color=discord.Color.red()))
            return

        user_data = await self.bot.db.economy_get_user_data(interaction.user.id)
        if user_data['balance'] < apuesta:
            await interaction.followup.send(embed=discord.Embed(title="🎡 Ruleta", description=f"{phrase}No tienes suficiente choskris para esta apuesta.", color=discord.Color.red()))
            return

        is_let_it_ride = (numero == 17 and color == "negro")

        resultado_num = random.randint(0, 36)
        es_rojo = resultado_num in [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]

        if resultado_num == 0:
            resultado_color = "verde"
            color_emoji = "🟢 Verde"
        elif es_rojo:
            resultado_color = "rojo"
            color_emoji = "🔴 Rojo"
        else:
            resultado_color = "negro"
            color_emoji = "⚫ Negro"

        acerto_color = (color is not None and color == resultado_color)
        acerto_numero = (numero is not None and numero == resultado_num)

        multiplier = 0
        pago_descripcion = ""

        if color is not None and numero is not None:
            if acerto_color and acerto_numero:
                multiplier = 70
                pago_descripcion = "¡Pleno Combinado!"
        elif numero is not None:
            if acerto_numero:
                multiplier = 36
                pago_descripcion = "¡Pleno al Número!"
        elif color is not None:
            if acerto_color:
                if color == "verde":
                    multiplier = 36
                    pago_descripcion = "¡Acierto en Verde!"
                else:
                    multiplier = 2
                    pago_descripcion = "¡Acierto de Color!"

        prefix_msg = "**¡LET IT RIDE!**\n" if is_let_it_ride else ""

        if multiplier > 0:
            prize = apuesta * multiplier
            await self.bot.db.economy_update_balance(interaction.user.id, prize - apuesta)
            await self.bot.global_stats.register_roulette_win(interaction.user.id, prize, apuesta)

            phrase = await self.bot.db.global_get_random_phrase("spin", "success")

            msg = f"{prefix_msg}{phrase}La bola cayó en **{resultado_num} {color_emoji}**.\n🎉 **{pago_descripcion}** Has ganado **{int(prize)}** choskris."

            current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
            msg += f"\n💰 Saldo actual: **{current_balance}**"

            await interaction.followup.send(
                embed=discord.Embed(
                    title="🎡 Ruleta",
                    description=msg,
                    color=discord.Color.green()
                )
            )
        else:
            phrase = await self.bot.db.global_get_random_phrase("spin", "fail")
            cashback_pct = await self.bot.db.get_user_job_perk(interaction.user.id, "gambling_cashback", 0.0)
            loss = int(apuesta * (1 - cashback_pct))
            await self.bot.db.economy_update_balance(interaction.user.id, -loss)
            await self.bot.global_stats.register_roulette_loss(interaction.user.id, apuesta)

            msg = f"{prefix_msg}{phrase}La bola cayó en **{resultado_num} {color_emoji}**.\n❌ Perdiste **{apuesta}** choskris."
            if cashback_pct > 0:
                msg += f" (-**{apuesta - loss}** cashback)"

            current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
            msg += f"\n💰 Saldo actual: **{current_balance}**"

            await interaction.followup.send(embed=discord.Embed(title="Ruleta", description=msg, color=discord.Color.red()))

    @casino_group.command(name="dados", description="Lanza dos dados de 6 caras. Apuesta a suma exacta, alta/baja/7 o par/impar.")
    @app_commands.describe(
        apuesta="Cantidad de choskris a apostar",
        modalidad="Tipo de apuesta (Alta/Baja/7, Par/Impar o Suma Exacta)",
        suma_exacta="Si elegiste 'Suma Exacta', especifica el número objetivo (2 al 12)"
    )
    @app_commands.choices(modalidad=[
        app_commands.Choice(name="Baja (2-6) - Paga 2x", value="baja"),
        app_commands.Choice(name="Siete Exacto (7) - Paga 5x", value="siete"),
        app_commands.Choice(name="Alta (8-12) - Paga 2x", value="alta"),
        app_commands.Choice(name="Par - Paga 2x", value="par"),
        app_commands.Choice(name="Impar - Paga 2x", value="impar"),
        app_commands.Choice(name="Suma Exacta (Especificar número abajo)", value="exacta")
    ])
    async def dice(self, interaction: discord.Interaction, apuesta: int, modalidad: str, suma_exacta: Optional[int] = None):
        await interaction.response.defer()

        phrase = await self.bot.db.global_get_random_phrase("gamble", "error")
        if apuesta <= 0:
            await interaction.followup.send(embed=discord.Embed(title="🎲 Dados", description=f"{phrase}La apuesta debe ser mayor a 0.", color=discord.Color.red()))
            return

        if modalidad == "exacta":
            if suma_exacta is None or not (2 <= suma_exacta <= 12):
                await interaction.followup.send(embed=discord.Embed(title="🎲 Dados", description=f"{phrase}Para la modalidad 'Suma Exacta', debes indicar un número entre 2 y 12 en el campo `suma_exacta`.", color=discord.Color.red()))
                return

        user_data = await self.bot.db.economy_get_user_data(interaction.user.id)
        if user_data['balance'] < apuesta:
            await interaction.followup.send(embed=discord.Embed(title="🎲 Dados", description=f"{phrase}No tienes suficiente choskris para esta apuesta.", color=discord.Color.red()))
            return

        dado1 = random.randint(1, 6)
        dado2 = random.randint(1, 6)
        total = dado1 + dado2

        dice_emojis = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
        d1_str = dice_emojis[dado1]
        d2_str = dice_emojis[dado2]

        multiplier = 0
        pago_descripcion = ""

        if modalidad == "exacta":
            if total == suma_exacta:
                payout_table = {2: 30, 12: 30, 3: 15, 11: 15, 4: 10, 10: 10, 5: 7, 9: 7, 6: 5, 8: 5, 7: 5}
                multiplier = payout_table.get(suma_exacta, 5)
                pago_descripcion = f"¡Acierto exacto de **{suma_exacta}**!"

        elif modalidad == "baja" and 2 <= total <= 6:
            multiplier = 2
            pago_descripcion = "¡Acierto en Baja (2-6)!"

        elif modalidad == "alta" and 8 <= total <= 12:
            multiplier = 2
            pago_descripcion = "¡Acierto en Alta (8-12)!"

        elif modalidad == "siete" and total == 7:
            multiplier = 5
            pago_descripcion = "¡Acierto en Siete Exacto (7)!"

        elif modalidad == "par" and total % 2 == 0:
            multiplier = 2
            pago_descripcion = "¡Acierto en Par!"

        elif modalidad == "impar" and total % 2 != 0:
            multiplier = 2
            pago_descripcion = "¡Acierto en Impar!"

        if multiplier > 0:
            prize = apuesta * multiplier
            await self.bot.db.economy_update_balance(interaction.user.id, prize - apuesta)
            await self.bot.global_stats.register_dice_win(interaction.user.id, prize, apuesta)

            phrase = await self.bot.db.global_get_random_phrase("dice", "success")

            msg = f"{phrase}Los dados cayeron en: {d1_str} + {d2_str} = **{total}**\n🎉 **{pago_descripcion}** Has ganado **{int(prize)}** choskris. *(Multiplicador {multiplier}x)*"

            current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
            msg += f"\n💰 Saldo actual: **{current_balance}**"

            await interaction.followup.send(
                embed=discord.Embed(
                    title="🎲 Dados",
                    description=msg,
                    color=discord.Color.green()
                )
            )
        else:
            cashback_pct = await self.bot.db.get_user_job_perk(interaction.user.id, "gambling_cashback", 0.0)
            loss = int(apuesta * (1 - cashback_pct))
            await self.bot.db.economy_update_balance(interaction.user.id, -loss)
            await self.bot.global_stats.register_dice_loss(interaction.user.id, apuesta)

            phrase = await self.bot.db.global_get_random_phrase("dice", "fail")
            msg = f"{phrase}Los dados cayeron en: {d1_str} + {d2_str} = **{total}**\n❌ Perdiste **{apuesta}** choskris."
            if cashback_pct > 0:
                msg += f" (-**{apuesta - loss}** cashback)"

            current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
            msg += f"\n💰 Saldo actual: **{current_balance}**"

            await interaction.followup.send(embed=discord.Embed(title="🎲 Dados", description=msg, color=discord.Color.red()))

    @staticmethod
    def _get_random_symbol():
        symbols = list(SYMBOLS.keys())
        weights = [SYMBOLS[s]["weight"] for s in symbols]
        return random.choices(symbols, weights=weights, k=1)[0]

    @casino_group.command(name="tragaperras", description="Juega a la máquina tragaperras")
    @app_commands.describe(apuesta="Cantidad de monedas a apostar")
    async def slots(self, interaction: discord.Interaction, apuesta: int):
        if apuesta <= 0:
            await interaction.response.send_message(embed=discord.Embed(title="🎰 Tragaperras 🎰", description="❌ La apuesta debe ser mayor a 0.", color=discord.Color.red()), ephemeral=True)
            return

        reel1 = self._get_random_symbol()
        reel2 = self._get_random_symbol()
        reel3 = self._get_random_symbol()

        multiplier = 0.0
        if reel1 == reel2 == reel3:
            multiplier = SYMBOLS[reel1]["payout_3"]
        elif reel1 == reel2 or reel1 == reel3:
            multiplier = SYMBOLS[reel1]["payout_2"]
        elif reel2 == reel3:
            multiplier = SYMBOLS[reel2]["payout_2"]

        winnings = int(apuesta * multiplier)
        net_change = winnings - apuesta

        success, current_balance = await self.bot.db.economy_process_slots_bet(interaction.user.id, apuesta, net_change)

        if not success:
            await interaction.response.send_message(embed=discord.Embed(title="🎰 Tragaperras 🎰", description=f"❌ No tienes suficientes monedas. Saldo actual: **{current_balance}**", color=discord.Color.red()), ephemeral=True)
            return

        reels_display = f"| {reel1} | {reel2} | {reel3} |"
        if winnings > 0:
            result_text = f"🎉 ¡Ganaste **{winnings}** monedas!\n(Multiplicador: {multiplier}x)"
            await self.bot.global_stats.register_slots_win(interaction.user.id, winnings, apuesta)
        else:
            result_text = "❌ Has perdido tu apuesta."
            await self.bot.global_stats.register_slots_loss(interaction.user.id, apuesta)

        embed = discord.Embed(title="🎰 Tragaperras 🎰", color=discord.Color.gold() if winnings > 0 else discord.Color.red())
        embed.add_field(name="Rodillos", value=f"```\n{reels_display}\n```", inline=False)
        embed.add_field(name="Resultado", value=result_text, inline=False)

        current_balance = await self.bot.db.economy_get_balance(interaction.user.id)
        embed.add_field(name=f"", value=f"💰 Saldo actual: **{current_balance}**")

        await interaction.response.send_message(embed=embed)

    @casino_group.command(name="mayoromenor", description="Jose Luis muestra una carta, tú dices si es mayor o menor. Rachas de aciertos mayores dan más botín.")
    async def mayoromenor(self, interaction: discord.Interaction, cantidad: int):
        await interaction.response.defer()

        balance = await self.bot.db.economy_get_balance(interaction.user.id)
        if cantidad > balance or cantidad <= 0:
            await interaction.followup.send(embed=discord.Embed(title="🃏 Mayor o Menor", description="❌ No tienes suficientes choskris.", color=discord.Color.red()))
            return

        await self.bot.db.economy_update_balance(interaction.user.id, -cantidad)

        view = MayorMenorView(interaction.user, cantidad, self.bot)
        embed = discord.Embed(
            title="🃏 Mayor o Menor",
            description=f"Carta actual: **{view.get_card_name(view.current_card)}**",
            color=discord.Color.blue()
        )
        embed.add_field(name="Apuesta acumulada", value=f"`{cantidad:,}` choskris")

        await interaction.followup.send(embed=embed, view=view)

    @casino_group.command(name="poker", description="Crea una mesa de póker multijugador.")
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
        view.message = await interaction.followup.send(embed=embed, view=view)

    @casino_group.command(name="blackjack", description="Juega una partida de Blackjack (21) contra la casa.")
    @app_commands.describe(apuesta="Cantidad de choskris a apostar")
    async def blackjack(self, interaction: discord.Interaction, apuesta: int):
        await interaction.response.defer()

        phrase = await self.bot.db.global_get_random_phrase("gamble", "error")
        if apuesta <= 0:
            await interaction.followup.send(
                embed=discord.Embed(title="🃏 Blackjack", description=f"{phrase}La apuesta debe ser mayor a 0.", color=discord.Color.red())
            )
            return

        balance = await self.bot.db.economy_get_balance(interaction.user.id)
        if balance < apuesta:
            await interaction.followup.send(
                embed=discord.Embed(title="🃏 Blackjack", description=f"{phrase}No tienes suficientes choskris para realizar esta apuesta.", color=discord.Color.red())
            )
            return

        await self.bot.db.economy_update_balance(interaction.user.id, -apuesta)

        view = BlackjackView(interaction.user, apuesta, self.bot)

        p_bj = view.is_blackjack(view.player_hand)
        d_bj = view.is_blackjack(view.dealer_hand)

        if p_bj or d_bj:
            if p_bj and d_bj:
                await view.end_game(interaction, result_type="push")
            elif p_bj:
                await view.end_game(interaction, result_type="natural_bj")
            else:
                await view.end_game(interaction, result_type="loss")
            return

        embed = discord.Embed(title="🃏 Blackjack (21)", color=discord.Color.blue())
        embed.description = f"💰 **Apuesta en mesa:** `{apuesta:,}` choskris\n──────────────────────────────"
        embed.add_field(name="👤 Tu Mano", value=view.format_hand(view.player_hand), inline=False)
        embed.add_field(name="🎰 Mano del Crupier", value=view.format_hand(view.dealer_hand, hide_second=True), inline=False)

        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg


async def setup(bot: JoseLuisBot):
    await bot.add_cog(CasinoCog(bot))