import discord
from discord.ext import commands
import logging

logger = logging.getLogger("SakuraBot.ResetJob")


class ResetJob(commands.Cog):
    """
    🌸 幽幽子的職業重置之舞 🌸
    幫助迷失的靈魂放下舊身份，
    在櫻花樹下準備迎接新的緣分～
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.data_manager = bot.data_manager
        logger.info("🌸 職業重置術式已於冥界花園中甦醒")

    @discord.slash_command(
        name="reset_job",
        description="🌸 放下當前職業，讓靈魂回歸虛無"
    )
    async def reset_job(self, ctx: discord.ApplicationContext):
        # [Debug 修復 #1] 加入在線備份攔截
        if not await self.data_manager.check_backup_status(ctx, "reset_job"):
            return
    
        if not await self.data_manager.check_economy_enabled(ctx, "reset_job"):
            return
    
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)

        # [Debug 修復 #2] 徹底移除硬碟讀寫！直接讀取記憶體中的 user_config
        user_config = self.data_manager.user_config

        if guild_id not in user_config:
            user_config[guild_id] = {}
        if user_id not in user_config[guild_id]:
            user_config[guild_id][user_id] = {}

        user_info = user_config[guild_id][user_id]
        current_job = user_info.get("job", None)

        if not current_job or current_job == "無職業":
            embed = discord.Embed(
                title="🌸 靈魂本就虛無",
                description=(
                    "呼呼～你本來就沒有職業呢!\n"
                    "靈魂如櫻花般純淨，無需重置～\n\n"
                    "想要選擇職業的話，可以使用 `/choose_job` 命令哦!"
                ),
                color=discord.Color.gold()
            )
            embed.set_footer(
                text="虛無本身也是一種美好 · 幽幽子",
                icon_url=self.bot.user.display_avatar.url  # [Debug 修復 #3]
            )
            embed.set_thumbnail(url=ctx.author.display_avatar.url)
            await ctx.respond(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="🌸 櫻花樹下的決斷",
            description=(
                f"你當前的職業是: **`{current_job}`**\n\n"
                f"一旦放下這份身份，就如同櫻花凋零般無法復原...\n"
                f"靈魂將重新回歸虛無，等待新的緣分降臨。\n\n"
                f"💭 **真的要放棄現有職業嗎?**"
            ),
            color=discord.Color.from_rgb(255, 192, 203)
        )
        embed.add_field(
            name="📋 重置後的變化",
            value=(
                "```diff\n"
                f"- 職業: {current_job} → 無職業\n"
                f"- 工作冷卻時間: 清除\n"
                "```"
            ),
            inline=False
        )
        embed.set_footer(
            text="請在靈魂的猶豫中做出選擇 · 幽幽子",
            icon_url=self.bot.user.display_avatar.url  # [Debug 修復 #3]
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)

        view = ConfirmResetView(self, ctx, guild_id, user_id, current_job)

        try:
            await ctx.respond(embed=embed, view=view, ephemeral=True)
            # [Debug 修復 #4] 使用 Pycord 最穩健的 original_response() 獲取 Message 物件
            view.message = await ctx.interaction.original_response()
            logger.info(f"👤 用戶 {ctx.author.name}({user_id}) 開啟職業重置確認")
        except Exception as e:
            logger.exception(f"❌ 職業重置互動建立失敗: {e}")
            error_embed = discord.Embed(
                title="❌ 術式施展失敗",
                description="哎呀，職業重置互動建立失敗了...\n請稍後再試～",
                color=discord.Color.dark_red()
            )
            error_embed.set_footer(text="術式受阻，請稍後重試 · 幽幽子")
            # 防止重複回應報錯
            if not ctx.response.is_done():
                await ctx.respond(embed=error_embed, ephemeral=True)


class ConfirmResetView(discord.ui.View):
    """🌸 幽幽子的職業重置確認之門 🌸"""

    def __init__(
        self,
        parent_cog: ResetJob,
        ctx: discord.ApplicationContext,
        guild_id: str,
        user_id: str,
        current_job: str
    ):
        super().__init__(timeout=60)
        self.parent_cog = parent_cog
        self.ctx = ctx
        self.guild_id = guild_id
        self.user_id = user_id
        self.current_job = current_job
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "呀啦呀啦～這不是你的靈魂抉擇，請不要干擾他人的命運哦!",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="是，放下職業", style=discord.ButtonStyle.green, emoji="🌸")
    async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)

            # [Debug 修復 #2] 直接操作記憶體中的 user_config
            user_config = self.parent_cog.data_manager.user_config
            
            if (self.guild_id not in user_config or
                    self.user_id not in user_config[self.guild_id] or
                    not user_config[self.guild_id][self.user_id].get("job")):
                
                no_job_embed = discord.Embed(
                    title="🌸 靈魂本就虛無",
                    description="呼呼～你本來就沒有職業了呢!\n可能在你猶豫的時候，職業已經隨風而逝了～",
                    color=discord.Color.gold()
                )
                no_job_embed.set_footer(text="虛無本身也是一種美好 · 幽幽子")
                await interaction.followup.send(embed=no_job_embed, ephemeral=True)
                return

            # 修改記憶體
            user_config[self.guild_id][self.user_id]["job"] = None
            user_config[self.guild_id][self.user_id]["work_cooldown"] = None

            # [Debug 修復 #2] 鎖釋放後，統一呼叫 save_all_async 保存
            await self.parent_cog.data_manager.save_all_async()

            success_embed = discord.Embed(
                title="🌸 職業已隨櫻花飄散",
                description=(
                    f"你的職業 **`{self.current_job}`** 已被清除。\n\n"
                    f"靈魂回歸虛無，如同初生的櫻花般純淨...\n"
                    f"等待著新的緣分降臨～\n\n"
                    f"💡 **想重新選擇職業?**\n"
                    f"請使用 `/choose_job` 命令開始新的旅程!"
                ),
                color=discord.Color.from_rgb(144, 238, 144)
            )
            success_embed.add_field(
                name="✨ 重置結果",
                value=(
                    "```yaml\n"
                    f"舊職業: {self.current_job}\n"
                    f"新狀態: 無職業（虛無）\n"
                    f"工作冷卻: 已清除\n"
                    "```"
                ),
                inline=False
            )
            success_embed.set_footer(
                text="櫻花凋零後，總會再次綻放 · 幽幽子",
                icon_url=self.parent_cog.bot.user.display_avatar.url  # [Debug 修復 #3]
            )
            success_embed.set_thumbnail(url=interaction.user.display_avatar.url)

            for item in self.children:
                item.disabled = True

            # [Debug 修復 #5] 理順 UI 邏輯：直接 edit 原訊息，不發送額外的 followup，保持畫面乾淨
            if self.message:
                try:
                    await self.message.edit(embed=success_embed, view=self)
                except Exception as edit_err:
                    logger.warning(f"⚠️ 無法編輯原訊息: {edit_err}")

            logger.info(f"✅ 用戶 {interaction.user.name}({self.user_id}) 成功重置職業: {self.current_job}")

        except Exception as e:
            logger.exception(f"❌ 職業重置執行失敗: {e}")
            error_embed = discord.Embed(
                title="❌ 術式崩壞",
                description="哎呀，職業重置失敗了...\n請稍後再試～",
                color=discord.Color.dark_red()
            )
            error_embed.set_footer(text="術式受阻，請稍後重試 · 幽幽子")
            await interaction.followup.send(embed=error_embed, ephemeral=True)

    @discord.ui.button(label="否，保留職業", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction):
        cancel_embed = discord.Embed(
            title="🌸 靈魂選擇繼續前行",
            description=(
                f"你選擇保留職業 **`{self.current_job}`**。\n\n"
                f"櫻花依舊綻放，職業依然延續～\n"
                f"繼續在這條道路上前行吧!"
            ),
            color=discord.Color.from_rgb(255, 182, 193)
        )
        cancel_embed.set_footer(
            text="堅守本心，也是一種美好 · 幽幽子",
            icon_url=self.parent_cog.bot.user.display_avatar.url  # [Debug 修復 #3]
        )
        cancel_embed.set_thumbnail(url=interaction.user.display_avatar.url)

        for item in self.children:
            item.disabled = True

        # [Debug 修復 #5] 理順 UI 邏輯：直接 edit_message，不發送額外的 send_message
        if self.message:
            try:
                await interaction.response.edit_message(embed=cancel_embed, view=self)
            except Exception as edit_err:
                logger.warning(f"⚠️ 無法編輯原訊息: {edit_err}")
        
        self.stop()
        logger.info(f"🚫 用戶 {interaction.user.name}({self.user_id}) 取消職業重置")

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

        timeout_embed = discord.Embed(
            title="🌸 櫻花已隨風逝去",
            description=(
                "職業重置操作已超時...\n\n"
                "時光如櫻花般飄落，稍縱即逝。\n"
                "若仍需重置，請重新執行 `/reset_job` 命令～"
            ),
            color=discord.Color.orange()
        )
        timeout_embed.set_footer(
            text="時光流逝如櫻花飄落 · 幽幽子",
            icon_url=self.parent_cog.bot.user.display_avatar.url  # [Debug 修復 #3]
        )

        try:
            if self.message:
                await self.message.edit(embed=timeout_embed, view=self)
            logger.info(f"⏰ 用戶 {self.user_id} 的職業重置操作已超時")
        except Exception as e:
            logger.exception(f"❌ 職業重置超時處理失敗: {e}")


def setup(bot: discord.Bot):
    bot.add_cog(ResetJob(bot))
    logger.info("🌸 職業重置模組已於櫻花樹下綻放完成")
