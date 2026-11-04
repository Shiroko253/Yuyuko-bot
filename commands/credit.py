import discord
from discord.ext import commands
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger("SakuraBot.Credit")
TZ = ZoneInfo("Asia/Taipei")

# 賭徒職業清單（工作無法恢復信譽的職業）
GAMBLER_JOBS = {"賭徒"}

CREDIT_LEVELS = [
    (10, 10, "🟢 完美信用",  "信譽無瑕，國庫向你完全開放！",            discord.Color.green()),
    ( 8,  9, "🟢 良好信用",  "信譽良好，幽幽子對你很放心～",            discord.Color.from_rgb(0, 200, 100)),
    ( 5,  7, "🟡 普通信用",  "信譽尚可，但請準時還款哦～",              discord.Color.gold()),
    ( 3,  4, "🟠 信用偏低",  "信譽偏低，再不改善借貸將受限！",          discord.Color.orange()),
    ( 1,  2, "🔴 信用危險",  "信譽岌岌可危，距離禁止借貸僅一步！",      discord.Color.red()),
    ( 0,  0, "⛔ 禁止借貸",  "信譽歸零，國庫已拒絕你的一切借貸申請！",  discord.Color.dark_red()),
]

def get_level(score: int) -> tuple:
    for lo, hi, label, desc, color in CREDIT_LEVELS:
        if lo <= score <= hi:
            return label, desc, color
    return "❓ 未知", "無法判斷信譽狀況", discord.Color.light_grey()

def credit_bar(score: int) -> str:
    filled = max(0, min(10, score))
    empty  = 10 - filled
    if score >= 8: bar = "🟢" * filled + "⬜" * empty
    elif score >= 5: bar = "🟡" * filled + "⬜" * empty
    elif score >= 1: bar = "🔴" * filled + "⬜" * empty
    else: bar = "⬛" * 10
    return f"{bar}  **{score}/10**"


class Credit(commands.Cog):
    """💳 幽幽子的靈魂信譽系統 💳"""

    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.data_manager = bot.data_manager
        logger.info("💳 信譽查詢系統已載入")

    # ──────────────────────────────────────────────────────
    # 信譽恢復 #1：時間自動恢復（每 7 天無逾期 +1）
    # ──────────────────────────────────────────────────────
    async def try_time_recovery(self, guild_id: str, user_id: str) -> int:
        """每 7 天無逾期記錄可自動 +1 信譽。"""
        need_save = False
        
        # [Debug 修復] 使用 balance_lock 保護記憶體修改
        async with self.data_manager.balance_lock:
            record = self.data_manager.credit.setdefault(guild_id, {}).setdefault(user_id, {"score": 10})
            score = record.get("score", 10)

            if score >= 10:
                return score

            now = datetime.now(TZ)
            last_str = record.get("last_time_recovery")

            if last_str:
                last_dt = datetime.fromisoformat(last_str)
                if last_dt.tzinfo is None: last_dt = last_dt.replace(tzinfo=TZ)
                days_since = (now - last_dt).days
            else:
                days_since = 7

            if days_since >= 7:
                score = min(10, score + 1)
                record["score"] = score
                record["last_time_recovery"] = now.isoformat()
                need_save = True
                logger.info(f"💳 時間恢復: {user_id} 信譽 +1 → {score}")

        # [Debug 修復] 鎖釋放後，統一呼叫 save_all_async
        if need_save:
            await self.data_manager.save_all_async()

        return score

    # ──────────────────────────────────────────────────────
    # 信譽恢復 #2：還清借貸 +1
    # ──────────────────────────────────────────────────────
    async def recover_on_repay(self, guild_id: str, user_id: str) -> tuple:
        """還清借貸後信譽 +1。回傳 (old_score, new_score)。"""
        async with self.data_manager.balance_lock:
            record = self.data_manager.credit.setdefault(guild_id, {}).setdefault(user_id, {"score": 10})
            old = record.get("score", 10)
            new = min(10, old + 1)
            record["score"] = new
            logger.info(f"💳 還款恢復: {user_id} 信譽 {old}→{new}")
            
        await self.data_manager.save_all_async()
        return old, new

    # ──────────────────────────────────────────────────────
    # 信譽恢復 #3：工作恢復 +1（非賭徒，每日限一次）
    # ──────────────────────────────────────────────────────
    async def recover_on_work(self, guild_id: str, user_id: str, job: str) -> tuple:
        """非賭徒職業工作成功後信譽 +1（每日限一次）。回傳 (old_score, new_score, recovered: bool)。"""
        need_save = False
        
        async with self.data_manager.balance_lock:
            record = self.data_manager.credit.setdefault(guild_id, {}).setdefault(user_id, {"score": 10})
            
            if job in GAMBLER_JOBS:
                return record.get("score", 10), record.get("score", 10), False

            old = record.get("score", 10)
            if old >= 10:
                return old, old, False

            now = datetime.now(TZ)
            last_work_str = record.get("last_work_recovery")

            if last_work_str:
                last_work = datetime.fromisoformat(last_work_str)
                if last_work.tzinfo is None: last_work = last_work.replace(tzinfo=TZ)
                if last_work.date() == now.date():
                    return old, old, False

            new = min(10, old + 1)
            record["score"] = new
            record["last_work_recovery"] = now.isoformat()
            need_save = True
            logger.info(f"💳 工作恢復: {user_id} 信譽 {old}→{new}")

        if need_save:
            await self.data_manager.save_all_async()
            
        return old, new, True

    # ──────────────────────────────────────────────────────
    # /credit 指令
    # ──────────────────────────────────────────────────────
    @discord.slash_command(name="credit", description="💳 查詢你在冥界的借貸信譽值")
    async def credit_cmd(
        self,
        ctx: discord.ApplicationContext,
        # [Debug 修復] 採用標準 Pycord 寫法，消除 IDE 警告
        member: discord.Member = discord.Option(
            discord.Member,
            description="查詢指定成員（不填則查詢自己）",
            required=False,
            default=None
        )
    ):
        """查詢信譽值，可查自己或指定成員 (純查詢，不需要備份攔截)"""
        if not ctx.guild:
            await ctx.respond("❌ 信譽查詢只能在伺服器中使用哦～", ephemeral=True)
            return
        
        if not await self.data_manager.check_economy_enabled(ctx, "credit"):
            return

        target = member or ctx.author
        guild_id = str(ctx.guild.id)
        user_id = str(target.id)
        is_self = (target.id == ctx.author.id)

        try:
            # [Debug 修復] 直接讀取記憶體，瞬間完成，無需任何 I/O！
            record = self.data_manager.credit.get(guild_id, {}).get(user_id, {})
            score = record.get("score", 10)
            label, desc, color = get_level(score)

            last_str = record.get("last_time_recovery")
            if score >= 10:
                recovery_text = "✅ 信譽已滿，無需恢復"
            elif last_str:
                last_dt = datetime.fromisoformat(last_str)
                if last_dt.tzinfo is None: last_dt = last_dt.replace(tzinfo=TZ)
                days_since = (datetime.now(TZ) - last_dt).days
                days_left = max(0, 7 - days_since)
                recovery_text = f"⏳ 距下次時間自動恢復：**{days_left}** 天"
            else:
                recovery_text = "⏳ 距下次時間自動恢復：**7** 天"

            embed = discord.Embed(
                title=f"💳 {'你的' if is_self else target.display_name + ' 的'}冥界信譽報告",
                color=color
            )
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.add_field(name="📊 信譽評級", value=f"**{label}**\n{desc}", inline=False)
            embed.add_field(name="🔢 信譽條", value=credit_bar(score), inline=False)
            embed.add_field(name="⏰ 恢復進度", value=recovery_text, inline=False)
            embed.add_field(
                name="📋 信譽規則",
                value=(
                    "```yaml\n"
                    "預設值:              10 點\n"
                    "逾期30天強制還款:    -1 點\n"
                    "有未還款時再借貸:    -3 點\n"
                    "信譽歸零:            禁止借貸\n"
                    "───────────────────\n"
                    "恢復途徑:\n"
                    "  還清借貸:          +1 點\n"
                    "  工作（非賭徒）:    +1 點/天\n"
                    "  無逾期 7 天:       +1 點\n"
                    "```"
                ),
                inline=False
            )

            if score <= 4:
                embed.add_field(
                    name="⚠️ 警告",
                    value=f"信譽還剩 **{score}** 點，降至 0 將**永久禁止借貸**！\n透過工作或還清借貸可恢復信譽。",
                    inline=False
                )

            embed.set_footer(text="誠信借貸，守護冥界金融秩序 · 幽幽子")
            await ctx.respond(embed=embed)
            logger.info(f"{ctx.author} 查詢了 {target} 的信譽值: {score}")

        except Exception as e:
            logger.error(f"❌ 信譽查詢失敗: {e}", exc_info=True)
            await ctx.respond("❌ 信譽查詢時發生錯誤，請稍後再試", ephemeral=True)


def setup(bot: discord.Bot):
    bot.add_cog(Credit(bot))
    logger.info("💳 信譽查詢 Cog 已載入")
