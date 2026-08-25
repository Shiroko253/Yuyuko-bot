import discord
from discord.ext import commands
import asyncio
import logging

logger = logging.getLogger("SakuraBot.Tax")


def format_number(num: float) -> str:
    if num >= 1e20: return f"{num / 1e20:.2f} 兆京"
    elif num >= 1e16: return f"{num / 1e16:.2f} 京"
    elif num >= 1e12: return f"{num / 1e12:.2f} 兆"
    elif num >= 1e8: return f"{num / 1e8:.2f} 億"
    else: return f"{num:.2f}"


def get_tax_rate(balance: float) -> float:
    """累進稅率"""
    if balance < 1000: return 0.05
    elif balance < 10000: return 0.10
    elif balance < 100000: return 0.20
    elif balance < 1000000: return 0.30
    else: return 0.40


class Tax(commands.Cog):
    """
    🌸 幽幽子的稅金徵收術式 🌸
    依照靈魂的財富多寡徵收稅金，讓國庫充盈，櫻花綻放～
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.data_manager = bot.data_manager
        logger.info("🌸 稅金徵收術式已於冥界花園中甦醒")

    @discord.slash_command(
        name="tax",
        description="🌸 對伺服器用戶動態徵稅，存入國庫（僅管理員）"
    )
    async def tax(self, ctx: discord.ApplicationContext):
        try:
            # [Debug 修復 #1] 加入在線備份攔截
            if not await self.data_manager.check_backup_status(ctx, "tax"):
                return
                        
            if not await self.data_manager.check_economy_enabled(ctx, "tax"):
                return

            guild_id = str(ctx.guild.id)
            user_id  = str(ctx.author.id)

            if not ctx.author.guild_permissions.administrator:
                await ctx.respond(
                    embed=discord.Embed(
                        title="🌸 權限不足!",
                        description="呼呼～只有管理員才能徵稅哦!\n幽幽子可不想被亂收稅呢～",
                        color=discord.Color.red()
                    ).set_footer(
                        text="稅金由管理員統一徵收 · 幽幽子",
                        icon_url=self.bot.user.display_avatar.url  # [Debug 修復 #2]
                    ),
                    ephemeral=True
                )
                return

            await ctx.defer()

            # [Debug 修復 #3] 徹底移除硬碟讀寫！直接引用記憶體中的 server_vault
            server_vault = self.data_manager.server_vault

            # 檢查記憶體中是否有人有幽靈幣
            if guild_id not in self.data_manager.balance or not self.data_manager.balance[guild_id]:
                await ctx.followup.send(
                    embed=discord.Embed(
                        title="🌸 無人可稅!",
                        description="呼呼～這個伺服器還沒有人有幽靈幣哦!\n快去玩遊戲賺錢吧，幽幽子在等美味的供品～",
                        color=discord.Color.gold()
                    ).set_footer(text="國庫空空如也 · 幽幽子")
                )
                return

            # 收集徵稅數據與更新國庫 (全部在鎖內完成，確保經濟數據的原子性)
            tax_targets = {}  # user_id -> (balance, tax_rate, tax_amount, new_balance)
            total_tax = 0.0

            async with self.data_manager.balance_lock:
                balance = self.data_manager.balance
                
                # 1. 計算並扣除用戶稅金
                for taxed_uid, user_balance in list(balance[guild_id].items()):
                    if taxed_uid == user_id: continue
                    if not isinstance(user_balance, (int, float)) or user_balance <= 0: continue

                    tax_rate   = get_tax_rate(user_balance)
                    tax_amount = round(user_balance * tax_rate, 2)
                    new_bal    = round(user_balance - tax_amount, 2)

                    balance[guild_id][taxed_uid] = new_bal
                    tax_targets[taxed_uid] = (user_balance, tax_rate, tax_amount, new_bal)
                    total_tax += tax_amount

                # 2. 同步更新國庫 (在同一个鎖內，防止併發導致國庫數據錯誤)
                if total_tax > 0:
                    server_vault.setdefault(guild_id, {}).setdefault("vault", {"total": 0.0, "contributions": {}})
                    vault = server_vault[guild_id]["vault"]
                    
                    vault["total"] = round(vault["total"] + total_tax, 2)
                    for taxed_uid, (_, _, tax_amount, _) in tax_targets.items():
                        vault["contributions"][taxed_uid] = round(
                            vault["contributions"].get(taxed_uid, 0.0) + tax_amount, 2
                        )

            if not tax_targets:
                await ctx.followup.send(
                    embed=discord.Embed(
                        title="🌸 無人可稅!",
                        description="呼呼～沒有人有足夠的幽靈幣可以徵稅哦!\n幽幽子只好餓肚子啦～",
                        color=discord.Color.gold()
                    ).set_footer(text="國庫依然空虛 · 幽幽子")
                )
                return

            # [Debug 修復 #3] 鎖釋放後，統一呼叫一次 save_all_async 保存所有經濟數據 (包含 balance 和 server_vault)
            await self.data_manager.save_all_async()

            # 鎖外 fetch_user，取得顯示名稱 (避免阻塞 Event Loop)
            display_names = {}
            for taxed_uid in tax_targets:
                try:
                    user = await asyncio.wait_for(
                        self.bot.fetch_user(int(taxed_uid)), timeout=3.0
                    )
                    display_names[taxed_uid] = getattr(user, "display_name", user.name)
                except Exception:
                    display_names[taxed_uid] = f"用戶ID: {taxed_uid}"

            # 組裝顯示列表
            taxed_users = []
            for taxed_uid, (old_bal, rate, tax_amt, new_bal) in tax_targets.items():
                name = display_names.get(taxed_uid, f"用戶ID: {taxed_uid}")
                taxed_users.append(
                    f"**{name}** "
                    f"（{format_number(old_bal)} → {format_number(new_bal)}）"
                    f" 課稅 {rate * 100:.0f}%：{format_number(tax_amt)} 幽靈幣"
                )

            current_vault = server_vault[guild_id]["vault"]["total"]
            executor      = ctx.author.display_name

            taxed_list = "\n".join(taxed_users[:10])
            if len(taxed_users) > 10:
                taxed_list += f"\n...以及其他 {len(taxed_users) - 10} 位靈魂"

            embed = discord.Embed(
                title="🌸 幽幽子的動態稅金徵收!",
                description=(
                    f"呼呼～幽幽子在櫻花樹下對伺服器內所有亡魂徵收美味稅金!\n"
                    f"國庫又豐盈啦～\n\n"
                    f"📋 **徵稅執行者:** {executor}\n"
                    f"👥 **徵稅人數:** {len(taxed_users)} 位靈魂"
                ),
                color=discord.Color.from_rgb(205, 133, 232)
            )
            embed.add_field(name="💸 被徵稅者",  value=taxed_list, inline=False)
            embed.add_field(
                name="📊 徵稅統計",
                value=(
                    f"```yaml\n"
                    f"本次稅金: {format_number(total_tax)} 幽靈幣\n"
                    f"國庫餘額: {format_number(current_vault)} 幽靈幣\n"
                    f"```"
                ),
                inline=False
            )
            embed.set_footer(
                text="幽幽子：賞花、吃點心、收稅金三連發! · 幽幽子",
                icon_url=self.bot.user.display_avatar.url  # [Debug 修復 #2]
            )

            await ctx.followup.send(embed=embed)
            logger.info(
                f"💰 {executor}({user_id}) 徵收稅金 {total_tax:.2f} 幽靈幣，"
                f"共 {len(taxed_users)} 位用戶，國庫餘額: {current_vault:.2f}"
            )

        except Exception as e:
            logger.error(f"❌ 稅金徵收失敗: {e}", exc_info=True)
            embed = discord.Embed(
                title="❌ 徵稅術式崩壞",
                description=(
                    "哎呀，徵稅時發生了不明之力...\n"
                    "請稍後再試或使用 `/feedback` 回報給幽幽子的主人～"
                ),
                color=discord.Color.dark_red()
            )
            embed.set_footer(text="術式受阻，請稍後重試 · 幽幽子")
            try:
                # [Debug 修復 #4] 使用 Pycord 標準的 ctx.response.is_done()
                if not ctx.response.is_done():
                    await ctx.respond(embed=embed, ephemeral=True)
                else:
                    await ctx.followup.send(embed=embed, ephemeral=True)
            except Exception:
                logger.exception("❌ 無法發送徵稅錯誤訊息")


def setup(bot: discord.Bot):
    bot.add_cog(Tax(bot))
    logger.info("🌸 稅金徵收模組已於櫻花樹下綻放完成")
