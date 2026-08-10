import discord
from discord.ext import commands
from discord import ApplicationContext, Interaction
import random
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List

logger = logging.getLogger("SakuraBot.Fish")

# [新增] 三種職業的專屬釣魚情境描述
FISHING_SCENARIOS = {
    "漁夫": (
        "你駕駛著一艘小木船，駛向櫻花湖的深海區。海風呼嘯，波浪拍打著船舷，\n"
        "你熟練地拋下重型漁網與魚竿。這是一場真正的航海垂釣，\n"
        "只有最勇敢的漁夫，才能征服這片海域的巨物！"
    ),
    "釣魚佬": (
        "你來到了櫻花湖最深處、暗流洶湧的『大魚大貨』秘境！\n"
        "這裡的魚兒個個膘肥體壯，但脾氣也暴躁無比。\n"
        "你緊握魚竿，雙眼緊盯浮標，準備與水下的巨物展開一場激烈的拔河！"
    ),
    "普通": (
        "微風拂過櫻花湖畔，你坐在岸邊，悠閒地拋下魚竿。\n"
        "水波蕩漾，櫻花花瓣偶爾落在浮標上，\n"
        "這便是冥界最愜意的午後時光，連時間都慢了下來～"
    )
}

class FishingButtons(discord.ui.View):
    def __init__(self, author_id, latest_fish_data, fish_data, current_rod, data_manager, cog, main_job, sub_job):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.latest_fish_data = latest_fish_data
        self.fish_data = fish_data
        self.current_rod = current_rod
        self.data_manager = data_manager
        self.cog = cog
        self.main_job = main_job
        self.sub_job = sub_job
        self.original_message = None

        # 如果是空軍，移除「保存漁獲」按鈕
        if self.latest_fish_data.get("is_empty_handed"):
            for item in self.children:
                if isinstance(item, discord.ui.Button) and "保存" in item.label:
                    self.remove_item(item)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("這不是你的櫻花釣魚按鈕哦～", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        if self.original_message:
            try: 
                await self.original_message.edit(content="釣魚操作已超時...", view=self)
            except discord.NotFound:
                logger.debug("釣魚訊息已被刪除，超時處理略過")
            except Exception as e:
                logger.warning(f"釣魚超時處理失敗: {e}")

    @discord.ui.button(label="🌸 再釣一次櫻花魚", style=discord.ButtonStyle.green)
    async def repeat_fishing(self, button, interaction):
        # [修復] 獲取 commands_error_logger
        commands_error_logger = logging.getLogger("SakuraBot.CommandsError")
        
        try:
            for item in self.children: item.disabled = True
            button.label = "幽幽子撒櫻花漁網中..."
            await interaction.response.edit_message(view=self)
            await asyncio.sleep(1.5)

            new_fish_data = self.cog.generate_fish_data(self.fish_data, self.main_job, self.sub_job)
            
            if new_fish_data.get("is_empty_handed"):
                new_embed = discord.Embed(
                    title="🎣 櫻花湖的微風... 哎呀，空軍了！",
                    description="呼呼～今天櫻花湖的魚兒們似乎都在睡午覺呢...\n你等了半天，連一片魚鱗都沒釣到！\n\n*釣魚佬的宿命，就是與空軍相伴啊～*",
                    color=discord.Color.light_gray()
                )
            else:
                new_embed = self.cog.create_fishing_embed(new_fish_data, self.current_rod, self.main_job, self.sub_job)

            new_view = FishingButtons(self.author_id, new_fish_data, self.fish_data, self.current_rod, self.data_manager, self.cog, self.main_job, self.sub_job)
            updated_message = await interaction.edit_original_response(content=None, embed=new_embed, view=new_view)
            new_view.original_message = updated_message
            
        except discord.NotFound:
            logger.warning(f"用戶 {self.author_id} 的釣魚訊息已被刪除，無法繼續釣魚")
        except discord.HTTPException as e:
            logger.error(f"重複釣魚時 Discord API 錯誤: {e}")
            try:
                error_embed = discord.Embed(
                    title="❌ 釣魚系統暫時異常",
                    description=(
                        "哎呀～櫻花湖的波動有點不穩定呢...\n"
                        "幽幽子正在努力修復中，請稍後再試一次 `/fish` 吧！\n\n"
                        "*如果問題持續發生，請使用 `/feedback` 回報給 Shiroko*"
                    ),
                    color=discord.Color.red()
                )
                error_embed.set_footer(text="冥界的小故障，請見諒 · 幽幽子")
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            except Exception as e2:
                # [修復] 記錄發送錯誤訊息失敗的錯誤
                commands_error_logger.error(
                    f"repeat_fishing: 發送錯誤訊息失敗 - 原始錯誤: {e}, 發送錯誤: {e2}", 
                    exc_info=True
                )
        except Exception as e:
            logger.error(f"重複釣魚時發生未預期錯誤: {e}", exc_info=True)
            try:
                error_embed = discord.Embed(
                    title="❌ 釣魚系統發生嚴重錯誤",
                    description=(
                        "嗚嗚...幽幽子在撒網時絆倒了...\n"
                        "這是一個未知的系統錯誤，請重新使用 `/fish` 開始新的釣魚。\n\n"
                        "**如果反覆出現此問題，請務必使用 `/feedback` 回報！**\n"
                        "Shiroko 會盡快修復的～"
                    ),
                    color=discord.Color.dark_red()
                )
                error_embed.set_footer(text="請回報錯誤 · 幽幽子")
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            except Exception as e2:
                # [修復] 記錄發送錯誤訊息失敗的錯誤
                commands_error_logger.error(
                    f"repeat_fishing: 發送嚴重錯誤訊息失敗 - 原始錯誤: {e}, 發送錯誤: {e2}", 
                    exc_info=True
                )

    @discord.ui.button(label="💾 保存櫻花漁獲", style=discord.ButtonStyle.blurple)
    async def save_fish(self, button, interaction):
        # [修復] 獲取 commands_error_logger
        commands_error_logger = logging.getLogger("SakuraBot.CommandsError")
        
        if self.data_manager.is_backing_up:
            await interaction.response.send_message("⚠️ 幽幽子正在備份，請稍候～", ephemeral=True)
            return
        
        user_id = str(interaction.user.id)
        guild_id = str(interaction.guild.id) if interaction.guild else "DM"
        
        try:
            button.disabled = True
            button.label = "封存中..."
            await interaction.response.edit_message(view=self)

            fish_record = {
                "name": self.latest_fish_data["name"],
                "rarity": self.latest_fish_data["rarity"],
                "size": self.latest_fish_data["size"],
                "rod": self.current_rod,
                "caught_at": datetime.now(self.cog.TIMEZONE).isoformat()
            }

            fishing_data = self.data_manager.fishingbackpack
            async with self.data_manager.balance_lock:
                fishing_data.setdefault(user_id, {}).setdefault(guild_id, {"fishes": []})["fishes"].append(fish_record)
            
            await self.data_manager.save_all_async()

            button.label = "✅ 已封存"
            button.style = discord.ButtonStyle.success
            await interaction.edit_original_response(view=self)
            
            logger.info(f"✅ 用戶 {user_id} 成功保存漁獲: {fish_record['name']} ({fish_record['rarity']}, {fish_record['size']}kg)")
            
        except discord.NotFound:
            logger.warning(f"用戶 {user_id} 的釣魚訊息已被刪除，無法保存漁獲")
        except discord.HTTPException as e:
            logger.error(f"保存漁獲時 Discord API 錯誤: {e}")
            try:
                button.disabled = False
                button.label = "💾 保存櫻花漁獲"
                button.style = discord.ButtonStyle.blurple
                await interaction.edit_original_response(view=self)
                
                error_embed = discord.Embed(
                    title="❌ 保存漁獲失敗",
                    description=(
                        "哎呀～櫻花湖的記憶有點模糊了...\n"
                        "你的漁獲**沒有被保存**，請重新點擊保存按鈕再試一次。\n\n"
                        "*如果反覆失敗，請使用 `/feedback` 回報*"
                    ),
                    color=discord.Color.red()
                )
                error_embed.set_footer(text="請重試 · 幽幽子")
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            except Exception as e2:
                # [修復] 記錄錯誤
                commands_error_logger.error(
                    f"save_fish: Discord API 錯誤後發送提示失敗 - 原始錯誤: {e}, 發送錯誤: {e2}", 
                    exc_info=True
                )
        except Exception as e:
            logger.error(f"保存漁獲時發生嚴重錯誤: {e}", exc_info=True)
            
            # 嘗試恢復按鈕狀態
            try:
                button.disabled = False
                button.label = "💾 保存櫻花漁獲"
                button.style = discord.ButtonStyle.blurple
                await interaction.edit_original_response(view=self)
            except Exception as e2:
                # [修復] 記錄恢復按鈕失敗的錯誤
                commands_error_logger.error(
                    f"save_fish: 恢復按鈕狀態失敗 - 原始錯誤: {e}, 恢復錯誤: {e2}", 
                    exc_info=True
                )
            
            # 發送錯誤提示給用戶
            try:
                fish_record = {
                    "name": self.latest_fish_data["name"],
                    "rarity": self.latest_fish_data["rarity"],
                    "size": self.latest_fish_data["size"]
                }
                error_embed = discord.Embed(
                    title="❌ 保存漁獲時發生嚴重錯誤",
                    description=(
                        "嗚嗚...幽幽子在封存漁獲時遇到了大麻煩...\n\n"
                        "**你的漁獲可能沒有被保存！**\n\n"
                        "請嘗試以下步驟：\n"
                        "1️⃣ 重新點擊「保存櫻花漁獲」按鈕\n"
                        "2️⃣ 如果還是失敗，請使用 `/fish_back` 檢查背包\n"
                        "3️⃣ 如果魚真的不見了，**請務必使用 `/feedback` 回報！**\n\n"
                        "Shiroko 會盡快幫你找回來的～"
                    ),
                    color=discord.Color.dark_red()
                )
                error_embed.add_field(
                    name="🐟 你嘗試保存的漁獲",
                    value=(
                        f"**{fish_record['name']}**\n"
                        f"稀有度: {fish_record['rarity']}\n"
                        f"重量: {fish_record['size']} kg"
                    ),
                    inline=False
                )
                error_embed.set_footer(text="請回報錯誤 · 幽幽子")
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            except Exception as e2:
                # [修復] 記錄發送錯誤訊息失敗的錯誤
                commands_error_logger.error(
                    f"save_fish: 發送嚴重錯誤訊息失敗 - 原始錯誤: {e}, 發送錯誤: {e2}", 
                    exc_info=True
                )


class Fish(commands.Cog):
    DEFAULT_RARITY_WEIGHTS = {"common": 50.0, "uncommon": 30.0, "rare": 15.0, "legendary": 4.0, "deify": 1.0, "unknown": 0.5}
    TIMEZONE = timezone(timedelta(hours=8))

    def __init__(self, bot):
        self.bot = bot
        self.rarity_weights_cache = None

    def get_fish_data(self) -> Optional[List[dict]]:
        try:
            config_path = f"{self.bot.data_manager.config_dir}/config.json"
            config_data = self.bot.data_manager._load_json(config_path, {})
            return config_data.get("fish")
        except Exception as e:
            logger.error(f"讀取魚資料失敗: {e}")
            return None

    def calculate_rarity_weights(self, fish_data: list) -> dict:
        if self.rarity_weights_cache:
            return self.rarity_weights_cache
        actual_rarities = set(fish.get("rarity", "common").lower() for fish in fish_data)
        final_weights = {r: self.DEFAULT_RARITY_WEIGHTS.get(r, 0.5) for r in actual_rarities}
        self.rarity_weights_cache = final_weights
        return final_weights

    def generate_fish_data(self, fish_data: list, main_job: str = "無職業", sub_job: str = "無副職") -> dict:
        if not fish_data:
            return {"name": "神秘櫻花魚", "rarity": "common", "size": 0.5}

        if sub_job == "釣魚佬" and random.random() < 0.30:
            return {"name": "空軍", "rarity": "none", "size": 0, "is_empty_handed": True}

        rarity_weights = self.calculate_rarity_weights(fish_data).copy()

        if main_job == "漁夫":
            rarity_weights["legendary"] = rarity_weights.get("legendary", 4.0) * 3.0
            rarity_weights["deify"] = rarity_weights.get("deify", 1.0) * 5.0
            rarity_weights["unknown"] = rarity_weights.get("unknown", 0.5) * 4.0

        rarity_pools = {}
        for fish in fish_data:
            rarity_pools.setdefault(fish.get("rarity", "common").lower(), []).append(fish)

        rarities = list(rarity_weights.keys())
        weights = [rarity_weights[r] for r in rarities]
        selected_rarity = random.choices(rarities, weights=weights, k=1)[0]
        selected_fish = random.choice(rarity_pools[selected_rarity])

        try:
            min_s = float(selected_fish.get("min_size", 0.1))
            max_s = float(selected_fish.get("max_size", 1.0))
            if min_s > max_s:
                min_s, max_s = max_s, min_s
            fish_size = round(random.uniform(min_s, max_s), 2)
        except Exception:
            fish_size = 0.5

        return {
            "name": selected_fish.get("name", "未知"),
            "rarity": selected_fish.get("rarity", "common").lower(),
            "size": fish_size,
            "is_empty_handed": False
        }

    def create_fishing_embed(self, fish_data: dict, current_rod: str, main_job: str, sub_job: str) -> discord.Embed:
        rarity_info = {
            "common": {"color": discord.Color.green(), "emoji": "🟢", "desc": "常見的櫻花湖住民"},
            "uncommon": {"color": discord.Color.blue(), "emoji": "🔵", "desc": "不太常見的美麗魚種"},
            "rare": {"color": discord.Color.purple(), "emoji": "🟣", "desc": "稀有的櫻花湖珍寶"},
            "legendary": {"color": discord.Color.orange(), "emoji": "🟠", "desc": "傳說中的夢幻魚種"},
            "deify": {"color": discord.Color.gold(), "emoji": "⭐", "desc": "神格化的冥界聖魚"},
            "unknown": {"color": discord.Color.dark_gray(), "emoji": "❓", "desc": "神秘的未知魚種"},
        }
        rarity = fish_data.get("rarity", "common").lower()
        info = rarity_info.get(rarity, {"color": discord.Color.light_gray(), "emoji": "⚪", "desc": "神秘魚種"})

        if main_job == "漁夫":
            scenario = FISHING_SCENARIOS["漁夫"]
        elif sub_job == "釣魚佬":
            scenario = FISHING_SCENARIOS["釣魚佬"]
        else:
            scenario = FISHING_SCENARIOS["普通"]

        job_bonus = ""
        if main_job == "漁夫" and rarity in ["legendary", "deify", "unknown"]:
            job_bonus = "\n*✨ 漁夫的直覺：深海的珍寶被你發現了！*"
        elif sub_job == "釣魚佬" and rarity in ["rare", "legendary", "deify"]:
            job_bonus = "\n*✨ 釣魚佬的執念：大魚大貨果然名不虛傳！*"

        embed = discord.Embed(
            title="🌸 幽幽子的櫻花湖釣魚結果！",
            description=f"使用的魚竿：**{current_rod}**\n\n{scenario}{job_bonus}",
            color=info["color"],
            timestamp=datetime.now(self.TIMEZONE)
        )
        
        passive_text = ""
        if main_job == "漁夫":
            passive_text = "✨ **被動：漁民的直覺**｜提高傳說、神級及未知漁獲的上鉤機率"
        elif sub_job == "釣魚佬":
            passive_text = "✨ **被動：釣魚佬的直覺**｜每次拋出魚竿時 30% 有概率空軍"
            
        if passive_text:
            embed.add_field(name="🎣 職業被動觸發", value=passive_text, inline=False)

        embed.add_field(name="🐟 捕獲櫻花魚種", value=f"**{fish_data['name']}**\n{info['desc']}", inline=False)
        embed.add_field(name=f"{info['emoji']} 稀有度", value=f"**{rarity.capitalize()}**", inline=True)
        embed.add_field(name="⚖️ 重量", value=f"**{fish_data['size']}** 公斤", inline=True)

        size = fish_data['size']
        if size >= 10:
            comment = "天啊！這是巨物級別的漁獲！"
        elif size >= 5:
            comment = "好大的一條魚～幽幽子都驚訝了！"
        elif size >= 2:
            comment = "不錯的收穫呢！"
        else:
            comment = "小小的也很可愛～"

        embed.set_footer(text=f"{comment} | 幽幽子祝你天天大豐收！")
        return embed

    @discord.slash_command(name="fish", description="🌸 幽幽子邀你到櫻花湖畔釣魚～")
    async def fish(self, ctx: ApplicationContext):
        # [修復] 獲取 commands_error_logger
        commands_error_logger = logging.getLogger("SakuraBot.CommandsError")
        
        if not await self.data_manager.check_economy_enabled(ctx, "fish"):
            return
        
        try:
            fish_data = await asyncio.to_thread(self.get_fish_data)
            if not fish_data:
                await ctx.respond(
                    embed=discord.Embed(
                        title="❌ 無法讀取魚資料",
                        description=(
                            "幽幽子迷糊了，無法讀取櫻花湖的魚資料...\n"
                            "請檢查 `config/config.json` 是否正確配置。\n\n"
                            "*如果問題持續，請使用 `/feedback` 回報*"
                        ),
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
                return

            guild_id = str(ctx.guild.id) if ctx.guild else "DM"
            user_id = str(ctx.user.id)
            user_info = self.bot.data_manager.user_config.get(guild_id, {}).get(user_id, {})
            
            main_job = user_info.get("job", "無職業")
            sub_job = user_info.get("sub_job", "無副職")

            await ctx.defer()
            await asyncio.sleep(1)

            latest_fish_data = self.generate_fish_data(fish_data, main_job, sub_job)
            
            if latest_fish_data.get("is_empty_handed"):
                embed = discord.Embed(
                    title="🎣 櫻花湖的微風... 哎呀，空軍了！",
                    description=FISHING_SCENARIOS["釣魚佬"] + "\n\n呼呼～等了半天，連一片魚鱗都沒釣到！\n*釣魚佬的宿命，就是與空軍相伴啊～*",
                    color=discord.Color.light_gray(),
                    timestamp=datetime.now(self.TIMEZONE)
                )
            else:
                embed = self.create_fishing_embed(latest_fish_data, "櫻花魚竿", main_job, sub_job)

            view = FishingButtons(ctx.user.id, latest_fish_data, fish_data, "櫻花魚竿", self.bot.data_manager, self, main_job, sub_job)
            message = await ctx.followup.send(embed=embed, view=view)
            view.original_message = message
            
        except Exception as e:
            logger.error(f"🎣 /fish 指令發生嚴重錯誤: {e}", exc_info=True)
            try:
                error_embed = discord.Embed(
                    title="❌ 釣魚系統發生錯誤",
                    description=(
                        "嗚嗚...幽幽子在準備釣魚時摔了一跤...\n"
                        "這是一個未知的系統錯誤，請稍後再試一次 `/fish`。\n\n"
                        "**如果反覆出現此問題，請務必使用 `/feedback` 回報！**"
                    ),
                    color=discord.Color.dark_red()
                ).set_footer(text="請回報錯誤 · 幽幽子")
                
                if not ctx.response.is_done():
                    await ctx.respond(embed=error_embed, ephemeral=True)
                else:
                    await ctx.followup.send(embed=error_embed, ephemeral=True)
            except Exception as e2:
                # [修復] 記錄發送錯誤訊息失敗的錯誤
                commands_error_logger.error(
                    f"fish: 發送錯誤訊息失敗 - 原始錯誤: {e}, 發送錯誤: {e2}", 
                    exc_info=True
                )


def setup(bot):
    bot.add_cog(Fish(bot))
    logger.info("Fish Cog 已載入，櫻花湖等待著釣魚者～")
