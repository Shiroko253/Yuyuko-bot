import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, InputText
import asyncio
import math
import logging
import os
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

logger = logging.getLogger("SakuraBot.Shop")

SHOP_COLOR     = discord.Color.from_rgb(255, 182, 193)
ITEMS_PER_PAGE = 5

def calc_total_price(price: float, tax_percent: float) -> float:
    return round(price + price * (tax_percent / 100), 2)


class Shop(commands.Cog):
    """🌸 幽幽子的貪吃冥界商店 🌸"""

    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.data_manager = bot.data_manager
        logger.info("🌸 商店指令已於櫻花樹下甦醒")

    @discord.slash_command(
        name="shop",
        description="🌸 幽幽子的貪吃冥界商店～購買美味供品讓靈魂愉悅"
    )
    async def shop(self, ctx: discord.ApplicationContext):
        # [Debug 修復 #1] 加入在線備份攔截
        if not await self.data_manager.check_backup_status(ctx, "shop"):
            return
        
        if not await self.data_manager.check_economy_enabled(ctx, "shop"):
            return

        try:
            # [Debug 修復 #2] 使用 to_thread 包裝同步 I/O，避免阻塞 Event Loop
            config_path = os.path.join(self.data_manager.config_dir, "config.json")
            config = await asyncio.to_thread(
                self.data_manager._load_json, config_path, {}
            )
            shop_items = config.get("shop_item", [])

            if not shop_items:
                embed = discord.Embed(
                    title="🌸 商店空空如也",
                    description="哎呀～商店裡沒有供品了!\n幽幽子都快餓扁了…請管理員補貨!",
                    color=discord.Color.red()
                )
                embed.set_footer(text="商店暫時關閉 · 幽幽子")
                await ctx.respond(embed=embed, ephemeral=True)
                return

            total_pages = max(1, math.ceil(len(shop_items) / ITEMS_PER_PAGE))
            view = ShopPagesView(ctx, shop_items, total_pages, self.data_manager, self)
            embed = view.get_embed()

            await ctx.respond(embed=embed, view=view)
            
            # [Debug 修復 #3] 使用 Pycord 最穩健的 original_response() 獲取 Message
            view.message = await ctx.interaction.original_response()
            logger.info(f"🛒 {ctx.user.name} 打開了商店")

        except Exception as e:
            logger.error(f"❌ 商店開啟失敗: {e}", exc_info=True)
            await ctx.respond(
                embed=discord.Embed(
                    title="❌ 商店開啟失敗",
                    description="哎呀，幽幽子的商店好像關門了...\n請聯絡管理員檢查設定檔!",
                    color=discord.Color.dark_red()
                ),
                ephemeral=True
            )


class ShopPagesView(View):
    def __init__(self, ctx, shop_items, total_pages, data_manager, cog):
        super().__init__(timeout=120)
        self.ctx, self.shop_items, self.total_pages = ctx, shop_items, total_pages
        self.current_page, self.data_manager, self.cog = 1, data_manager, cog
        self.message = None
        self.update_buttons()

    def get_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🍡 幽幽子的貪吃冥界商店 🍡",
            description="呼呼～冥界主人幽幽子為你呈上今日美味供品!\n快來選購讓靈魂愉悅的美食吧～",
            color=SHOP_COLOR, timestamp=discord.utils.utcnow()
        )
        start = (self.current_page - 1) * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE

        for i, item in enumerate(self.shop_items[start:end], start=start + 1):
            price, tax = item.get("price", 0), item.get("tax", 0)
            total = calc_total_price(price, tax)
            # [Debug 修復 #4] 向下相容：優先讀取 Stamina，若無則讀取舊的 MP
            stamina = item.get("Stamina", item.get("MP", 0))
            
            embed.add_field(
                name=f"🍽️ 編號 {i} - {item.get('name', '未命名供品')}",
                value=f"```yaml\n單價: {price:,}\n稅收: {tax}%\n合計: {total:,}\n效果: 恢復體力 {stamina} 點\n```",
                inline=False
            )

        embed.set_footer(
            text=f"第 {self.current_page} / {self.total_pages} 頁 ｜ 吃飽飽才有力氣賞花呢～",
            icon_url=self.cog.bot.user.display_avatar.url  # [Debug 修復 #5]
        )
        return embed

    def update_buttons(self):
        self.clear_items()
        if self.current_page > 1:
            prev_btn = Button(label="上一頁", style=discord.ButtonStyle.secondary, emoji="⬅️", row=0)
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
        if self.current_page < self.total_pages:
            next_btn = Button(label="下一頁", style=discord.ButtonStyle.secondary, emoji="➡️", row=0)
            next_btn.callback = self.next_page
            self.add_item(next_btn)
        
        buy_btn = Button(label="選購", style=discord.ButtonStyle.success, emoji="🛒", row=1)
        buy_btn.callback = self.start_buy
        self.add_item(buy_btn)
        
        close_btn = Button(label="關閉商店", style=discord.ButtonStyle.danger, emoji="❌", row=1)
        close_btn.callback = self.close_shop
        self.add_item(close_btn)

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        if self.message:
            try: await self.message.edit(view=self)
            except: pass

    async def _check_owner(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("這不是你的商店頁面哦!", ephemeral=True)
            return False
        return True

    async def prev_page(self, interaction):
        if not await self._check_owner(interaction): return
        if self.current_page > 1:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def next_page(self, interaction):
        if not await self._check_owner(interaction): return
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def start_buy(self, interaction):
        if not await self._check_owner(interaction): return
        await interaction.response.send_modal(BuyModal(self.ctx, self.shop_items, self.data_manager, self.cog))

    async def close_shop(self, interaction):
        if not await self._check_owner(interaction): return
        for item in self.children: item.disabled = True
        embed = discord.Embed(title="🌸 商店已關閉", description="感謝光臨!\n櫻花樹下歡迎你隨時再來～", color=SHOP_COLOR)
        embed.set_footer(text="期待下次見面 · 幽幽子", icon_url=self.cog.bot.user.display_avatar.url)
        await interaction.response.edit_message(embed=embed, view=self)


class BuyModal(Modal):
    def __init__(self, ctx, shop_items, data_manager, cog):
        super().__init__(title="🌸 幽幽子的商店購物車")
        self.ctx, self.shop_items, self.data_manager, self.cog = ctx, shop_items, data_manager, cog
        self.add_item(InputText(label="商品編號", placeholder="輸入編號 (例如: 1)", required=True, min_length=1, max_length=5))
        self.add_item(InputText(label="購買數量", placeholder="輸入數量 (例如: 1)", required=True, min_length=1, max_length=5))

    async def callback(self, interaction):
        try:
            try:
                item_number = int(self.children[0].value.strip())
                quantity = int(self.children[1].value.strip())
                if quantity <= 0: raise ValueError
            except ValueError:
                await interaction.response.send_message(embed=discord.Embed(title="❌ 格式錯誤", description="請輸入有效的數字!", color=discord.Color.red()), ephemeral=True)
                return

            item_index = item_number - 1
            if item_index < 0 or item_index >= len(self.shop_items):
                await interaction.response.send_message(embed=discord.Embed(title="🌸 商品不存在", description=f"編號 `{item_number}` 沒有對應的供品哦!", color=discord.Color.orange()), ephemeral=True)
                return

            item = self.shop_items[item_index]
            unit_price, tax = item.get("price", 0), item.get("tax", 0)
            unit_total = calc_total_price(unit_price, tax)
            total_price = round(unit_total * quantity, 2)

            guild_id, user_id = str(self.ctx.guild.id), str(self.ctx.author.id)

            # 鎖內純記憶體讀取
            async with self.data_manager.balance_lock:
                balance = self.data_manager.balance
                balance.setdefault(guild_id, {}).setdefault(user_id, 0.0)
                user_balance = balance[guild_id][user_id]

            if user_balance < total_price:
                await interaction.response.send_message(
                    embed=discord.Embed(title="🌸 餘額不足", description=f"購買需要 **{total_price:,}**，但你只有 **{user_balance:,}** 呢...", color=discord.Color.red()),
                    ephemeral=True
                )
                return

            await interaction.response.defer()

            # [Debug 修復 #4] 向下相容 Stamina
            stamina = item.get("Stamina", item.get("MP", 0))
            confirm_embed = discord.Embed(
                title="🍽️ 確認購買",
                description=f"**商品**: {item.get('name')}\n**數量**: `{quantity}`\n**總價**: `{total_price:,}` 幽靈幣\n**效果**: 恢復體力 `{stamina * quantity}` 點\n\n確定要買下它們嗎?",
                color=SHOP_COLOR, timestamp=discord.utils.utcnow()
            )
            confirm_embed.add_field(name="💰 餘額變化", value=f"```yaml\n目前: {user_balance:,}\n購買後: {user_balance - total_price:,}\n```", inline=False)

            # 傳遞 guild_id 和 user_id 給 ConfirmBuyView，以便後續寫入背包
            view = ConfirmBuyView(self.ctx, item, quantity, total_price, self.data_manager, self.cog, guild_id, user_id)
            await interaction.followup.send(embed=confirm_embed, view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"❌ 購買流程失敗: {e}", exc_info=True)
            try: await interaction.response.send_message("❌ 購買流程發生錯誤!", ephemeral=True)
            except: await interaction.followup.send("❌ 購買流程發生錯誤!", ephemeral=True)


class ConfirmBuyView(View):
    def __init__(self, ctx, item, quantity, total_price, data_manager, cog, guild_id, user_id):
        super().__init__(timeout=60)
        self.ctx, self.item, self.quantity, self.total_price = ctx, item, quantity, total_price
        self.data_manager, self.cog, self.guild_id, self.user_id = data_manager, cog, guild_id, user_id

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        self.stop()

    @discord.ui.button(label="確認購買", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm(self, button, interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("這不是你的購買確認哦!", ephemeral=True)
            return

        # [Debug 修復 #1] 加入在線備份攔截
        if not await self.cog.data_manager.check_backup_status(interaction, "shop_confirm"):
            return

        await interaction.response.defer()

        # 鎖內純記憶體操作
        async with self.data_manager.balance_lock:
            balance = self.data_manager.balance
            balance.setdefault(self.guild_id, {}).setdefault(self.user_id, 0.0)
            user_balance = balance[self.guild_id][self.user_id]

            if user_balance < self.total_price:
                await interaction.followup.send("❌ 餘額不足，購買失敗!", ephemeral=True)
                return

            balance[self.guild_id][self.user_id] -= self.total_price
            new_balance = balance[self.guild_id][self.user_id]

        # 鎖外保存
        await self.data_manager.save_all_async()

        # 非同步記錄交易
        await self._record_transaction()

        success_embed = discord.Embed(
            title="🎉 購買成功!",
            description=f"你成功購買了 **{self.quantity}** 個 **{self.item.get('name')}**!\n要放入背包還是直接食用呢?",
            color=discord.Color.from_rgb(144, 238, 144)
        )
        success_embed.add_field(name="💰 交易詳情", value=f"```yaml\n花費: {self.total_price:,}\n剩餘: {new_balance:,}\n```", inline=False)

        # 傳遞 guild_id 和 user_id 給 UseOrBackpackView
        view = UseOrBackpackView(self.item, self.quantity, self.cog, self.guild_id, self.user_id)
        await interaction.followup.send(embed=success_embed, view=view, ephemeral=True)

        for item in self.children: item.disabled = True
        logger.info(f"💰 {interaction.user.name} 購買了 {self.quantity} 個 {self.item.get('name')}")

    async def _record_transaction(self):
        """非同步記錄交易"""
        path = os.path.join(self.data_manager.economy_dir, "transactions.json")
        try:
            transactions = await asyncio.to_thread(self.data_manager._load_json, path, {})
            transactions.setdefault(self.guild_id, []).append({
                "user_id": self.user_id, "amount": -self.total_price,
                "type": "shop_purchase", "item": self.item.get("name"),
                "quantity": self.quantity, "timestamp": datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
            })
            await asyncio.to_thread(self.data_manager._save_json, path, transactions)
        except Exception as e:
            logger.error(f"❌ 交易記錄失敗: {e}")

    @discord.ui.button(label="取消", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel(self, button, interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("這不是你的購買確認哦!", ephemeral=True)
            return
        embed = discord.Embed(title="🌸 取消購買", description="好吧，供品留給下次吧!", color=SHOP_COLOR)
        embed.set_footer(text="歡迎隨時再來 · 幽幽子")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        for item in self.children: item.disabled = True
        self.stop()


class UseOrBackpackView(View):
    def __init__(self, item, quantity, cog, guild_id, user_id):
        super().__init__(timeout=60)
        self.item, self.quantity, self.cog = item, quantity, cog
        self.guild_id, self.user_id = guild_id, user_id  # [Debug 修復 #6] 接收並保存 ID

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        self.stop()

    @discord.ui.button(label="直接食用", style=discord.ButtonStyle.primary, emoji="🍡")
    async def eat(self, button, interaction):
        # [Debug 修復 #4] 向下相容 Stamina
        stamina = self.item.get("Stamina", self.item.get("MP", 0)) * self.quantity
        embed = discord.Embed(
            title="🍡 享用美味!",
            description=f"你食用了 **{self.quantity}** 個 **{self.item.get('name')}**，\n恢復了 **{stamina}** 點體力!\n\n櫻花樹下的美食，果然是最棒的～",
            color=discord.Color.from_rgb(144, 238, 144)
        )
        embed.set_footer(text="美味無比 · 幽幽子")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        for item in self.children: item.disabled = True
        self.stop()

    @discord.ui.button(label="放入背包", style=discord.ButtonStyle.secondary, emoji="🎒")
    async def backpack(self, button, interaction):
        # [Debug 修復 #6] 實作真正的背包寫入邏輯！
        await interaction.response.defer(ephemeral=True)
        
        try:
            user_config = self.cog.data_manager.user_config
            
            # 確保數據結構存在
            user_config.setdefault(self.guild_id, {}).setdefault(self.user_id, {"stamina": 20, "max_stamina": 20, "backpack": []})
            
            # 將物品加入背包 (只記錄 name，與 backpack.py 的讀取邏輯一致)
            item_record = {"name": self.item.get("name", "未知物品")}
            user_config[self.guild_id][self.user_id]["backpack"].append(item_record)
            
            # 統一保存
            await self.cog.data_manager.save_all_async()

            embed = discord.Embed(
                title="🎒 存入背包!",
                description=f"供品已放入背包，等下再慢慢享用吧～\n記得不要放太久哦，不然會壞掉的!",
                color=SHOP_COLOR
            )
            embed.set_footer(text="妥善保管 · 幽幽子")
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            for item in self.children: item.disabled = True
            self.stop()
            logger.info(f"🎒 {interaction.user.name} 將 {self.quantity} 個 {self.item.get('name')} 放入背包")
            
        except Exception as e:
            logger.error(f"❌ 放入背包失敗: {e}", exc_info=True)
            await interaction.followup.send("❌ 放入背包時發生錯誤!", ephemeral=True)


def setup(bot: discord.Bot):
    bot.add_cog(Shop(bot))
    logger.info("🌸 商店模組已於櫻花樹下綻放完成")
