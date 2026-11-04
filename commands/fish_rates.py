import discord
from discord.ext import commands
from discord import ApplicationContext
import asyncio
import logging
from datetime import datetime, timezone
import io
import matplotlib
matplotlib.use('Agg')  # 必須在 import pyplot 之前設定
import matplotlib.pyplot as plt

logger = logging.getLogger("SakuraBot.FishRates")


class FishRates(commands.Cog):
    """幽幽子的櫻花湖機率展示系統，揭開冥界的奧秘"""

    def __init__(self, bot):
        self.bot = bot
        
        # [Debug 修復] 初始化繪圖鎖為 None
        # 原因：Python 3.10+ 規定 asyncio.Lock 必須在 running event loop 中建立
        # 我們將在第一次執行指令時（此時必定有 event loop）再實體化它
        self.plot_lock = None 
        
        # rcParams 移至 __init__，只設定一次
        plt.rcParams['axes.unicode_minus'] = False
        logger.info("櫻花湖機率展示系統已初始化～")

    def get_rarity_weights(self) -> dict:
        """從 Fish Cog 讀取實際計算的權重，確保顯示機率與實際一致"""
        try:
            fish_cog = self.bot.get_cog("Fish")
            if fish_cog:
                fish_data = fish_cog.get_fish_data()
                if fish_data:
                    return fish_cog.calculate_rarity_weights(fish_data)
        except Exception as e:
            logger.warning(f"無法從 Fish Cog 計算權重: {e}")

        logger.warning("使用預設稀有度權重")
        return {
            "common": 50.0,
            "uncommon": 30.0,
            "rare": 15.0,
            "legendary": 4.0,
            "deify": 1.0
        }

    def get_rarity_display_info(self) -> dict:
        return {
            "common":    {"name": "普通", "color": "#57F287", "emoji": "🟢"},
            "uncommon":  {"name": "罕見", "color": "#3498DB", "emoji": "🔵"},
            "rare":      {"name": "稀有", "color": "#9B59B6", "emoji": "🟣"},
            "legendary": {"name": "傳說", "color": "#E67E22", "emoji": "🟠"},
            "deify":     {"name": "神格", "color": "#F1C40F", "emoji": "⭐"},
            "unknown":   {"name": "未知", "color": "#95A5A6", "emoji": "❓"},
        }

    def create_rarity_pie_chart(self) -> io.BytesIO:
        """創建稀有度機率餅圖 (同步方法，將在背景執行緒中執行)"""
        rarity_weights = self.get_rarity_weights()
        display_info = self.get_rarity_display_info()

        sorted_items = sorted(rarity_weights.items(), key=lambda x: x[1], reverse=True)
        rarities = [item[0] for item in sorted_items]
        probabilities = [item[1] for item in sorted_items]

        labels = []
        colors = []
        for r in rarities:
            info = display_info.get(r, {"name": r.capitalize(), "color": "#95A5A6"})
            labels.append(f"{r.capitalize()}\n{rarity_weights[r]}%")
            colors.append(info["color"])

        explode = []
        for prob in probabilities:
            if prob <= 1.0:
                explode.append(0.15)
            elif prob <= 5.0:
                explode.append(0.1)
            elif prob <= 20.0:
                explode.append(0.05)
            else:
                explode.append(0.02)

        # 用 try/finally 確保 plt.close() 一定執行，防止記憶體洩漏
        plt.figure(figsize=(10, 8))
        try:
            wedges, texts, autotexts = plt.pie(
                probabilities,
                labels=labels,
                colors=colors,
                autopct='%1.1f%%',
                startangle=90,
                textprops={'fontsize': 12, 'weight': 'bold'},
                explode=explode
            )

            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontsize(14)
                autotext.set_weight('bold')

            legend_labels = [
                f"{r.capitalize()} ({rarity_weights[r]}%)" for r in rarities
            ]
            plt.legend(
                wedges,
                legend_labels,
                title="Rarity Rates",
                loc="center left",
                bbox_to_anchor=(1, 0, 0.5, 1),
                fontsize=11
            )

            plt.tight_layout()

            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
            buffer.seek(0)
            return buffer
        finally:
            plt.close()

    @discord.slash_command(
        name="fish_rates",
        description="🌸 查看櫻花湖的釣魚機率～幽幽子為你揭開冥界的奧秘"
    )
    async def fish_rates(self, ctx: ApplicationContext):
        await ctx.defer()
        
        if not await self.data_manager.check_economy_enabled(ctx, "fish_rates"):
            return

        try:
            rarity_weights = self.get_rarity_weights()
            display_info = self.get_rarity_display_info()

            # [Debug 修復] 確保 plot_lock 在 running event loop 中被實體化 (相容 Python 3.10+)
            if self.plot_lock is None:
                self.plot_lock = asyncio.Lock()

            # [Debug 修復] 使用 asyncio.Lock 確保同一時間只有一個繪圖任務在執行
            # 這能徹底解決 matplotlib.pyplot 非執行緒安全導致的多執行緒崩潰問題
            async with self.plot_lock:
                chart_buffer = await asyncio.to_thread(self.create_rarity_pie_chart)
            
            file = discord.File(chart_buffer, filename="sakura_fishing_rates.png")

            sorted_items = sorted(rarity_weights.items(), key=lambda x: x[1], reverse=True)
            prob_lines = []
            for rarity, weight in sorted_items:
                info = display_info.get(rarity, {"name": rarity.capitalize(), "emoji": "⚪"})
                prob_lines.append(
                    f"{info['emoji']} {info['name']} ({rarity.capitalize()}): **{weight}%**"
                )

            embed = discord.Embed(
                title="🌸 櫻花湖釣魚機率統計 🌸",
                description=(
                    "幽幽子為你展示櫻花湖中各種魚的出現機率～\n"
                    "櫻花隨風飄落，魚兒隨緣而來，祝你釣魚順利！\n\n"
                    "**機率分布：**\n" + "\n".join(prob_lines)
                ),
                color=discord.Color.from_rgb(255, 182, 193),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_image(url="attachment://sakura_fishing_rates.png")
            embed.set_footer(text="幽幽子祝你釣到心儀的魚～記得多釣幾次增加機會哦！")

            await ctx.followup.send(embed=embed, file=file)
            logger.info(f"用戶 {ctx.user} ({ctx.user.id}) 查看了釣魚機率")

        except Exception as e:
            logger.error(f"生成釣魚機率圖表時發生錯誤: {e}", exc_info=True)
            try:
                if ctx.response.is_done():
                    await ctx.followup.send(
                        "幽幽子在繪製櫻花圖表時迷糊了～請稍後再試！🌸",
                        ephemeral=True
                    )
                else:
                    await ctx.respond(
                        "幽幽子在繪製櫻花圖表時迷糊了～請稍後再試！🌸",
                        ephemeral=True
                    )
            except Exception:
                pass


def setup(bot):
    bot.add_cog(FishRates(bot))
    logger.info("FishRates Cog 已載入，機率餅圖等待展示～")
