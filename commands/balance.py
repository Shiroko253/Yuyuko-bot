import discord
from discord.ext import commands
import random
import logging

logger = logging.getLogger("SakuraBot.commands.balance")


class Balance(commands.Cog):
    """
    ✿ 幽幽子的幽靈幣餘額窺探 ✿
    讓幽幽子幫你優雅地查查錢包吧～
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.yuyuko_comments = [
            "嘻嘻，你的幽靈幣數量真有趣呢～",
            "這些幽靈幣，會帶來什麼樣的命運呢？",
            "靈魂與幽靈幣的交響曲，幽幽子很喜歡哦～",
            "你的幽靈幣閃閃發光，櫻花都忍不住飄落了～",
            "這樣的數量，會讓幽靈們羨慕吧？",
            "冥界的財富，就像櫻花一樣美麗呢～",
            "妖夢～快來看看這個數字！"
        ]
        self.yuyuko_error_comments = [
            "下次再試試吧～靈魂的波動有時會捉弄我們哦～",
            "幽幽子也會偶爾迷路呢…下次會順利的！",
            "哎呀～幽幽子的小手突然滑了一下，下次一定查到！",
            "冥界的櫻花飄亂了，稍等片刻再試吧～"
        ]

    @staticmethod
    def format_number(num: float) -> str:
        """幽幽子溫柔地把大數字變成美麗的單位～"""
        if num >= 1e20:
            return f"{num / 1e20:.2f} 兆京"
        elif num >= 1e16:
            return f"{num / 1e16:.2f} 京"
        elif num >= 1e12:
            return f"{num / 1e12:.2f} 兆"
        elif num >= 1e8:
            return f"{num / 1e8:.2f} 億"
        elif num >= 1e4:
            return f"{num / 1e4:.2f} 萬"
        else:
            return f"{num:,.2f}"

    @discord.slash_command(
        name="balance",
        description="幽幽子為你窺探幽靈幣的數量～"
    )
    async def balance(self, ctx: discord.ApplicationContext):
        """查詢幽靈幣餘額"""
        if not await self.data_manager.check_economy_enabled(ctx, "balance"):
            return
        try:
            if not ctx.guild:
                embed = discord.Embed(
                    title="🌸 無法查詢幽靈幣 🌸",
                    description="幽幽子只能在伺服器裡窺探幽靈幣哦～請到伺服器頻道使用指令！",
                    color=discord.Color.red()
                )
                embed.set_footer(text="僅限伺服器查詢")
                await ctx.respond(embed=embed, ephemeral=True)
                return

            if not hasattr(self.bot, "data_manager"):
                await ctx.respond("❌ 幽幽子的錢包系統暫時找不到了...", ephemeral=True)
                logger.error("data_manager 不存在")
                return

            data_manager = self.bot.data_manager
            guild_id = str(ctx.guild.id)
            user_id = str(ctx.user.id)

            # [Debug 修復 #1] 極致優化：純記憶體讀取，不觸發任何鎖與硬碟寫入
            # 原版會為了「新用戶初始化」而呼叫 save_all_async()，導致 I/O 風暴
            # 現在直接從記憶體字典讀取，若不存在則預設為 0.0，耗時 < 0.0001 秒
            balance = data_manager.balance.get(guild_id, {}).get(user_id, 0.0)
            
            formatted_balance = self.format_number(balance)

            # 根據餘額決定顏色與身份
            if balance >= 1e8:
                color = discord.Color.gold()
                status = "💰 冥界的富豪"
            elif balance >= 1e6:
                color = discord.Color.from_rgb(255, 215, 0)
                status = "💎 櫻花樹下的財主"
            elif balance >= 1e4:
                color = discord.Color.from_rgb(147, 112, 219)
                status = "🌸 小有積蓄"
            elif balance >= 1000:
                color = discord.Color.from_rgb(255, 182, 193)
                status = "🎋 平凡的靈魂"
            else:
                color = discord.Color.light_gray()
                status = "🍃 清貧的旅人"

            embed = discord.Embed(
                title="🌸 幽幽子的幽靈幣窺探 🌸",
                description=(
                    f"**{ctx.user.display_name}**，讓幽幽子為你揭示吧～\n\n"
                    f"**身份:** {status}\n"
                    f"**幽靈幣餘額:** `{formatted_balance}` 💴\n\n"
                    f"在這片靈魂之地，你的財富隨風飄舞～"
                ),
                color=color
            )

            if balance >= 1e4:
                embed.add_field(
                    name="📊 精確數值",
                    value=f"`{balance:,.2f}` 幽靈幣",
                    inline=False
                )

            embed.set_thumbnail(url=ctx.user.display_avatar.url)
            embed.set_footer(text=random.choice(self.yuyuko_comments))
            embed.timestamp = discord.utils.utcnow()

            await ctx.respond(embed=embed, ephemeral=False)
            logger.info(f"{ctx.user} 查詢了餘額: {balance:.2f}")

        except Exception as e:
            logger.exception(f"餘額查詢指令發生錯誤: {e}")

            error_embed = discord.Embed(
                title="🌸 哎呀，靈魂出錯了！🌸",
                description="幽幽子試圖窺探你的幽靈幣時，發生了一點小意外…\n\n請稍後再試，或聯繫管理員～",
                color=discord.Color.red()
            )
            error_embed.set_footer(text=random.choice(self.yuyuko_error_comments))

            try:
                await ctx.respond(embed=error_embed, ephemeral=True)
            except discord.errors.NotFound:
                logger.warning("無法回應查詢（interaction 已過期）")
            except Exception as followup_error:
                logger.error(f"發送錯誤訊息失敗: {followup_error}")


def setup(bot: discord.Bot):
    """將幽幽子的餘額查詢功能裝進 bot 裡"""
    bot.add_cog(Balance(bot))
    logger.info("餘額查詢系統已載入")
