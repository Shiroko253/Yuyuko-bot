import discord
from discord.ext import commands
from discord.ui import View, Select, Button
import logging
import asyncio
import os

logger = logging.getLogger("SakuraBot.commands.backpack")
# [Debug 修復] 引入專門的 Commands 錯誤日誌記錄器
commands_error_logger = logging.getLogger("SakuraBot.CommandsError")


class BackpackView(View):
    """第一層 View：背包物品選擇器"""

    def __init__(self, select_item, timeout=300):
        super().__init__(timeout=timeout)
        self.add_item(select_item)
        self.message = None

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content="⏰ 背包已超時關閉，請重新使用 `/backpack`。",
                    view=self
                )
            except discord.NotFound:
                # 訊息被用戶刪除是正常的，直接忽略
                pass
            except Exception as e:
                # [Debug 修復] 記錄其他導致超時編輯失敗的嚴重錯誤
                commands_error_logger.error(f"BackpackView on_timeout 編輯訊息失敗: {e}", exc_info=True)


class ActionView(View):
    """第二層 View：物品操作按鈕 (享用/捐贈/取消)"""

    def __init__(self, timeout=180):
        super().__init__(timeout=timeout)
        self.message = None

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content="⏰ 操作已超時，請重新使用 `/backpack`。",
                    view=self
                )
            except discord.NotFound:
                # 訊息被用戶刪除是正常的，直接忽略
                pass
            except Exception as e:
                # [Debug 修復] 記錄其他導致超時編輯失敗的嚴重錯誤
                commands_error_logger.error(f"ActionView on_timeout 編輯訊息失敗: {e}", exc_info=True)


class Backpack(commands.Cog):
    """
    ✿ 幽幽子的背包小空間 ✿
    來看看你收集了哪些可愛小東西吧～幽幽子會一直陪著你♪
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @discord.slash_command(
        name="backpack",
        description="幽幽子帶你看看背包裡的小寶貝哦～"
    )
    async def backpack(self, ctx: discord.ApplicationContext):
        """查看背包並管理物品"""
        if not await self.data_manager.check_economy_enabled(ctx, "backpack"):
            return
        
        if not ctx.guild:
            await ctx.respond("❌ 背包功能只能在伺服器裡使用哦～", ephemeral=True)
            return

        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)

        if not hasattr(self.bot, "data_manager"):
            await ctx.respond("❌ 幽幽子的背包系統暫時找不到了...", ephemeral=True)
            logger.error("data_manager 不存在")
            return

        data_manager = self.bot.data_manager

        try:
            user_config = data_manager.user_config
            
            config_path = os.path.join(data_manager.config_dir, "config.json")
            config_data = await asyncio.to_thread(data_manager._load_json, config_path, {})
            shop_data = config_data.get("shop_item", [])
            
        except Exception as e:
            logger.error(f"載入背包數據失敗: {e}")
            await ctx.respond("❌ 背包數據載入失敗...", ephemeral=True)
            return

        # 初始化用戶資料結構 (直接操作記憶體)
        if guild_id not in user_config:
            user_config[guild_id] = {}
        if user_id not in user_config[guild_id]:
            # [修改] 預設體力值為 20/20
            user_config[guild_id][user_id] = {"stamina": 20, "max_stamina": 20, "backpack": []}

        user_data = user_config[guild_id][user_id]
        
        # [相容性處理] 確保舊用戶資料也有體力值欄位
        if "stamina" not in user_data:
            user_data["stamina"] = 20
        if "max_stamina" not in user_data:
            user_data["max_stamina"] = 20

        backpack_items = user_data.get("backpack", [])
        current_stamina = user_data.get("stamina", 20)
        max_stamina = user_data.get("max_stamina", 20)

        if not backpack_items:
            embed = discord.Embed(
                title="🎒 空空的背包",
                description="哎呀～你的背包空空的，像櫻花瓣一樣輕呢！🌸\n\n快去 `/shop` 買些東西吧～",
                color=discord.Color.from_rgb(255, 182, 193)
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return

        # 統計物品數量
        item_counts = {}
        for item in backpack_items:
            item_name = item.get("name", "未知物品")
            item_counts[item_name] = item_counts.get(item_name, 0) + 1

        options = [
            discord.SelectOption(
                label=item_name,
                description=f"數量: {count}",
                value=item_name,
                emoji="🎁"
            )
            for item_name, count in sorted(item_counts.items())
        ][:25]

        class BackpackSelect(Select):
            """幽幽子的背包選擇器"""

            def __init__(self_inner):
                super().__init__(
                    placeholder="選一件小東西吧～",
                    options=options,
                    min_values=1,
                    max_values=1
                )

            async def callback(self_inner, interaction: discord.Interaction):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("嘻嘻，這可不是你的小背包哦～", ephemeral=True)
                    return

                selected_item_name = self_inner.values[0]
                item_data = next((item for item in shop_data if item.get("name") == selected_item_name), None)

                if not item_data:
                    await interaction.response.send_message("哎呀～幽幽子找不到這個東西的秘密呢...", ephemeral=True)
                    return

                # [修改] 優先讀取 Stamina，若無則向下相容讀取舊的 MP 欄位
                stamina_value = item_data.get("Stamina", item_data.get("MP", 0))
                item_count = item_counts.get(selected_item_name, 0)

                embed = discord.Embed(
                    title=f"🎒 {selected_item_name}",
                    description=(
                        f"**效果:** 恢復 {stamina_value} 點體力\n"
                        f"**擁有數量:** {item_count}\n"
                        f"**當前體力:** {current_stamina}/{max_stamina}\n\n"
                        "你想怎麼處理它呢？"
                    ),
                    color=discord.Color.from_rgb(255, 105, 180)
                )
                embed.set_footer(text="幽幽子陪你一起做決定～")

                use_button = Button(label="享用它～", style=discord.ButtonStyle.success, emoji="✨")
                donate_button = Button(label="送給幽幽子", style=discord.ButtonStyle.secondary, emoji="💝")
                cancel_button = Button(label="算了", style=discord.ButtonStyle.danger, emoji="❌")

                async def use_callback(use_inter: discord.Interaction):
                    if use_inter.user.id != ctx.author.id:
                        await use_inter.response.send_message("這可不是你的選擇啦～", ephemeral=True)
                        return
                    
                    if not await self.bot.data_manager.check_backup_status(use_inter, "backpack 使用"):
                        return

                    # 從背包移除物品
                    for i, item in enumerate(user_data["backpack"]):
                        if item.get("name") == selected_item_name:
                            user_data["backpack"].pop(i)
                            break

                    # [修改] 計算體力恢復，並限制不超過最大體力上限
                    old_stamina = user_data.get("stamina", 20)
                    max_stamina = user_data.get("max_stamina", 20)
                    
                    # 恢復體力，但不超過上限
                    new_stamina = min(max_stamina, old_stamina + stamina_value)
                    user_data["stamina"] = new_stamina
                    actual_recovered = new_stamina - old_stamina

                    await data_manager.save_all_async()

                    result_embed = discord.Embed(
                        title="✨ 享用成功",
                        description=(
                            f"你享用了 **{selected_item_name}**，體力恢復了！\n\n"
                            f"**體力變化:** {old_stamina}/{max_stamina} → {new_stamina}/{max_stamina} (+{actual_recovered})\n"
                            f"真是輕鬆呢～🌸"
                        ),
                        color=discord.Color.green()
                    )
                    await use_inter.response.edit_message(embed=result_embed, view=None)
                    logger.info(f"{ctx.author} 使用了 {selected_item_name}, 體力: {old_stamina}/{max_stamina} -> {new_stamina}/{max_stamina}")

                async def donate_callback(donate_inter: discord.Interaction):
                    if donate_inter.user.id != ctx.author.id:
                        await donate_inter.response.send_message("這可不是你的禮物哦～", ephemeral=True)
                        return
                    
                    if not await self.bot.data_manager.check_backup_status(donate_inter, "backpack 捐贈"):
                        return

                    blacklist = ["香烟", "台灣啤酒", "煙", "酒"]
                    if selected_item_name in blacklist:
                        reject_embed = discord.Embed(
                            title="❌ 幽幽子婉拒了",
                            description=f"哎呀～幽幽子才不要這種 **{selected_item_name}** 呢，拿回去吧！",
                            color=discord.Color.red()
                        )
                        await donate_inter.response.edit_message(embed=reject_embed, view=None)
                        return

                    # 從背包移除物品
                    for i, item in enumerate(user_data["backpack"]):
                        if item.get("name") == selected_item_name:
                            user_data["backpack"].pop(i)
                            break

                    await data_manager.save_all_async()

                    success_embed = discord.Embed(
                        title="💝 感謝你的禮物",
                        description=f"你把 **{selected_item_name}** 送給了幽幽子！\n\n她開心地說：「謝謝你哦～❤」",
                        color=discord.Color.from_rgb(255, 105, 180)
                    )
                    await donate_inter.response.edit_message(embed=success_embed, view=None)
                    logger.info(f"{ctx.author} 捐贈了 {selected_item_name} 給幽幽子")

                async def cancel_callback(cancel_inter: discord.Interaction):
                    if cancel_inter.user.id != ctx.author.id:
                        return
                    await cancel_inter.response.edit_message(content="好吧～這次就先留著它吧～", embed=None, view=None)

                use_button.callback = use_callback
                donate_button.callback = donate_callback
                cancel_button.callback = cancel_callback

                action_view = ActionView(timeout=180)
                action_view.add_item(use_button)
                action_view.add_item(donate_button)
                action_view.add_item(cancel_button)

                await interaction.response.edit_message(embed=embed, view=action_view)
                action_view.message = interaction.message

        embed = discord.Embed(
            title="🎒 幽幽子的背包小天地",
            description=(
                f"來看看你收集了哪些可愛的小東西吧～🌸\n\n"
                f"**物品種類:** {len(item_counts)}\n"
                f"**物品總數:** {len(backpack_items)}\n"
                f"**當前體力:** {current_stamina}/{max_stamina}\n" # [修改] 顯示 20/20 格式
            ),
            color=discord.Color.from_rgb(255, 105, 180)
        )
        embed.set_footer(text="幽幽子會一直陪著你的哦～")
        embed.set_thumbnail(url=ctx.author.display_avatar.url)

        view = BackpackView(BackpackSelect())
        response = await ctx.respond(embed=embed, view=view, ephemeral=False)
        view.message = await response.original_response()


def setup(bot: discord.Bot):
    """將幽幽子的背包功能裝進 bot 裡"""
    bot.add_cog(Backpack(bot))
    # [修復] 將生硬的日誌改為符合幽幽子風格的冥界語氣
    logger.info("🎒 幽幽子的背包小空間已於櫻花樹下展開")
