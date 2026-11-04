import discord
from discord.ext import commands
import random
import logging
from typing import List

logger = logging.getLogger("SakuraBot.commands.blackjack")


class BlackjackGame:
    def __init__(self):
        self.deck: List[str] = self.create_deck()
        self.player_cards: List[str] = []
        self.dealer_cards: List[str] = []

    def create_deck(self):
        suits = ["♠","♥","♣","♦"]
        ranks = [2,3,4,5,6,7,8,9,10,"J","Q","K","A"]
        return [f"{r}{s}" for s in suits for r in ranks]

    def shuffle_deck(self):
        random.shuffle(self.deck)

    def draw_card(self):
        if not self.deck:
            self.deck = self.create_deck(); self.shuffle_deck()
        return self.deck.pop()

    def deal_initial_cards(self):
        self.player_cards = [self.draw_card(), self.draw_card()]
        self.dealer_cards = [self.draw_card(), self.draw_card()]
        return self.player_cards, self.dealer_cards

    def calculate_hand(self, cards):
        value, aces = 0, 0
        for card in cards:
            rank = card[:-1]
            if rank in ["J","Q","K"]: value += 10
            elif rank == "A": aces += 1; value += 11
            else: value += int(rank)
        while value > 21 and aces:
            value -= 10; aces -= 1
        return value

    def dealer_play(self):
        while self.calculate_hand(self.dealer_cards) < 17:
            self.dealer_cards.append(self.draw_card())
        return self.calculate_hand(self.dealer_cards)

    # [被動重構] 賭徒的決定：勝利返還 base_bet * 6，平手返還 actual_bet
    def settle_game(self, player_cards, dealer_cards, base_bet, actual_bet, is_gambler):
        pt = self.calculate_hand(player_cards)
        dt = self.calculate_hand(dealer_cards)
        
        if dt > 21 or pt > dt: 
            # 勝利：賭徒獲得 6 倍，普通人獲得 2 倍
            return "win", round(base_bet * (6 if is_gambler else 2), 2)
        elif pt == dt: 
            # 平手：退還「實際扣除」的本金
            return "tie", actual_bet
        else: 
            return "lose", 0

    @staticmethod
    def progress_bar(value, max_value=21):
        filled = int(value / max_value * 10)
        return "🌸" * filled + "⋯" * (10 - filled)


class BlackjackButtons(discord.ui.View):
    def __init__(self, game, data_manager, guild_id, user_id):
        super().__init__(timeout=180)
        self.game = game
        self.data_manager = data_manager
        self.guild_id = str(guild_id)
        self.user_id = str(user_id)
        self.message = None

    async def on_timeout(self):
        try:
            refund_amount = None
            async with self.data_manager.balance_lock:
                gd = self.data_manager.blackjack_data.get(self.guild_id,{}).get(self.user_id,{})
                if gd and gd.get("game_status") == "ongoing":
                    # [被動重構] 超時退還「實際扣除」的本金
                    refund_amount = gd.get("actual_bet", gd.get("bet", 0))
                    self.data_manager.balance[self.guild_id][self.user_id] += refund_amount
                    self.data_manager.blackjack_data[self.guild_id][self.user_id]["game_status"] = "ended"
            if refund_amount is not None:
                await self.data_manager.save_all_async()
                if self.message:
                    await self.message.edit(embed=discord.Embed(
                        title="🌸 遊戲超時，幽幽子靈魂小憩～",
                        description=f"退還你的實際賭注 **{refund_amount:.2f}** 幽靈幣，下次再來一起賞花吧！",
                        color=discord.Color.blue()
                    ).set_footer(text="如需再跳舞，請重新開始一局～"), view=None)
        except Exception as e:
            logger.exception(f"Timeout 處理失敗: {e}")

    async def interaction_check(self, interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("這不是你的靈魂之舞喲～", ephemeral=True)
            return False
        return True

    # [被動重構] auto_settle 使用 base_bet 計算 6 倍
    async def auto_settle(self, interaction, player_cards, base_bet, actual_bet, is_gambler):
        pt = self.game.calculate_hand(player_cards)
        if pt != 21:
            return False
        
        # Blackjack 勝利：賭徒 6 倍，普通人 2.5 倍
        m = 6 if is_gambler else 2.5
        reward = round(base_bet * m, 2)
        
        async with self.data_manager.balance_lock:
            self.data_manager.balance[self.guild_id][self.user_id] += reward
            self.data_manager.blackjack_data[self.guild_id][self.user_id]["game_status"] = "ended"
        await self.data_manager.save_all_async()
        
        for c in self.children: c.disabled = True
        
        passive_text = "\n✨ **被動觸發：賭徒的決定** (勝率 x6)" if is_gambler else ""
        await interaction.edit_original_response(embed=discord.Embed(
            title="🌸 黑傑克！櫻花下靈魂舞勝利！🌸",
            description=f"**你的手牌:** {' '.join(player_cards)}\n**總點數:** 21 點\n\n幽幽子為你獻上 **{reward:.2f}** 幽靈幣的祝福～{passive_text}",
            color=discord.Color.gold()
        ).set_footer(text="恭喜你，靈魂閃爍！"), view=None)
        logger.info(f"{self.user_id} Blackjack, 贏得 {reward:.2f}")
        return True

    @discord.ui.button(label="抽牌 (Hit)", style=discord.ButtonStyle.primary, emoji="🎴")
    async def hit(self, button, interaction):
        try:
            await interaction.response.defer()
            async with self.data_manager.balance_lock:
                gd = self.data_manager.blackjack_data[self.guild_id][self.user_id]
                pc = gd["player_cards"]
                pc.append(self.game.draw_card())
                pt = self.game.calculate_hand(pc)
                gd["player_cards"] = pc
                base_bet = gd["base_bet"]; actual_bet = gd["actual_bet"]; is_gambler = gd["is_gambler"]
                if pt > 21: gd["game_status"] = "ended"
            
            if pt > 21:
                await self.data_manager.save_all_async()
                for c in self.children: c.disabled = True
                await interaction.edit_original_response(embed=discord.Embed(
                    title="🌸 哎呀，靈魂爆掉了！🌸",
                    description=f"**你的手牌:** {' '.join(pc)}\n**點數總計:** {pt}\n\n你失去了 **{actual_bet:.2f}** 幽靈幣...",
                    color=discord.Color.red()
                ).set_footer(text="遊戲結束，冥界等待著你～"), view=None)
                return
            
            if await self.auto_settle(interaction, pc, base_bet, actual_bet, is_gambler): return
            
            await interaction.edit_original_response(embed=discord.Embed(
                title="🌸 幽幽子為你送上新櫻花一片！🌸",
                description=f"**你的手牌:** {' '.join(pc)}\n**目前點數:** {pt} {self.game.progress_bar(pt)}\n\n要繼續舞動，還是收手？",
                color=discord.Color.from_rgb(255,182,193)
            ).set_footer(text="命運在你手中～"), view=self)
        except Exception as e:
            logger.exception(f"Hit 失敗: {e}")

    @discord.ui.button(label="停牌 (Stand)", style=discord.ButtonStyle.danger, emoji="✋")
    async def stand(self, button, interaction):
        try:
            await interaction.response.defer()
            async with self.data_manager.balance_lock:
                gd = self.data_manager.blackjack_data[self.guild_id][self.user_id]
                pc = gd["player_cards"]; dc = gd["dealer_cards"]
                base_bet = gd["base_bet"]; actual_bet = gd["actual_bet"]; ig = gd["is_gambler"]
                gd["game_status"] = "ended"
                self.game.dealer_play()
                # [被動重構] 傳入 base_bet 和 actual_bet
                result, reward = self.game.settle_game(pc, dc, base_bet, actual_bet, ig)
                self.data_manager.balance[self.guild_id][self.user_id] += reward
            
            await self.data_manager.save_all_async()
            for c in self.children: c.disabled = True
            
            titles = {"win":"🌸 靈魂之舞勝利！🌸","tie":"🌸 靈魂平手～🌸","lose":"🌸 冥界勝利～🌸"}
            colors = {"win":discord.Color.gold(),"tie":discord.Color.from_rgb(255,182,193),"lose":discord.Color.red()}
            
            if result == "win":
                res_desc = f"你贏得了 **{reward:.2f}** 幽靈幣！"
                if ig: res_desc += "\n✨ **被動觸發：賭徒的決定** (勝率 x6)"
            elif result == "tie":
                res_desc = f"退還實際賭注 **{reward:.2f}** 幽靈幣"
            else:
                res_desc = f"你失去了 **{actual_bet:.2f}** 幽靈幣... 下次再來賞櫻吧～"

            await interaction.edit_original_response(embed=discord.Embed(
                title=titles[result],
                description=f"**你的手牌:** {' '.join(pc)}\n**幽幽子的手牌:** {' '.join(dc)}\n\n{res_desc}",
                color=colors[result]
            ).set_footer(text="遊戲結束，櫻花依舊飄落～"), view=None)
            logger.info(f"{self.user_id} Stand, 結果: {result}, 獎勵: {reward:.2f}")
        except Exception as e:
            logger.exception(f"Stand 失敗: {e}")

    @discord.ui.button(label="雙倍 (Double)", style=discord.ButtonStyle.success, emoji="💰")
    async def double_down(self, button, interaction):
        try:
            await interaction.response.defer()
            error_type = None
            doubled_base_bet = doubled_actual_bet = 0
            pc = dc = None
            player_total = 0
            result = reward = None
            
            async with self.data_manager.balance_lock:
                gd = self.data_manager.blackjack_data[self.guild_id][self.user_id]
                if gd["double_down_used"]:
                    error_type = "used"
                else:
                    base_bet = gd["base_bet"]
                    actual_bet = gd["actual_bet"]
                    ig = gd["is_gambler"]
                    ub = self.data_manager.balance[self.guild_id][self.user_id]
                    
                    # [被動重構] 雙倍下注：額外扣除「實際下注」的金額
                    doubled_base_bet = base_bet * 2
                    doubled_actual_bet = actual_bet * 2
                    
                    if ub < actual_bet:
                        error_type = "no_money"
                    else:
                        gd["base_bet"] = doubled_base_bet
                        gd["actual_bet"] = doubled_actual_bet
                        gd["double_down_used"] = True
                        self.data_manager.balance[self.guild_id][self.user_id] -= actual_bet
                        
                        pc = gd["player_cards"]; dc = gd["dealer_cards"]
                        pc.append(self.game.draw_card())
                        player_total = self.game.calculate_hand(pc)
                        gd["player_cards"] = pc
                        gd["game_status"] = "ended"
                        
                        if player_total <= 21:
                            self.game.dealer_play()
                            result, reward = self.game.settle_game(pc, dc, doubled_base_bet, doubled_actual_bet, ig)
                            self.data_manager.balance[self.guild_id][self.user_id] += reward

            if error_type == "used":
                await interaction.edit_original_response(embed=discord.Embed(title="🌸 命運只能挑戰一次！", description="你已經用過雙倍下注了哦～", color=discord.Color.red()), view=self)
                return
            if error_type == "no_money":
                await interaction.edit_original_response(embed=discord.Embed(title="🌸 櫻花能量不足～", description=f"你的幽靈幣不足以追加 **{actual_bet:.2f}** 的雙倍賭注哦～", color=discord.Color.red()), view=self)
                return

            await self.data_manager.save_all_async()
            for c in self.children: c.disabled = True
            
            if player_total > 21:
                await interaction.edit_original_response(embed=discord.Embed(
                    title="🌸 哎呀，靈魂爆掉了！🌸",
                    description=f"**你的手牌:** {' '.join(pc)}\n**總點數:** {player_total}\n\n你失去了 **{doubled_actual_bet:.2f}** 幽靈幣...",
                    color=discord.Color.red()
                ).set_footer(text="遊戲結束，櫻花謝了～"), view=None)
                return
                
            titles = {"win":"🌸 櫻花舞勝利！🌸","tie":"🌸 靈魂平衡～🌸","lose":"🌸 冥界勝利～🌸"}
            colors = {"win":discord.Color.gold(),"tie":discord.Color.from_rgb(255,182,193),"lose":discord.Color.red()}
            
            if result == "win":
                res_desc = f"你贏得了 **{reward:.2f}** 幽靈幣！"
                if ig: res_desc += "\n✨ **被動觸發：賭徒的決定** (雙倍勝率 x6)"
            elif result == "tie":
                res_desc = f"退還實際賭注 **{reward:.2f}** 幽靈幣"
            else:
                res_desc = f"你失去了 **{doubled_actual_bet:.2f}** 幽靈幣..."

            await interaction.edit_original_response(embed=discord.Embed(
                title=titles[result],
                description=f"**你的手牌:** {' '.join(pc)}\n**幽幽子的手牌:** {' '.join(dc)}\n\n**雙倍賭注:** {doubled_actual_bet:.2f}\n{res_desc}",
                color=colors[result]
            ).set_footer(text="遊戲結束，櫻花依舊飄落～"), view=None)
        except Exception as e:
            logger.exception(f"Double Down 失敗: {e}")


class Blackjack(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(name="blackjack", description="🌸 幽幽子邀你在冥界櫻花園共舞一場21點～")
    async def blackjack(self, ctx, bet: float = discord.Option(float, "下注金額 (幽靈幣)", min_value=1.0)):
        if not await self.data_manager.check_economy_enabled(ctx, "blackjack"):
            return
        try:
            dm = self.bot.data_manager
            if not await dm.check_backup_status(ctx, "blackjack"): return

            bet = round(bet, 2)
            uid = str(ctx.author.id); gid = str(ctx.guild.id)

            async with dm.balance_lock:
                if dm.blackjack_data.get(gid,{}).get(uid,{}).get("game_status") == "ongoing":
                    await ctx.respond(embed=discord.Embed(title="🌸 靈魂還在跳舞！", description="你已經在進行一場櫻花舞了～", color=discord.Color.red()), ephemeral=True); return
                
                ub = round(dm.balance.get(gid,{}).get(uid,0), 2)
                
                is_gambler = dm.user_config.get(gid, {}).get(uid, {}).get("job") == "賭徒"
                
                # [被動重構] 賭徒的決定：實際扣除 3 倍本金
                base_bet = bet
                actual_bet = bet * 3 if is_gambler else bet
                
                if ub < actual_bet:
                    await ctx.respond(embed=discord.Embed(
                        title="🌸 幽靈幣不足，櫻花不開～ 🌸",
                        description=f"你的幽靈幣只有 **{ub:.2f}**，無法下注 **{actual_bet:.2f}** 哦～",
                        color=discord.Color.red()
                    ), ephemeral=True); return
                
                game = BlackjackGame(); game.shuffle_deck()
                pc, dc = game.deal_initial_cards()
                dm.balance[gid][uid] = ub - actual_bet
                
                dm.blackjack_data.setdefault(gid,{})[uid] = {
                    "player_cards": pc, "dealer_cards": dc, 
                    "base_bet": base_bet, "actual_bet": actual_bet,
                    "game_status": "ongoing", "double_down_used": False, "is_gambler": is_gambler
                }
                
                pt = game.calculate_hand(pc)
                if pt == 21:
                    m = 6 if is_gambler else 2.5
                    reward = round(base_bet * m, 2)
                    dm.balance[gid][uid] += reward
                    dm.blackjack_data[gid][uid]["game_status"] = "ended"

            await dm.save_all_async()

            if pt == 21:
                passive_text = "\n✨ **被動觸發：賭徒的決定** (Blackjack x6)" if is_gambler else ""
                await ctx.respond(embed=discord.Embed(
                    title="🌸 黑傑克！櫻花魂閃耀！🌸",
                    description=f"**你的手牌:** {' '.join(pc)}\n\n幽幽子為你獻上 **{reward:.2f}** 幽靈幣的祝福～{passive_text}",
                    color=discord.Color.gold()
                ).set_footer(text="恭喜！櫻花灑滿冥界"))
                return

            view = BlackjackButtons(game, dm, gid, uid)
            passive_desc = "\n✨ **被動：賭徒的決定**｜實際下注 x3 / 勝利 x6" if is_gambler else ""
            embed = discord.Embed(
                title="🌸 幽幽子的櫻花21點舞開始！🌸",
                description=(
                    f"你下注了 **{base_bet:.2f}** 幽靈幣 (實際扣除: **{actual_bet:.2f}**){passive_desc}\n\n"
                    f"**你的初始手牌:** {' '.join(pc)}\n"
                    f"**總點數:** {pt} {game.progress_bar(pt)}\n\n"
                    f"**幽幽子的明牌:** {dc[0]}"
                ),
                color=discord.Color.from_rgb(255,182,193)
            ).set_footer(text="選擇命運吧～櫻花舞只等你來")
            
            response = await ctx.respond(embed=embed, view=view)
            view.message = await response.original_response()
        except Exception as e:
            logger.exception(f"Blackjack 失敗: {e}")


def setup(bot):
    bot.add_cog(Blackjack(bot))
