from decimal import Decimal, ROUND_DOWN
import discord
from discord.ext import commands
import logging
import os
import traceback

logger = logging.getLogger("SakuraBot.commands.addmoney")
AUTHOR_ID = int(os.getenv("AUTHOR_ID", 0))


class EconomyAdmin(commands.Cog):
    """幽幽子的經濟系統管理指令"""

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    async def _send_error_report(self, ctx: discord.ApplicationContext, error_msg: str, command_name: str, **kwargs):
        """輔助方法：發送錯誤報告給 AUTHOR_ID"""
        if not AUTHOR_ID:
            return
            
        owner = self.bot.get_user(AUTHOR_ID)
        if not owner:
            try:
                # 如果 get_user 失敗 (不在快取中)，嘗試 fetch_user
                owner = await self.bot.fetch_user(AUTHOR_ID)
            except Exception:
                return

        try:
            error_embed = discord.Embed(
                title=f"🚨 {command_name} 錯誤報告",
                description=f"```python\n{error_msg[:1900]}\n```",
                color=discord.Color.red()
            )
            error_embed.add_field(name="觸發者", value=f"{ctx.user.mention} ({ctx.user.id})")
            for k, v in kwargs.items():
                error_embed.add_field(name=k, value=str(v), inline=True)
            await owner.send(embed=error_embed)
        except Exception:
            pass

    @discord.slash_command(
        name="addmoney",
        description="給用戶增加幽靈幣（只有幽幽子的特定朋友可以用～）"
    )
    async def addmoney(
        self,
        ctx: discord.ApplicationContext,
        member: discord.Member,
        amount: str
    ):
        if not await self.data_manager.check_economy_enabled(ctx, "addmoney"):
            return
        """管理員添加金錢指令"""
        try:
            if not hasattr(self.bot, "data_manager") or not await self.bot.data_manager.check_backup_status(ctx, "addmoney"):
                return
            
            if ctx.user.id != AUTHOR_ID:
                await ctx.respond("❌ 嗯？這個命令只有幽幽子特別信任的人才能用唷～", ephemeral=True)
                return

            if not ctx.guild:
                await ctx.respond("❌ 這個命令只能在伺服器裡用唷～", ephemeral=True)
                return

            try:
                amount_decimal = Decimal(amount)
                if amount_decimal <= 0:
                    raise ValueError("金額必須大於 0")
                amount_decimal = amount_decimal.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            except Exception:
                await ctx.respond("❌ 金額格式不對哦～請輸入正數（像 100 或 100.00 這樣）", ephemeral=True)
                return

            if not hasattr(self.bot, "data_manager"):
                await ctx.respond("❌ 幽幽子的錢包暫時找不到了，請稍後再試～", ephemeral=True)
                logger.error("data_manager 不存在")
                return

            data_manager = self.bot.data_manager

            if member.id == self.bot.user.id:
                await ctx.respond("❌ 幽幽子自己可不需要幽靈幣呢～", ephemeral=True)
                return

            if member.bot:
                await ctx.respond("❌ 機器人不需要幽靈幣啦～", ephemeral=True)
                return

            guild_id = str(ctx.guild.id)
            recipient_id = str(member.id)

            # [Debug 修復 #1] 徹底移除全量遞迴轉換，改為只針對「目標用戶」進行單一數值轉換
            # 原版 convert_float_to_decimal 會遍歷整個 balance 字典，當用戶量大時會嚴重阻塞 Event Loop
            async with data_manager.balance_lock:
                # 1. 讀取舊餘額 (float -> Decimal)
                old_balance_float = data_manager.balance.get(guild_id, {}).get(recipient_id, 0.0)
                old_balance = Decimal(str(old_balance_float))
                
                # 2. 計算新餘額
                new_balance = old_balance + amount_decimal
                new_balance = new_balance.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                
                # 3. 確保字典結構存在並寫入新餘額 (Decimal -> float)
                if guild_id not in data_manager.balance:
                    data_manager.balance[guild_id] = {}
                data_manager.balance[guild_id][recipient_id] = float(new_balance)

            # [Debug 修復 #2] 使用 save_all_async 確保異步保存
            await data_manager.save_all_async()

            embed = discord.Embed(
                title="💰 幽靈幣悄悄增加啦",
                description=(
                    f"{member.mention} 的錢包裡悄悄多了 **{amount_decimal:.2f} 幽靈幣**～\n\n"
                    f"**舊餘額:** {old_balance:.2f}\n"
                    f"**新餘額:** {new_balance:.2f}\n"
                    f"**增加:** +{amount_decimal:.2f}\n\n"
                    "幽幽子祝你使用愉快♪"
                ),
                color=discord.Color.purple()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(
                text="幽幽子的幽靈幣系統 · 美味又放心",
                # [Debug 修復 #3] 使用 display_avatar 避免 None 判斷
                icon_url=self.bot.user.display_avatar.url 
            )

            await ctx.respond(embed=embed)
            logger.info(
                f"管理員 {ctx.user} ({ctx.user.id}) 給 {member} ({member.id}) "
                f"增加了 {amount_decimal:.2f} 幽靈幣，新餘額: {new_balance:.2f}"
            )

        except Exception as e:
            err_trace = traceback.format_exc()
            logger.error(f"addmoney 指令執行錯誤: {e}\n{err_trace}")
            await ctx.respond("❌ 哎呀，幽幽子的系統有點小狀況，請稍後再來～", ephemeral=True)
            
            # 發送錯誤報告
            await self._send_error_report(
                ctx, err_trace, "AddMoney", 
                目標=f"{member.mention} ({member.id})", 
                金額=amount
            )

    @discord.slash_command(
        name="setmoney",
        description="設置用戶的幽靈幣數量（管理員專用）"
    )
    async def setmoney(
        self,
        ctx: discord.ApplicationContext,
        member: discord.Member,
        amount: str
    ):
        """設置用戶金錢（而非增加）"""
        try:
            if ctx.user.id != AUTHOR_ID:
                await ctx.respond("❌ 此指令需要最高權限～", ephemeral=True)
                return

            if not ctx.guild:
                await ctx.respond("❌ 這個命令只能在伺服器裡用唷～", ephemeral=True)
                return

            try:
                amount_decimal = Decimal(amount)
                if amount_decimal < 0:
                    raise ValueError("金額不能為負數")
                amount_decimal = amount_decimal.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            except Exception:
                await ctx.respond("❌ 金額格式錯誤，請輸入非負數", ephemeral=True)
                return

            if not hasattr(self.bot, "data_manager"):
                await ctx.respond("❌ 數據管理器不存在", ephemeral=True)
                return

            if member.bot:
                await ctx.respond("❌ 機器人不需要幽靈幣", ephemeral=True)
                return

            data_manager = self.bot.data_manager
            guild_id = str(ctx.guild.id)
            recipient_id = str(member.id)

            # [Debug 修復 #1] 同樣移除全量遞迴轉換，效能 O(1)
            async with data_manager.balance_lock:
                old_balance_float = data_manager.balance.get(guild_id, {}).get(recipient_id, 0.0)
                old_balance = Decimal(str(old_balance_float))
                
                new_balance = amount_decimal.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                
                if guild_id not in data_manager.balance:
                    data_manager.balance[guild_id] = {}
                data_manager.balance[guild_id][recipient_id] = float(new_balance)

            await data_manager.save_all_async()

            embed = discord.Embed(
                title="⚙️ 幽靈幣已設置",
                description=(
                    f"{member.mention} 的餘額已設置為 **{amount_decimal:.2f} 幽靈幣**\n\n"
                    f"**舊餘額:** {old_balance:.2f}\n"
                    f"**新餘額:** {amount_decimal:.2f}"
                ),
                color=discord.Color.blue()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(
                text="幽幽子的幽靈幣系統 · 美味又放心",
                icon_url=self.bot.user.display_avatar.url
            )

            await ctx.respond(embed=embed)
            logger.info(f"管理員 {ctx.user} 將 {member} 的餘額設置為 {amount_decimal:.2f}")

        except Exception as e:
            err_trace = traceback.format_exc()
            logger.error(f"setmoney 錯誤: {e}\n{err_trace}")
            await ctx.respond("❌ 執行失敗", ephemeral=True)
            
            # [Debug 修復 #4] 補上 setmoney 的錯誤報告機制
            await self._send_error_report(
                ctx, err_trace, "SetMoney", 
                目標=f"{member.mention} ({member.id})", 
                金額=amount
            )


def setup(bot: discord.Bot):
    bot.add_cog(EconomyAdmin(bot))
    # [修復] 將生硬的英文/中文日誌改為符合幽幽子風格的冥界語氣
    logger.info("💰 冥界經濟管理後門已於櫻花樹下開啟")
