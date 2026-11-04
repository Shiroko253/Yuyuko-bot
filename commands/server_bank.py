import os
import logging
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from zoneinfo import ZoneInfo
import discord
from discord.ext import commands, tasks
from discord.ui import View, Modal, InputText

logger = logging.getLogger("SakuraBot.ServerBank")


def calculate_interest_rate(amount: float) -> float:
    if amount < 100_000: return 0.10
    elif amount < 1_000_000: return 0.15
    elif amount < 10_000_000: return 0.25
    elif amount < 100_000_000: return 0.40
    else: return 0.60

def interest_tier_description() -> str:
    return (
        "```yaml\n< 10萬: 10%\n10萬~100萬: 15%\n100萬~1000萬: 25%\n"
        "1000萬~1億: 40%\n1億以上: 60%\n```"
    )


class ServerBank(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.data_manager = bot.data_manager
        self.tz = ZoneInfo('Asia/Taipei')
        self.check_overdue_loans.start()
        logger.info("🌸 櫻花金庫已於冥界花園中開啟")

    def cog_unload(self):
        self.check_overdue_loans.cancel()

    def initialize_server_vault(self, guild_id: str, owner_id: str):
        """初始化伺服器國庫 (純記憶體操作)"""
        server_vault = self.data_manager.server_vault
        need_save = False

        if guild_id not in server_vault:
            server_vault[guild_id] = {"vault": {"total": 5000000000.0, "contributions": {owner_id: 5000000000.0}}}
            need_save = True
        elif "vault" not in server_vault[guild_id]:
            server_vault[guild_id]["vault"] = {"total": 5000000000.0, "contributions": {owner_id: 5000000000.0}}
            need_save = True

        return need_save

    @tasks.loop(hours=168)
    async def check_overdue_loans(self):
        """每週一檢查逾期借貸 (優化：批量修改記憶體，一次性保存)"""
        try:
            personal_bank = self.data_manager.personal_bank
            current_time = datetime.now(self.tz)
            
            # 收集需要修改的數據，避免在迴圈中頻繁獲取鎖
            updates_to_apply = [] 

            for guild_id, users in personal_bank.items():
                guild = self.bot.get_guild(int(guild_id))
                for user_id, user_data in users.items():
                    if not isinstance(user_data, dict) or "loan" not in user_data: continue
                    loan = user_data["loan"]
                    if loan is None or not isinstance(loan, dict) or loan.get("repaid"): continue

                    try:
                        due_date = datetime.fromisoformat(loan["due_date"])
                        if due_date.tzinfo is None: due_date = due_date.replace(tzinfo=self.tz)
                    except: continue

                    days_overdue = (current_time - due_date).days
                    if days_overdue < 0: continue

                    if days_overdue >= 30:
                        updates_to_apply.append(("force_repay", guild_id, user_id, loan, days_overdue, guild))
                    elif days_overdue >= 7:
                        penalty_cycles = days_overdue // 7
                        last_penalty_cycle = loan.get("last_penalty_cycle", 0)
                        if penalty_cycles > last_penalty_cycle:
                            updates_to_apply.append(("penalty", guild_id, user_id, loan, penalty_cycles, last_penalty_cycle, days_overdue, guild))

            # 一次性獲取鎖，批量修改記憶體
            if updates_to_apply:
                async with self.data_manager.balance_lock:
                    balance = self.data_manager.balance
                    for update in updates_to_apply:
                        if update[0] == "force_repay":
                            await self._force_repay_in_lock(update[1], update[2], update[3], update[4], update[5])
                        elif update[0] == "penalty":
                            self._apply_penalty_in_lock(update[1], update[2], update[3], update[4], update[5])

                # 鎖釋放後，統一保存
                await self.data_manager.save_all_async()

                # 發送 DM (在鎖外進行，避免阻塞)
                for update in updates_to_apply:
                    if update[0] == "penalty":
                        await self._send_penalty_dm(update[1], update[2], update[3], update[4], update[6], update[7])

        except Exception as e:
            logger.error(f"❌ 逾期檢查失敗: {e}", exc_info=True)

    def _apply_penalty_in_lock(self, guild_id, user_id, loan, penalty_cycles, last_penalty_cycle):
        """在鎖內套用逾期懲罰"""
        new_penalties = penalty_cycles - last_penalty_cycle
        for i in range(new_penalties):
            current_cycle = last_penalty_cycle + i + 1
            if current_cycle == 1: loan["amount"] *= 2
            else: loan["amount"] *= 4
        loan["last_penalty_cycle"] = penalty_cycles

    async def _force_repay_in_lock(self, guild_id, user_id, loan, days_overdue, guild):
        """在鎖內執行強制還款"""
        amount_with_interest = round(loan["amount"] * (1 + loan["interest_rate"]), 2)
        balance = self.data_manager.balance
        personal_bank = self.data_manager.personal_bank
        
        hand_balance = balance.get(guild_id, {}).get(user_id, 0.0)
        bank_balance = personal_bank.get(guild_id, {}).get(user_id, {}).get("balance", 0.0)
        total_available = hand_balance + bank_balance
        remaining = amount_with_interest

        deducted_hand = min(hand_balance, remaining) if hand_balance > 0 else 0.0
        if guild_id in balance and user_id in balance[guild_id]:
            balance[guild_id][user_id] -= deducted_hand
        remaining -= deducted_hand

        deducted_bank = min(bank_balance, remaining) if remaining > 0 and bank_balance > 0 else 0.0
        if guild_id in personal_bank and user_id in personal_bank[guild_id]:
            personal_bank[guild_id][user_id]["balance"] -= deducted_bank
        
        personal_bank[guild_id][user_id]["loan"] = None
        
        # 調整信譽
        self.adjust_credit(guild_id, user_id, -1, "逾期30天強制還款")

        logger.info(f"🔴 強制還款: {user_id} 逾期 {days_overdue} 天，扣款 {deducted_hand + deducted_bank:.2f}")

    async def _send_penalty_dm(self, guild_id, user_id, loan, penalty_cycles, days_overdue, guild):
        """發送逾期懲罰 DM"""
        try:
            fetched_user = await self.bot.fetch_user(int(user_id))
            guild_name = guild.name if guild else guild_id
            title = "⚠️ 櫻花債逾期第一週警告" if penalty_cycles == 1 else f"💀 逾期第{penalty_cycles}週！"
            color = discord.Color.orange() if penalty_cycles == 1 else discord.Color.from_rgb(139, 0, 0)
            
            embed = discord.Embed(
                title=title,
                description=f"你在 **{guild_name}** 的借貸已逾期 **{days_overdue}** 天！\n債務已懲罰性增加！",
                color=color
            )
            embed.add_field(name="📋 當前債務", value=f"```yaml\n當前債務: {self.format_number(loan['amount'])} 幽靈幣\n```", inline=False)
            embed.set_footer(text="冥界強制令不可違抗 · 幽幽子")
            await fetched_user.send(embed=embed)
        except Exception as e:
            logger.error(f"❌ 無法向用戶 {user_id} 發送DM: {e}")

    @check_overdue_loans.before_loop
    async def before_check_overdue_loans(self):
        await self.bot.wait_until_ready()
        now = datetime.now(self.tz)
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0 and now.hour >= 0: days_until_monday = 7
        next_monday = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
        await asyncio.sleep((next_monday - now).total_seconds())

    def format_number(self, num: float) -> str:
        if num >= 1e20: return f"{num / 1e20:.2f} 兆京"
        elif num >= 1e16: return f"{num / 1e16:.2f} 京"
        elif num >= 1e12: return f"{num / 1e12:.2f} 兆"
        elif num >= 1e8: return f"{num / 1e8:.2f} 億"
        else: return f"{num:.2f}"

    async def log_transaction(self, guild_id: str, user_id: str, amount: float, transaction_type: str):
        """記錄交易 (使用 to_thread 因為 transactions.json 未納入 DataManager)"""
        path = os.path.join(self.data_manager.economy_dir, "transactions.json")
        try:
            transactions = await asyncio.to_thread(self.data_manager._load_json, path, {})
            transactions.setdefault(guild_id, []).append({
                "user_id": user_id, "amount": float(amount),
                "type": transaction_type, "timestamp": datetime.now(self.tz).isoformat()
            })
            await asyncio.to_thread(self.data_manager._save_json, path, transactions)
        except Exception as e:
            logger.error(f"❌ 交易記錄失敗: {e}")

    def is_blacklisted(self, guild_id: str, user_id: str) -> bool:
        return user_id in self.data_manager.server_vault.get(guild_id, {}).get("blacklist", [])

    def add_to_blacklist(self, guild_id: str, user_id: str):
        sv = self.data_manager.server_vault
        sv.setdefault(guild_id, {}).setdefault("blacklist", [])
        if user_id not in sv[guild_id]["blacklist"]:
            sv[guild_id]["blacklist"].append(user_id)

    def remove_from_blacklist(self, guild_id: str, user_id: str):
        sv = self.data_manager.server_vault
        bl = sv.get(guild_id, {}).get("blacklist", [])
        if user_id in bl: bl.remove(user_id)

    def get_credit(self, guild_id: str, user_id: str) -> int:
        return self.data_manager.credit.get(guild_id, {}).get(user_id, {}).get("score", 10)

    def adjust_credit(self, guild_id: str, user_id: str, delta: int, reason: str):
        credit_data = self.data_manager.credit
        credit_data.setdefault(guild_id, {}).setdefault(user_id, {"score": 10})
        old = credit_data[guild_id][user_id].get("score", 10)
        new = max(0, min(10, old + delta))
        credit_data[guild_id][user_id]["score"] = new
        if new <= 0: self.add_to_blacklist(guild_id, user_id)
        elif old <= 0 and new > 0: self.remove_from_blacklist(guild_id, user_id)
        return old, new

    @discord.slash_command(name="server_bank", description="🌸 與幽幽子的櫻花金庫互動～")
    async def server_bank(self, ctx: discord.ApplicationContext):
        if not await self.data_manager.check_backup_status(ctx, "server_bank"): return
        
        if not await self.data_manager.check_economy_enabled(ctx, "server_bank"):
            return

        guild_id, user_id, owner_id = str(ctx.guild.id), str(ctx.author.id), str(ctx.guild.owner_id)
        
        # 初始化國庫 (若需要)
        if self.initialize_server_vault(guild_id, owner_id):
            await self.data_manager.save_all_async()

        balance = self.data_manager.balance
        personal_bank = self.data_manager.personal_bank
        server_vault = self.data_manager.server_vault

        # 確保用戶數據結構存在
        balance.setdefault(guild_id, {}).setdefault(user_id, 0.0)
        personal_bank.setdefault(guild_id, {}).setdefault(user_id, {"balance": 0.0, "loan": None})

        user_balance = balance[guild_id][user_id]
        pb_balance = personal_bank[guild_id][user_id]["balance"]
        vault_total = server_vault.get(guild_id, {}).get("vault", {}).get("total", 0.0)
        loan = personal_bank[guild_id][user_id].get("loan")

        embed = self._build_main_embed(ctx, user_balance, pb_balance, vault_total, loan)
        view = BankButtonsView(self, ctx, guild_id, user_id, bool(loan and not loan.get("repaid")))

        await ctx.respond(embed=embed, view=view, ephemeral=False)
        view.message = await ctx.interaction.original_response()

    def _build_main_embed(self, ctx, user_balance, pb_balance, vault_total, loan):
        loan_info = ""
        if loan and not loan.get("repaid"):
            try:
                due_date = datetime.fromisoformat(loan["due_date"])
                if due_date.tzinfo is None: due_date = due_date.replace(tzinfo=self.tz)
            except: due_date = datetime.now(self.tz) + timedelta(days=5)
            
            amount_with_interest = round(loan["amount"] * (1 + loan["interest_rate"]), 2)
            days_overdue = max(0, (datetime.now(self.tz) - due_date).days)
            overdue_text = " **逾期超過30天！**" if days_overdue >= 30 else f" **已逾期 {days_overdue} 天！**" if days_overdue > 0 else ""
            
            loan_info = (
                f"\n\n⚠️ **未還款的櫻花債**{overdue_text}\n"
                f"```yaml\n借貸: {self.format_number(loan['amount'])}\n需還: {self.format_number(amount_with_interest)}\n截止: {due_date.strftime('%Y-%m-%d')}\n```"
            )

        embed = discord.Embed(
            title="🌸 幽幽子的櫻花金庫 🌸",
            description=f"歡迎來到 **{ctx.guild.name}** 的金庫!\n幽幽子會好好保管你的幽靈幣哦～",
            color=discord.Color.from_rgb(255, 182, 193)
        )
        embed.add_field(name="🏛️ 冥界國庫", value=f"```yaml\n總額: {self.format_number(vault_total)}\n```", inline=False)
        embed.add_field(name="💰 你的財富", value=f"```yaml\n手頭: {user_balance:,.2f}\n金庫: {self.format_number(pb_balance)}\n總計: {self.format_number(user_balance + pb_balance)}\n```", inline=False)
        if loan_info: embed.add_field(name="📋 借貸詳情", value=loan_info, inline=False)
        embed.set_footer(text="每週一自動檢查逾期 · 幽幽子", icon_url=self.bot.user.display_avatar.url)
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        return embed


class BankButtonsView(View):
    def __init__(self, cog, ctx, guild_id, user_id, has_loan):
        super().__init__(timeout=60)
        self.cog, self.ctx, self.guild_id, self.user_id, self.has_loan = cog, ctx, guild_id, user_id, has_loan
        self.message = None
        if len(self.children) >= 4: self.children[3].disabled = not has_loan

    async def interaction_check(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("這不是你的金庫哦!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        if self.message:
            try: await self.message.edit(view=self)
            except: pass

    async def update_main_embed(self, interaction):
        balance = self.cog.data_manager.balance
        personal_bank = self.cog.data_manager.personal_bank
        server_vault = self.cog.data_manager.server_vault

        user_balance = balance.get(self.guild_id, {}).get(self.user_id, 0.0)
        pb_balance = personal_bank.get(self.guild_id, {}).get(self.user_id, {}).get("balance", 0.0)
        vault_total = server_vault.get(self.guild_id, {}).get("vault", {}).get("total", 0.0)
        loan = personal_bank.get(self.guild_id, {}).get(self.user_id, {}).get("loan")
        
        self.has_loan = bool(loan and not loan.get("repaid"))
        if len(self.children) >= 4: self.children[3].disabled = not self.has_loan

        embed = self.cog._build_main_embed(self.ctx, user_balance, pb_balance, vault_total, loan)
        if self.message:
            try: await self.message.edit(embed=embed, view=self)
            except: pass

    @discord.ui.button(label="存錢", style=discord.ButtonStyle.primary, emoji="💰", row=0)
    async def deposit(self, button, interaction):
        await interaction.response.send_modal(DepositModal(self.cog, self.guild_id, self.user_id, self))

    @discord.ui.button(label="取錢", style=discord.ButtonStyle.success, emoji="💵", row=0)
    async def withdraw(self, button, interaction):
        pb_balance = self.cog.data_manager.personal_bank.get(self.guild_id, {}).get(self.user_id, {}).get("balance", 0.0)
        if pb_balance <= 0:
            await interaction.response.send_message("金庫空空如也哦!", ephemeral=True)
            return
        await interaction.response.send_modal(WithdrawModal(self.cog, self.guild_id, self.user_id, self))

    @discord.ui.button(label="借貸", style=discord.ButtonStyle.danger, emoji="📜", row=0)
    async def borrow(self, button, interaction):
        await interaction.response.send_modal(BorrowModal(self.cog, self.guild_id, self.user_id, self.has_loan, self))

    @discord.ui.button(label="還款", style=discord.ButtonStyle.green, emoji="✅", row=1)
    async def repay(self, button, interaction):
        if not await self.cog.data_manager.check_backup_status(interaction, "bank_repay"): return
        
        if not self.has_loan:
            await interaction.response.send_message("你沒有債務哦!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        personal_bank = self.cog.data_manager.personal_bank
        server_vault = self.cog.data_manager.server_vault
        loan = personal_bank.get(self.guild_id, {}).get(self.user_id, {}).get("loan")
        
        if not loan or loan.get("repaid"):
            await interaction.followup.send("無需還款", ephemeral=True)
            return

        amount_with_interest = round(loan["amount"] * (1 + loan["interest_rate"]), 2)

        async with self.cog.data_manager.balance_lock:
            balance = self.cog.data_manager.balance
            user_balance = balance.get(self.guild_id, {}).get(self.user_id, 0.0)
            if user_balance < amount_with_interest:
                await interaction.followup.send(f"餘額不足！需要 {self.cog.format_number(amount_with_interest)}", ephemeral=True)
                return

            balance[self.guild_id][self.user_id] -= amount_with_interest
            personal_bank[self.guild_id][self.user_id]["loan"] = None
            if self.guild_id in server_vault and "vault" in server_vault[self.guild_id]:
                server_vault[self.guild_id]["vault"]["total"] += loan["amount"]

        await self.cog.data_manager.save_all_async()
        await self.cog.log_transaction(self.guild_id, self.user_id, amount_with_interest, "repay")
        
        credit_cog = self.cog.bot.get_cog("Credit")
        if credit_cog: await credit_cog.recover_on_repay(self.guild_id, self.user_id)

        await self.update_main_embed(interaction)
        await interaction.followup.send(f"還款成功！支付了 {self.cog.format_number(amount_with_interest)} 幽靈幣", ephemeral=True)

    @discord.ui.button(label="結束", style=discord.ButtonStyle.gray, emoji="❌", row=1)
    async def close_bank(self, button, interaction):
        for item in self.children: item.disabled = True
        embed = discord.Embed(title="🌸 金庫已關閉", description="期待下次再見～", color=discord.Color.from_rgb(255, 182, 193))
        embed.set_footer(text="願櫻花守護你的財富 · 幽幽子", icon_url=self.cog.bot.user.display_avatar.url)
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()


class DepositModal(Modal):
    def __init__(self, cog, guild_id, user_id, view):
        super().__init__(title="🌸 存入幽靈幣")
        self.cog, self.guild_id, self.user_id, self.view = cog, guild_id, user_id, view
        self.add_item(InputText(label="存款金額", placeholder="輸入數量...", required=True))

    async def callback(self, interaction):
        if not await self.cog.data_manager.check_backup_status(interaction, "bank_deposit"): return
        await interaction.response.defer(ephemeral=True)
        
        try:
            amount = Decimal(self.children[0].value.strip())
            if amount <= 0: raise ValueError
            amount = float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        except:
            await interaction.followup.send("金額格式錯誤!", ephemeral=True)
            return

        async with self.cog.data_manager.balance_lock:
            balance = self.cog.data_manager.balance
            personal_bank = self.cog.data_manager.personal_bank
            user_balance = balance.get(self.guild_id, {}).get(self.user_id, 0.0)
            
            if user_balance < amount:
                await interaction.followup.send(f"手頭只有 {user_balance:,.2f}，餘額不足!", ephemeral=True)
                return

            balance[self.guild_id][self.user_id] -= amount
            personal_bank.setdefault(self.guild_id, {}).setdefault(self.user_id, {"balance": 0.0, "loan": None})["balance"] += amount

        await self.cog.data_manager.save_all_async()
        await self.cog.log_transaction(self.guild_id, self.user_id, amount, "deposit")
        await self.view.update_main_embed(interaction)
        await interaction.followup.send(f"成功存入 **{amount:,.2f}** 幽靈幣!", ephemeral=True)


class WithdrawModal(Modal):
    def __init__(self, cog, guild_id, user_id, view):
        super().__init__(title="🌸 取出幽靈幣")
        self.cog, self.guild_id, self.user_id, self.view = cog, guild_id, user_id, view
        self.add_item(InputText(label="取款金額", placeholder="輸入數量...", required=True))

    async def callback(self, interaction):
        if not await self.cog.data_manager.check_backup_status(interaction, "bank_withdraw"): return
        await interaction.response.defer(ephemeral=True)
        
        try:
            amount = Decimal(self.children[0].value.strip())
            if amount <= 0: raise ValueError
            amount = float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        except:
            await interaction.followup.send("金額格式錯誤!", ephemeral=True)
            return

        async with self.cog.data_manager.balance_lock:
            balance = self.cog.data_manager.balance
            personal_bank = self.cog.data_manager.personal_bank
            bank_balance = personal_bank.get(self.guild_id, {}).get(self.user_id, {}).get("balance", 0.0)
            
            if bank_balance < amount:
                await interaction.followup.send(f"金庫只有 {self.cog.format_number(bank_balance)}，餘額不足!", ephemeral=True)
                return

            personal_bank[self.guild_id][self.user_id]["balance"] -= amount
            balance.setdefault(self.guild_id, {}).setdefault(self.user_id, 0.0)
            balance[self.guild_id][self.user_id] += amount

        await self.cog.data_manager.save_all_async()
        await self.cog.log_transaction(self.guild_id, self.user_id, amount, "withdraw")
        await self.view.update_main_embed(interaction)
        await interaction.followup.send(f"成功取出 **{amount:,.2f}** 幽靈幣!", ephemeral=True)


class BorrowModal(Modal):
    def __init__(self, cog, guild_id, user_id, has_loan, view):
        super().__init__(title="🌸 向國庫借貸")
        self.cog, self.guild_id, self.user_id, self.has_loan, self.view = cog, guild_id, user_id, has_loan, view
        self.add_item(InputText(label="借貸金額", placeholder="輸入數量...", required=True))

    async def callback(self, interaction):
        if not await self.cog.data_manager.check_backup_status(interaction, "bank_borrow"): return
        await interaction.response.defer(ephemeral=True)
        
        try:
            amount = Decimal(self.children[0].value.strip())
            if amount <= 0: raise ValueError
            amount = float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        except:
            await interaction.followup.send("金額格式錯誤!", ephemeral=True)
            return

        if self.cog.is_blacklisted(self.guild_id, self.user_id):
            await interaction.followup.send("你在黑名單中，無法借貸!", ephemeral=True)
            return

        credit_score = self.cog.get_credit(self.guild_id, self.user_id)
        if credit_score <= 0:
            await interaction.followup.send("信譽歸零，無法借貸!", ephemeral=True)
            return

        server_vault = self.cog.data_manager.server_vault
        vault_total = server_vault.get(self.guild_id, {}).get("vault", {}).get("total", 0.0)
        if vault_total < amount:
            await interaction.followup.send(f"國庫餘額不足 (只有 {self.cog.format_number(vault_total)})", ephemeral=True)
            return

        interest_rate = calculate_interest_rate(amount)
        credit_penalty_applied = False

        async with self.cog.data_manager.balance_lock:
            balance = self.cog.data_manager.balance
            personal_bank = self.cog.data_manager.personal_bank
            
            # 再次借貸扣信譽
            existing_loan = personal_bank.get(self.guild_id, {}).get(self.user_id, {}).get("loan")
            if existing_loan and not existing_loan.get("repaid"):
                self.cog.adjust_credit(self.guild_id, self.user_id, -3, "有未還貸款時再次借貸")
                credit_penalty_applied = True
                credit_score = self.cog.get_credit(self.guild_id, self.user_id)

            server_vault[self.guild_id]["vault"]["total"] -= amount
            balance.setdefault(self.guild_id, {}).setdefault(self.user_id, 0.0)
            balance[self.guild_id][self.user_id] += amount

            personal_bank.setdefault(self.guild_id, {}).setdefault(self.user_id, {"balance": 0.0, "loan": None})
            current_time = datetime.now(self.cog.tz)
            loan_data = personal_bank[self.guild_id][self.user_id].get("loan")

            if loan_data and not loan_data.get("repaid"):
                old_amount = loan_data["amount"]
                new_total = old_amount + amount
                blended_rate = (old_amount * loan_data["interest_rate"] + amount * interest_rate) / new_total
                loan_data["amount"] = new_total
                loan_data["interest_rate"] = round(blended_rate, 4)
                loan_data["due_date"] = (current_time + timedelta(days=5)).isoformat()
            else:
                loan_data = {
                    "amount": amount, "interest_rate": interest_rate,
                    "borrowed_at": current_time.isoformat(),
                    "due_date": (current_time + timedelta(days=5)).isoformat(),
                    "repaid": False, "last_penalty_cycle": 0
                }
            personal_bank[self.guild_id][self.user_id]["loan"] = loan_data

        await self.cog.data_manager.save_all_async()
        await self.cog.log_transaction(self.guild_id, self.user_id, amount, "borrow")
        await self.view.update_main_embed(interaction)

        embed = discord.Embed(title="🌸 借貸成功！", color=discord.Color.from_rgb(255, 215, 0))
        embed.add_field(name="💰 金額", value=f"**{amount:,.2f}** 幽靈幣", inline=False)
        embed.add_field(name="📋 條款", value=f"```yaml\n利息: {interest_rate * 100:.0f}%\n需還: {self.cog.format_number(loan_data['amount'] * (1 + interest_rate))}\n截止: {datetime.fromisoformat(loan_data['due_date']).strftime('%Y-%m-%d')}\n```", inline=False)
        if credit_penalty_applied:
            embed.add_field(name="💳 信譽警告", value=f"⚠️ 再次借貸，信譽 **-3**！\n{self.cog._credit_bar(credit_score)}", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(ServerBank(bot))
