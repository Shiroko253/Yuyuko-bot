import discord
from discord.ext import commands
from discord import ApplicationContext, Interaction
import logging
from datetime import datetime

logger = logging.getLogger("SakuraBot.FishBack")

RARITY_ORDER = {
    "unknown": 0,
    "deify": 1,
    "legendary": 2,
    "rare": 3,
    "uncommon": 4,
    "common": 5,
}

RARITY_COLORS = {
    "unknown": discord.Color.dark_gray(),
    "deify": discord.Color.gold(),
    "legendary": discord.Color.orange(),
    "rare": discord.Color.purple(),
    "uncommon": discord.Color.blue(),
    "common": discord.Color.green(),
}

RARITY_NAMES = {
    "unknown": "未知",
    "deify": "神級",
    "legendary": "傳奇",
    "rare": "史詩",
    "uncommon": "不常見",
    "common": "普通",
}

RARITY_EMOJIS = {
    "unknown": "❓",
    "deify": "👑",
    "legendary": "🌟",
    "rare": "💎",
    "uncommon": "🔷",
    "common": "🌸",
}


def get_rarity_sort_index(fish: dict) -> int:
    return RARITY_ORDER.get(fish.get("rarity", "unknown"), 99)


class PageButton(discord.ui.Button):
    def __init__(self, label: str, target_page: int, view_ref):
        super().__init__(label=label, style=discord.ButtonStyle.blurple)
        self.target_page = target_page
        self.view_ref = view_ref

    async def callback(self, interaction: Interaction):
        if interaction.user.id != self.view_ref.user_id:
            await interaction.response.send_message(
                "🌸 櫻花湖的背包只能由主人自己翻閱哦～", ephemeral=True
            )
            return

        self.view_ref.page = self.target_page
        self.view_ref.update_buttons()
        embed = self.view_ref.get_embed()

        await interaction.response.edit_message(embed=embed, view=self.view_ref)
        logger.info(f"{interaction.user} 翻至第 {self.target_page + 1} 頁")


class FishBackView(discord.ui.View):
    def __init__(self, user_id: int, guild_id: str, fish_list: list, bot: discord.Bot, page: int = 0):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.guild_id = guild_id
        self.bot = bot
        self.fish_list = sorted(fish_list, key=get_rarity_sort_index)
        self.page = page
        self.fishes_per_page = 5
        self.max_page = max(0, (len(self.fish_list) - 1) // self.fishes_per_page)
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        if self.page > 0:
            self.add_item(PageButton("⬅️ 前一頁（櫻花還沒飄完）", self.page - 1, self))
        if self.page < self.max_page:
            self.add_item(PageButton("下一頁 ➡️（還有更多魚等著你）", self.page + 1, self))

    def get_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🌸 幽幽子的櫻花漁獲背包",
            color=discord.Color.from_rgb(255, 182, 193)
        )

        start = self.page * self.fishes_per_page
        end = start + self.fishes_per_page
        fishes_on_page = self.fish_list[start:end]

        if not fishes_on_page:
            embed.description = (
                "❌ 你還沒有捕到任何魚～\n\n"
                "櫻花湖靜待你的身影，快去使用 `/fishing` 試試手氣吧！"
            )
            embed.set_footer(text="幽幽子在湖邊等你來釣魚～")
            return embed

        embed.description = (
            f"📄 **頁數:** {self.page + 1} / {self.max_page + 1}\n"
            f"🎯 **總計:** {len(self.fish_list)} 條魚\n"
            f"📊 **排序:** 未知 → 神級 → 傳奇 → 史詩 → 不常見 → 普通\n"
        )

        for idx, fish in enumerate(fishes_on_page, start=1):
            rarity = fish.get("rarity", "unknown")
            rarity_name = RARITY_NAMES.get(rarity, "未知")
            rarity_emoji = RARITY_EMOJIS.get(rarity, "❓")
            fish_name = fish.get("name", "未知魚種")
            size = fish.get("size", 0)
            rod = fish.get("rod", "未知釣竿")

            caught_at = fish.get("caught_at", "未知時間")
            try:
                # 相容 Python 3.10 以下的 ISO 格式解析
                caught_time = datetime.fromisoformat(caught_at.replace('Z', '+00:00'))
                time_str = caught_time.strftime("%Y-%m-%d %H:%M")
            except Exception:
                time_str = "未知時間"

            field_value = (
                f"{rarity_emoji} **稀有度:** {rarity_name}\n"
                f"⚖️ **重量:** {size:.2f} 公斤\n"
                f"🎣 **釣竿:** {rod}\n"
                f"🕐 **捕獲時間:** {time_str}"
            )

            embed.add_field(
                name=f"🐟 {start + idx}. {fish_name}",
                value=field_value,
                inline=False
            )

        embed.set_footer(
            text="可用下方櫻花按鈕翻頁 • 幽幽子祝你漁獲豐收～",
            icon_url=self.bot.user.display_avatar.url
        )
        return embed

    async def on_timeout(self):
        # Ephemeral 訊息無法由 Bot 主動編輯，故僅停止計時器與清空按鈕
        self.clear_items()
        self.stop()
        logger.info(f"用戶 {self.user_id} 的漁獲背包已超時關閉")


class FishBack(commands.Cog):
    """
    ✿ 冥界櫻花湖釣魚背包 ✿
    幽幽子帶你一頁頁翻閱過往釣魚的靈魂回憶～
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.data_manager = bot.data_manager
        logger.info("櫻花湖釣魚背包系統已啟動")

    @discord.slash_command(
        name="fish_back",
        description="幽幽子帶你翻閱靈魂釣魚背包～"
    )
    async def fish_back(self, ctx: ApplicationContext):
        # 純查詢指令，不需要 check_backup_status 攔截
        await ctx.defer(ephemeral=True)
        
        if not await self.data_manager.check_economy_enabled(ctx, "fish_back"):
            return

        user_id = str(ctx.user.id)
        guild_id = str(ctx.guild.id) if ctx.guild else "dm"

        try:
            # [Debug 修復 #1 & #2] 徹底移除硬碟讀取與 save_lock！
            # 直接讀取記憶體中的 fishingbackpack，瞬間完成，且不阻塞其他寫入指令。
            fishing_data = self.data_manager.fishingbackpack

            # [Debug 修復 #3] 使用 .get() 鏈式呼叫防呆，避免 KeyError 崩潰
            user_fishes = fishing_data.get(user_id, {}).get(guild_id, {}).get('fishes', [])

            if not user_fishes:
                await ctx.followup.send(
                    "❌ 你還沒有捕到任何魚～\n\n"
                    "櫻花湖靜待你的身影！快去使用 `/fishing` 試試手氣吧！",
                    ephemeral=True
                )
                logger.info(f"{ctx.user} 尚未有任何釣魚記錄")
                return

            view = FishBackView(ctx.user.id, guild_id, user_fishes, self.bot, page=0)
            embed = view.get_embed()

            # 因為已經 defer，這裡必須用 followup.send
            await ctx.followup.send(embed=embed, view=view, ephemeral=True)
            logger.info(f"{ctx.user} 查看了釣魚背包，共 {len(user_fishes)} 條魚")

        except Exception as e:
            logger.error(f"查看釣魚背包時發生錯誤: {e}", exc_info=True)
            try:
                if ctx.response.is_done():
                    await ctx.followup.send(
                        "❌ 啊呀…櫻花湖的記憶有些模糊了～\n幽幽子需要稍作休息，請稍後再試！",
                        ephemeral=True
                    )
                else:
                    await ctx.respond(
                        "❌ 啊呀…櫻花湖的記憶有些模糊了～\n幽幽子需要稍作休息，請稍後再試！",
                        ephemeral=True
                    )
            except Exception:
                pass


def setup(bot: discord.Bot):
    bot.add_cog(FishBack(bot))
    logger.info("櫻花湖釣魚背包系統已載入")
