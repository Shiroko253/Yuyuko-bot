import discord
from discord.ext import commands
import random
import logging
import asyncio
from typing import Dict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger("SakuraBot.commands.blackjack_pvp")


class BlackjackPVPGame:
    def __init__(self, player1_id, player2_id, bet_amount):
        self.deck = self.create_deck()
        self.shuffle_deck()
        self.player1_id = player1_id
        self.player2_id = player2_id
        self.bet_amount = bet_amount
        self.actual_bet_p1 = bet_amount
        self.actual_bet_p2 = bet_amount
        self.player1_cards = []
        self.player2_cards = []
        self.player1_stand = False
        self.player2_stand = False
        self.game_over = False
        self.winner = None

    def create_deck(self):
        suits = ["♠", "♥", "♣", "♦"]
        ranks = [2, 3, 4, 5, 6, 7, 8, 9, 10, "J", "Q", "K", "A"]
        return [f"{rank}{suit}" for suit in suits for rank in ranks]

    def shuffle_deck(self):
        random.shuffle(self.deck)

    def draw_card(self):
        if not self.deck:
            self.deck = self.create_deck()
            self.shuffle_deck()
        return self.deck.pop()

    def calculate_hand(self, cards):
        value, aces = 0, 0
        for card in cards:
            rank = card[:-1]
            if rank in ["J", "Q", "K"]:
                value += 10
            elif rank == "A":
                aces += 1
                value += 11
            else:
                value += int(rank)
        while value > 21 and aces:
            value -= 10
            aces -= 1
        return value

    def deal_initial_cards(self):
        self.player1_cards = [self.draw_card(), self.draw_card()]
        self.player2_cards = [self.draw_card(), self.draw_card()]
        return self.player1_cards, self.player2_cards

    @staticmethod
    def progress_bar(value, max_value=21):
        filled = int(value / max_value * 10)
        return "🌸" * filled + "⋯" * (10 - filled)


class BlackjackPVPManager:
    def __init__(self):
        self.active_games: Dict[str, BlackjackPVPGame] = {}
        self.pending_challenges: Dict[str, dict] = {}
        self.player_in_game: Dict[str, str] = {}

    def create_challenge(self, guild_id, challenger_id, opponent_id, bet_amount):
        key = f"{guild_id}:{challenger_id}:{opponent_id}"
        self.pending_challenges[key] = {
            "guild_id": guild_id, "challenger_id": challenger_id,
            "opponent_id": opponent_id, "bet_amount": bet_amount,
            "timestamp": datetime.now()
        }
        return key

    def accept_challenge(self, key):
        return self.pending_challenges.pop(key, None)

    def decline_challenge(self, key):
        self.pending_challenges.pop(key, None)

    def start_game(self, guild_id, player1_id, player2_id, bet_amount):
        game = BlackjackPVPGame(player1_id, player2_id, bet_amount)
        self.active_games[guild_id] = game
        self.player_in_game[player1_id] = guild_id
        self.player_in_game[player2_id] = guild_id
        return game

    def get_game(self, guild_id):
        return self.active_games.get(guild_id)

    def end_game(self, guild_id):
        if guild_id in self.active_games:
            game = self.active_games[guild_id]
            self.player_in_game.pop(game.player1_id, None)
            self.player_in_game.pop(game.player2_id, None)
            del self.active_games[guild_id]

    def is_player_in_game(self, user_id):
        return user_id in self.player_in_game


pvp_manager = BlackjackPVPManager()


class ChallengeView(discord.ui.View):
    def __init__(self, cog, challenge_key, challenger, opponent, bet_amount):
        super().__init__(timeout=60)
        self.cog = cog
        self.challenge_key = challenge_key
        self.challenger = challenger
        self.opponent = opponent
        self.bet_amount = bet_amount
        self.responded = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("這不是給你的挑戰哦！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="接受挑戰", style=discord.ButtonStyle.success, emoji="⚔️")
    async def accept_button(self, button, interaction):
        if self.responded:
            await interaction.response.send_message("挑戰已回應！", ephemeral=True)
            return
        
        if not await self.cog.data_manager.check_backup_status(interaction, "blackjack_pvp_accept"):
            return

        self.responded = True
        await interaction.response.defer()
        try:
            guild_id = str(interaction.guild.id)
            opponent_id = str(self.opponent.id)
            balance = self.cog.data_manager.balance
            opponent_balance = balance.get(guild_id, {}).get(opponent_id, 0.0)
            if opponent_balance < self.bet_amount:
                shortage = self.bet_amount - opponent_balance
                await self.offer_loan(interaction, shortage)
                return
            await self.start_pvp_game(interaction)
        except Exception as e:
            logger.error(f"接受挑戰失敗: {e}", exc_info=True)
            await interaction.followup.send("❌ 發生錯誤，請稍後再試", ephemeral=True)

    async def offer_loan(self, interaction, shortage):
        guild_id = str(interaction.guild.id)
        opponent_id = str(self.opponent.id)
        
        # [終極優化] 直接讀取記憶體中的 server_vault，無需任何 I/O！
        server_vault = self.cog.data_manager.server_vault
        vault_total = server_vault.get(guild_id, {}).get("vault", {}).get("total", 0.0)
        
        if vault_total < shortage:
            await interaction.followup.send(embed=discord.Embed(
                title="🌸 國庫餘額不足",
                description=f"你的餘額不足 **{shortage:.2f}** 幽靈幣，但國庫也無法提供借貸...",
                color=discord.Color.red()
            ), ephemeral=True)
            self.stop()
            return
            
        loan_view = LoanConfirmView(self.cog, self, interaction, shortage)
        embed = discord.Embed(
            title="🌸 餘額不足，是否借貸？",
            description=(
                f"你的餘額不足以與 {self.challenger.mention} 對賭！\n\n"
                f"**下注金額：** {self.bet_amount:.2f} 幽靈幣\n"
                f"**你的餘額：** {self.cog.data_manager.balance.get(guild_id, {}).get(opponent_id, 0.0):.2f} 幽靈幣\n"
                f"**需要補齊：** {shortage:.2f} 幽靈幣\n\n"
                f"是否向國庫借款 **{shortage:.2f}** 幽靈幣來參與對戰？"
            ),
            color=discord.Color.orange()
        )
        embed.add_field(name="📋 借貸條款", value=(
            f"```yaml\n借款金額: {shortage:.2f} 幽靈幣\n利息率: 10%\n"
            f"需還款: {shortage * 1.1:.2f} 幽靈幣\n還款期限: 5 天\n```"
        ), inline=False)
        embed.add_field(name="⚠️ 風險提示",
            value="• 借貸後無論輸贏都需償還\n• 逾期未還將利息提升至20%\n• 逾期超過7天將金額×4",
            inline=False)
        await interaction.followup.send(embed=embed, view=loan_view, ephemeral=True)

    async def start_pvp_game(self, interaction):
        guild_id = str(interaction.guild.id)
        challenger_id = str(self.challenger.id)
        opponent_id = str(self.opponent.id)
        
        challenger_job = self.cog.get_player_job(guild_id, challenger_id)
        opponent_job = self.cog.get_player_job(guild_id, opponent_id)
        
        challenger_actual_bet = self.bet_amount * 3 if challenger_job == "賭徒" else self.bet_amount
        opponent_actual_bet = self.bet_amount * 3 if opponent_job == "賭徒" else self.bet_amount

        async with self.cog.data_manager.balance_lock:
            balance = self.cog.data_manager.balance
            if balance.get(guild_id, {}).get(challenger_id, 0.0) < challenger_actual_bet:
                await interaction.followup.send(
                    f"❌ {self.challenger.mention} 餘額不足！需要 **{challenger_actual_bet:.2f}** 幽靈幣",
                    ephemeral=True)
                return
            if balance.get(guild_id, {}).get(opponent_id, 0.0) < opponent_actual_bet:
                await interaction.followup.send(
                    f"❌ {self.opponent.mention} 餘額不足！需要 **{opponent_actual_bet:.2f}** 幽靈幣",
                    ephemeral=True)
                return
            balance[guild_id][challenger_id] -= challenger_actual_bet
            balance[guild_id][opponent_id] -= opponent_actual_bet

        await self.cog.data_manager.save_all_async()

        game = pvp_manager.start_game(guild_id, challenger_id, opponent_id, self.bet_amount)
        game.actual_bet_p1 = challenger_actual_bet
        game.actual_bet_p2 = opponent_actual_bet
        game.deal_initial_cards()

        game_view = PVPGameView(self.cog, game, guild_id, self.challenger, self.opponent)
        embed = self._create_game_embed(game)
        await interaction.edit_original_response(
            content=f"🌸⚔️ **遊戲開始！** {self.challenger.mention} 輪到你操作了！",
            embed=embed, view=game_view)
        self.stop()
        logger.info(f"PVP 遊戲開始: {challenger_id} vs {opponent_id}, 賭注: {self.bet_amount:.2f}")

    def _create_game_embed(self, game):
        p1_total = game.calculate_hand(game.player1_cards)
        p2_total = game.calculate_hand(game.player2_cards)
        embed = discord.Embed(
            title="🌸⚔️ Blackjack PVP 對戰開始！",
            description=f"賭注：**{game.bet_amount:.2f}** 幽靈幣\n勝者獨得：**{game.bet_amount * 2:.2f}** 幽靈幣",
            color=discord.Color.purple())
        embed.add_field(name=f"🎴 {self.challenger.display_name} (當前回合)",
            value=f"**手牌：** {' '.join(game.player1_cards)}\n**點數：** {p1_total} {game.progress_bar(p1_total)}",
            inline=False)
        embed.add_field(name=f"🎴 {self.opponent.display_name}",
            value=f"**手牌：** {' '.join(game.player2_cards)}\n**點數：** {p2_total} {game.progress_bar(p2_total)}",
            inline=False)
        embed.set_footer(text=f"輪到 {self.challenger.display_name} 操作 · 幽幽子")
        return embed

    @discord.ui.button(label="拒絕挑戰", style=discord.ButtonStyle.danger, emoji="❌")
    async def decline_button(self, button, interaction):
        if self.responded:
            await interaction.response.send_message("挑戰已回應！", ephemeral=True)
            return
        self.responded = True
        pvp_manager.decline_challenge(self.challenge_key)
        await interaction.response.edit_message(embed=discord.Embed(
            title="🌸 挑戰已拒絕",
            description=f"{self.opponent.mention} 拒絕了 {self.challenger.mention} 的挑戰",
            color=discord.Color.red()), view=None)
        self.stop()

    async def on_timeout(self):
        if not self.responded:
            pvp_manager.decline_challenge(self.challenge_key)
            try:
                if hasattr(self, 'message') and self.message:
                    await self.message.edit(embed=discord.Embed(
                        title="🌸 挑戰已超時",
                        description=f"{self.opponent.mention} 未在時限內回應，挑戰已取消",
                        color=discord.Color.orange()), view=None)
            except Exception:
                pass


class LoanConfirmView(discord.ui.View):
    def __init__(self, cog, challenge_view, interaction, loan_amount):
        super().__init__(timeout=30)
        self.cog = cog
        self.challenge_view = challenge_view
        self.interaction = interaction
        self.loan_amount = loan_amount
        self.responded = False

    @discord.ui.button(label="確認借貸", style=discord.ButtonStyle.success, emoji="💰")
    async def confirm_loan(self, button, interaction):
        if self.responded:
            return
        
        if not await self.cog.data_manager.check_backup_status(interaction, "blackjack_pvp_loan"):
            return

        self.responded = True
        await interaction.response.defer()
        try:
            guild_id = str(interaction.guild.id)
            user_id = str(interaction.user.id)

            # [終極優化] 直接引用記憶體中的字典，統一上鎖修改，最後一次性保存！
            personal_bank = self.cog.data_manager.personal_bank
            server_vault = self.cog.data_manager.server_vault
            balance = self.cog.data_manager.balance

            async with self.cog.data_manager.balance_lock:
                # 1. 修改國庫
                if guild_id not in server_vault: server_vault[guild_id] = {"vault": {"total": 0.0}}
                server_vault[guild_id]["vault"]["total"] -= self.loan_amount
                
                # 2. 修改玩家餘額
                if guild_id not in balance: balance[guild_id] = {}
                if user_id not in balance[guild_id]: balance[guild_id][user_id] = 0.0
                balance[guild_id][user_id] += self.loan_amount
                
                # 3. 修改私人銀行借貸紀錄
                if guild_id not in personal_bank: personal_bank[guild_id] = {}
                if user_id not in personal_bank[guild_id]: personal_bank[guild_id][user_id] = {"balance": 0.0, "loan": None}
                
                tz = ZoneInfo('Asia/Taipei')
                current_time = datetime.now(tz)
                loan_data = personal_bank[guild_id][user_id].get("loan")
                
                if loan_data and not loan_data.get("repaid"):
                    loan_data["amount"] += self.loan_amount
                    loan_data["last_borrowed_at"] = current_time.isoformat()
                    loan_data["due_date"] = (current_time + timedelta(days=5)).isoformat()
                    loan_data["purpose"] = "blackjack_pvp"
                else:
                    loan_data = {
                        "amount": self.loan_amount, "interest_rate": 0.1,
                        "borrowed_at": current_time.isoformat(),
                        "due_date": (current_time + timedelta(days=5)).isoformat(),
                        "repaid": False, "last_penalty_cycle": 0, "purpose": "blackjack_pvp"
                    }
                personal_bank[guild_id][user_id]["loan"] = loan_data

            # [終極優化] 鎖釋放後，呼叫一次 save_all_async，三個經濟檔案會一起被深拷貝並安全寫入！
            await self.cog.data_manager.save_all_async()

            await self.challenge_view.start_pvp_game(self.interaction)
            await interaction.followup.send(embed=discord.Embed(
                title="🌸 借貸成功！",
                description=f"你已借貸 **{self.loan_amount:.2f}** 幽靈幣，遊戲即將開始！",
                color=discord.Color.gold()), ephemeral=True)
            logger.info(f"PVP 借貸: {user_id} 借貸 {self.loan_amount:.2f}")
        except Exception as e:
            logger.error(f"借貸失敗: {e}", exc_info=True)
            await interaction.followup.send("❌ 借貸失敗，請稍後再試", ephemeral=True)
        self.stop()

    @discord.ui.button(label="取消", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel_loan(self, button, interaction):
        if self.responded:
            return
        self.responded = True
        await interaction.response.edit_message(embed=discord.Embed(
            title="🌸 已取消", description="你取消了借貸，挑戰已結束",
            color=discord.Color.red()), view=None)
        self.stop()


class PVPGameView(discord.ui.View):
    def __init__(self, cog, game, guild_id, player1, player2):
        super().__init__(timeout=180)
        self.cog = cog
        self.game = game
        self.guild_id = guild_id
        self.player1 = player1
        self.player2 = player2
        self.current_turn = game.player1_id
        self.message = None

    async def interaction_check(self, interaction):
        user_id = str(interaction.user.id)
        if user_id != self.current_turn:
            await interaction.response.send_message("還沒輪到你哦！", ephemeral=True)
            return False
        if user_id == self.game.player1_id and self.game.player1_stand:
            await interaction.response.send_message("你已經停牌了！", ephemeral=True)
            return False
        if user_id == self.game.player2_id and self.game.player2_stand:
            await interaction.response.send_message("你已經停牌了！", ephemeral=True)
            return False
        return True

    def update_turn(self):
        if self.game.player1_stand and self.game.player2_stand:
            return
        if self.current_turn == self.game.player1_id:
            if not self.game.player2_stand:
                self.current_turn = self.game.player2_id
        else:
            if not self.game.player1_stand:
                self.current_turn = self.game.player1_id

    def get_next_player_notification(self) -> str:
        if self.game.game_over:
            return ""
        next_player = self.player2 if self.current_turn == self.game.player2_id else self.player1
        current_player = self.player1 if self.current_turn == self.game.player2_id else self.player2
        return f"🌸 {current_player.mention} 已完成操作，{next_player.mention} 輪到你了！"

    async def check_game_over(self, interaction) -> bool:
        p1_total = self.game.calculate_hand(self.game.player1_cards)
        p2_total = self.game.calculate_hand(self.game.player2_cards)
        if p1_total > 21:
            await self.end_game(interaction, self.game.player2_id, "player1_bust")
            return True
        if p2_total > 21:
            await self.end_game(interaction, self.game.player1_id, "player2_bust")
            return True
        if self.game.player1_stand and self.game.player2_stand:
            if p1_total > p2_total:
                await self.end_game(interaction, self.game.player1_id, "higher_score")
            elif p2_total > p1_total:
                await self.end_game(interaction, self.game.player2_id, "higher_score")
            else:
                await self.end_game(interaction, None, "tie")
            return True
        return False

    def get_player_job(self, user_id) -> str:
        return self.cog.data_manager.user_config.get(self.guild_id, {}).get(user_id, {}).get("job", "普通")

    async def end_game(self, interaction, winner_id, reason):
        self.game.game_over = True
        self.game.winner = winner_id
        p1_job = self.get_player_job(self.game.player1_id)
        p2_job = self.get_player_job(self.game.player2_id)

        async with self.cog.data_manager.balance_lock:
            balance = self.cog.data_manager.balance
            if winner_id:
                winner_job = self.get_player_job(winner_id)
                loser_id = self.game.player2_id if winner_id == self.game.player1_id else self.game.player1_id
                loser_job = self.get_player_job(loser_id)
                total_pool = self.game.actual_bet_p1 + self.game.actual_bet_p2
                if winner_job != "賭徒" and loser_job == "賭徒":
                    loser_actual = self.game.actual_bet_p2 if loser_id == self.game.player2_id else self.game.actual_bet_p1
                    payout = total_pool + loser_actual * 0.5
                else:
                    payout = total_pool
                balance[self.guild_id][winner_id] += payout
                win_amount = payout
            else:
                balance[self.guild_id][self.game.player1_id] += self.game.actual_bet_p1
                balance[self.guild_id][self.game.player2_id] += self.game.actual_bet_p2
                win_amount = None

        await self.cog.data_manager.save_all_async()

        embed = self._create_end_embed(reason, p1_job, p2_job, win_amount)
        if winner_id == self.game.player1_id:
            result_text = f"🎉 {self.player1.mention} 獲勝！獲得 **{win_amount:.2f}** 幽靈幣"
        elif winner_id == self.game.player2_id:
            result_text = f"🎉 {self.player2.mention} 獲勝！獲得 **{win_amount:.2f}** 幽靈幣"
        else:
            result_text = f"🤝 平手！雙方各退回 **{self.game.bet_amount:.2f}** 幽靈幣"

        for item in self.children:
            item.disabled = True
        try:
            await interaction.edit_original_response(content=result_text, embed=embed, view=self)
        except Exception:
            pass
        pvp_manager.end_game(self.guild_id)
        self.stop()
        logger.info(f"PVP 遊戲結束: {reason}, 勝者: {winner_id}")

    def _create_end_embed(self, reason, p1_job, p2_job, win_amount):
        p1_total = self.game.calculate_hand(self.game.player1_cards)
        p2_total = self.game.calculate_hand(self.game.player2_cards)
        if reason == "player1_bust":
            title, desc, color = f"🌸 {self.player2.display_name} 獲勝！", f"{self.player1.display_name} 爆牌了！", discord.Color.red()
        elif reason == "player2_bust":
            title, desc, color = f"🌸 {self.player1.display_name} 獲勝！", f"{self.player2.display_name} 爆牌了！", discord.Color.gold()
        elif reason == "higher_score":
            w = self.player1 if self.game.winner == self.game.player1_id else self.player2
            high, low = (p1_total, p2_total) if self.game.winner == self.game.player1_id else (p2_total, p1_total)
            title, desc, color = f"🌸 {w.display_name} 獲勝！", f"點數更高：{high} vs {low}", discord.Color.gold()
        elif reason == "timeout":
            w = self.player1 if self.game.winner == self.game.player1_id else self.player2
            l = self.player2 if self.game.winner == self.game.player1_id else self.player1
            title, desc, color = f"🌸 {w.display_name} 獲勝！", f"{l.display_name} 超時棄牌", discord.Color.gold()
        else:
            title, desc, color = "🌸 平手！", f"雙方點數相同：{p1_total}", discord.Color.blue()

        embed = discord.Embed(title=title, description=desc, color=color)
        p1_icon = "🎰" if p1_job == "賭徒" else "🎴"
        p2_icon = "🎰" if p2_job == "賭徒" else "🎴"
        embed.add_field(name=f"{p1_icon} {self.player1.display_name}",
            value=f"**手牌：** {' '.join(self.game.player1_cards)}\n**點數：** {p1_total}\n**職業：** {p1_job}", inline=False)
        embed.add_field(name=f"{p2_icon} {self.player2.display_name}",
            value=f"**手牌：** {' '.join(self.game.player2_cards)}\n**點數：** {p2_total}\n**職業：** {p2_job}", inline=False)
        if self.game.winner and win_amount is not None:
            winner_job = p1_job if self.game.winner == self.game.player1_id else p2_job
            loser_job = p2_job if self.game.winner == self.game.player1_id else p1_job
            reward_text = f"獲得 **{win_amount:.2f}** 幽靈幣"
            if winner_job == "賭徒" and loser_job != "賭徒":
                reward_text += "\n🎰 **賭徒加成：** 實際壓注 ×3！"
            elif winner_job != "賭徒" and loser_job == "賭徒":
                reward_text += "\n⚔️ **擊敗賭徒：** 額外獲得賭徒壓注的一半！"
            elif winner_job == "賭徒" and loser_job == "賭徒":
                reward_text += "\n🎰🔥 **賭徒對決：** 雙方各壓 ×3，勝者通吃！"
            embed.add_field(name="💰 獎勵", value=reward_text, inline=False)
        else:
            embed.add_field(name="💰 退款", value=f"雙方各退回 **{self.game.bet_amount:.2f}** 幽靈幣", inline=False)
        embed.set_footer(text="遊戲結束 · 幽幽子")
        return embed

    def _create_game_embed(self):
        p1_total = self.game.calculate_hand(self.game.player1_cards)
        p2_total = self.game.calculate_hand(self.game.player2_cards)
        p1_job = self.get_player_job(self.game.player1_id)
        p2_job = self.get_player_job(self.game.player2_id)
        cur_name = self.player1.display_name if self.current_turn == self.game.player1_id else self.player2.display_name
        embed = discord.Embed(title="🌸⚔️ Blackjack PVP 對戰中",
            description=f"當前回合：**{cur_name}**\n賭注：**{self.game.bet_amount:.2f}** 幽靈幣",
            color=discord.Color.purple())
        p1_status = "🛑 已停牌" if self.game.player1_stand else "🎴 進行中"
        p1_icon = "🎰" if p1_job == "賭徒" else "🎴"
        embed.add_field(name=f"{p1_status} {p1_icon} {self.player1.display_name} ({p1_job})",
            value=f"**手牌：** {' '.join(self.game.player1_cards)}\n**點數：** {p1_total} {self.game.progress_bar(p1_total)}",
            inline=False)
        p2_status = "🛑 已停牌" if self.game.player2_stand else "🎴 進行中"
        p2_icon = "🎰" if p2_job == "賭徒" else "🎴"
        embed.add_field(name=f"{p2_status} {p2_icon} {self.player2.display_name} ({p2_job})",
            value=f"**手牌：** {' '.join(self.game.player2_cards)}\n**點數：** {p2_total} {self.game.progress_bar(p2_total)}",
            inline=False)
        if p1_job == "賭徒" or p2_job == "賭徒":
            if p1_job == "賭徒" and p2_job == "賭徒":
                special = "🎰🔥 雙方都是賭徒！各壓 ×3 倍，勝者通吃全部！"
            elif p1_job == "賭徒":
                special = f"🎰 {self.player1.display_name} 是賭徒！實際壓注 ×3"
            else:
                special = f"🎰 {self.player2.display_name} 是賭徒！實際壓注 ×3"
            embed.add_field(name="⚠️ 特殊規則", value=special, inline=False)
        embed.set_footer(text=f"輪到 {cur_name} 操作 · 幽幽子")
        return embed

    @discord.ui.button(label="抽牌 (Hit)", style=discord.ButtonStyle.primary, emoji="🎴")
    async def hit(self, button, interaction):
        await interaction.response.defer()
        try:
            user_id = str(interaction.user.id)
            if user_id == self.game.player1_id:
                self.game.player1_cards.append(self.game.draw_card())
            else:
                self.game.player2_cards.append(self.game.draw_card())
            if await self.check_game_over(interaction):
                return
            self.update_turn()
            notification = self.get_next_player_notification()
            await interaction.edit_original_response(content=notification, embed=self._create_game_embed(), view=self)
        except Exception as e:
            logger.error(f"Hit 失敗: {e}", exc_info=True)

    @discord.ui.button(label="停牌 (Stand)", style=discord.ButtonStyle.danger, emoji="✋")
    async def stand(self, button, interaction):
        await interaction.response.defer()
        try:
            user_id = str(interaction.user.id)
            if user_id == self.game.player1_id:
                self.game.player1_stand = True
            else:
                self.game.player2_stand = True
            if await self.check_game_over(interaction):
                return
            self.update_turn()
            notification = self.get_next_player_notification()
            await interaction.edit_original_response(content=notification, embed=self._create_game_embed(), view=self)
        except Exception as e:
            logger.error(f"Stand 失敗: {e}", exc_info=True)

    async def on_timeout(self):
        if self.game.game_over:
            return
        winner_id = self.game.player2_id if self.current_turn == self.game.player1_id else self.game.player1_id
        self.game.game_over = True
        self.game.winner = winner_id
        p1_job = self.get_player_job(self.game.player1_id)
        p2_job = self.get_player_job(self.game.player2_id)
        total_pool = self.game.actual_bet_p1 + self.game.actual_bet_p2

        async with self.cog.data_manager.balance_lock:
            self.cog.data_manager.balance[self.guild_id][winner_id] += total_pool

        await self.cog.data_manager.save_all_async()

        embed = self._create_end_embed("timeout", p1_job, p2_job, total_pool)
        winner_member = self.player1 if winner_id == self.game.player1_id else self.player2
        result_text = f"⏰ 超時！{winner_member.mention} 獲勝，對方未在時限內操作。"

        for item in self.children:
            item.disabled = True
        try:
            if self.message:
                await self.message.edit(content=result_text, embed=embed, view=self)
        except Exception as e:
            logger.error(f"PVP timeout 更新訊息失敗: {e}")
        pvp_manager.end_game(self.guild_id)
        logger.info(f"PVP 遊戲超時結束, 勝者: {winner_id}")


class BlackjackPVP(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_manager = bot.data_manager

    def get_player_job(self, guild_id, user_id) -> str:
        return self.data_manager.user_config.get(guild_id, {}).get(user_id, {}).get("job", "普通")

    @discord.slash_command(name="blackjack_pvp", description="🌸⚔️ 向其他玩家發起 Blackjack 對戰挑戰")
    async def blackjack_pvp(
        self, ctx,
        opponent: discord.Member = discord.Option(discord.Member, "挑戰對象"),
        bet: float = discord.Option(float, "下注金額 (幽靈幣)", min_value=1.0)
    ):
        if not await self.data_manager.check_economy_enabled(ctx, "blackjack_pvp"):
            return
        try:
            if not await self.data_manager.check_backup_status(ctx, "blackjack_pvp"):
                return

            guild_id = str(ctx.guild.id)
            challenger_id = str(ctx.author.id)
            opponent_id = str(opponent.id)
            bet = round(bet, 2)

            if ctx.author.id == opponent.id:
                await ctx.respond(embed=discord.Embed(title="❌ 無法挑戰自己", description="你不能和自己對戰哦！", color=discord.Color.red()), ephemeral=True)
                return
            if opponent.bot:
                await ctx.respond(embed=discord.Embed(title="❌ 無法挑戰機器人", description="機器人無法參與 PVP 對戰！", color=discord.Color.red()), ephemeral=True)
                return
            if pvp_manager.is_player_in_game(challenger_id):
                await ctx.respond(embed=discord.Embed(title="❌ 你已在遊戲中", description="請先完成當前的遊戲！", color=discord.Color.red()), ephemeral=True)
                return
            if pvp_manager.is_player_in_game(opponent_id):
                await ctx.respond(embed=discord.Embed(title="❌ 對手已在遊戲中", description=f"{opponent.mention} 正在進行其他遊戲！", color=discord.Color.red()), ephemeral=True)
                return

            balance = self.data_manager.balance
            challenger_balance = balance.get(guild_id, {}).get(challenger_id, 0.0)
            if challenger_balance < bet:
                await ctx.respond(embed=discord.Embed(
                    title="🌸 餘額不足",
                    description=f"你的餘額只有 **{challenger_balance:.2f}** 幽靈幣，無法下注 **{bet:.2f}** 幽靈幣",
                    color=discord.Color.red()), ephemeral=True)
                return

            challenge_key = pvp_manager.create_challenge(guild_id, challenger_id, opponent_id, bet)
            view = ChallengeView(self, challenge_key, ctx.author, opponent, bet)

            embed = discord.Embed(
                title="🌸⚔️ Blackjack PVP 挑戰！",
                description=(
                    f"{ctx.author.mention} 向 {opponent.mention} 發起挑戰！\n\n"
                    f"**賭注：** {bet:.2f} 幽靈幣\n**勝者獲得：** {bet * 2:.2f} 幽靈幣（基礎）"),
                color=discord.Color.purple())
            embed.add_field(name="⚔️ 規則", value=(
                "• 雙方輪流操作抽牌或停牌\n• 超過21點立即判負\n"
                "• 雙方停牌後比較點數\n• 點數高者獲勝\n• 平手退回賭注\n• 超時視為棄牌判負"), inline=False)

            config_user = self.data_manager.user_config
            c_job = config_user.get(guild_id, {}).get(challenger_id, {}).get("job", "普通")
            o_job = config_user.get(guild_id, {}).get(opponent_id, {}).get("job", "普通")
            
            if c_job == "賭徒" or o_job == "賭徒":
                lines = []
                if c_job == "賭徒" and o_job == "賭徒":
                    lines += ["🎰🔥 **賭徒 vs 賭徒：超高風險對決！**",
                              f"雙方實際壓注 **{bet*3:.2f}** 幽靈幣（×3）",
                              f"勝者通吃 **{bet*6:.2f}** 幽靈幣（總池）"]
                else:
                    if c_job == "賭徒": lines.append(f"🎰 {ctx.author.display_name} 是賭徒！實際壓注 ×3")
                    if o_job == "賭徒": lines.append(f"🎰 {opponent.display_name} 是賭徒！實際壓注 ×3")
                    lines.append("⚔️ 擊敗賭徒可獲得額外獎勵！")
                embed.add_field(name="🎰 賭徒職業特殊規則", value="\n".join(lines), inline=False)

            embed.set_footer(text=f"{opponent.display_name} 請選擇接受或拒絕 · 60秒內回應")
            response = await ctx.respond(
                content=f"{opponent.mention} 你收到了一個 Blackjack PVP 挑戰！",
                embed=embed, view=view)
            view.message = await response.original_response()
            logger.info(f"PVP 挑戰: {challenger_id} -> {opponent_id}, 賭注: {bet:.2f}")

        except Exception as e:
            logger.error(f"PVP 挑戰失敗: {e}", exc_info=True)
            await ctx.respond("❌ 發生錯誤，請稍後再試", ephemeral=True)


def setup(bot):
    bot.add_cog(BlackjackPVP(bot))
    logger.info("🌸⚔️ Blackjack PVP 系統已載入")
