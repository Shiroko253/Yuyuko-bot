import os
import logging
import aiohttp
import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta, time

logger = logging.getLogger("SakuraBot.events.on_air")
LOCAL_TIMEZONE = timezone(timedelta(hours=8))
WAQI_TOKEN = os.getenv("WAQI_TOKEN")


def get_aqi_info(aqi: int):
    if aqi <= 50:
        return "🟢 良好", "非常適合出門跑步！", discord.Color.green()
    if aqi <= 100:
        return "🟡 普通", "可以出門跑步，敏感體質建議縮短時間。", discord.Color.gold()
    if aqi <= 150:
        return "🟠 對敏感族群不健康", "不建議激烈戶外運動。", discord.Color.orange()
    if aqi <= 200:
        return "🔴 不健康", "不建議出門跑步。", discord.Color.red()
    if aqi <= 300:
        return "🟣 非常不健康", "請避免戶外活動。", discord.Color.purple()
    return "🟤 危險", "請待在室內。", discord.Color.dark_red()


class AirQualityMonitor(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.data_manager = bot.data_manager
        self.session = None
        self.last_aqi = {}  # 🌸 新增：記住每個城市上一次的 AQI，用來對比趨勢
        self.check_air.start()
        logger.info("空氣品質 V2 已部署（每 1 小時正點・含趨勢對比）")

    def cog_unload(self):
        self.check_air.cancel()
        if self.session and not self.session.closed:
            self.bot.loop.create_task(self.session.close())

    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def fetch_station(self, city_name: str, slug: str):
        if not WAQI_TOKEN or not slug:
            return None

        url = f"https://api.waqi.info/feed/{slug}/?token={WAQI_TOKEN}"
        try:
            session = await self.get_session()
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if data.get("status") != "ok":
                    return None

                aqi = data["data"].get("aqi")
                if aqi is None or aqi == "-":
                    return None
                try:
                    aqi = int(aqi)
                except (ValueError, TypeError):
                    return None

                time_str = data["data"].get("time", {}).get("s", "未知時間")
                dominent = data["data"].get("dominentpol")
                if not dominent or dominent == "-":
                    dominent = "資料未提供"

                return {
                    "city": city_name,
                    "aqi": aqi,
                    "time": time_str,
                    "dominent": dominent,
                }
        except Exception as e:
            logger.error(f"取得 {city_name} 失敗: {e}")
            return None

    def _get_trend(self, city: str, current_aqi: int) -> str:
        """🌸 新增：對比上一次 AQI，回傳趨勢文字"""
        prev = self.last_aqi.get(city)
        self.last_aqi[city] = current_aqi  # 更新為最新值

        if prev is None:
            return "🆕 首次記錄"

        diff = current_aqi - prev
        if diff > 0:
            return f"🔺 上升 +{diff}（空氣變差）"
        elif diff < 0:
            return f"🔽 下降 {diff}（空氣好轉）"
        else:
            return "➡️ 持平"

    @tasks.loop(time=time(minute=0, tzinfo=LOCAL_TIMEZONE))
    async def check_air(self):
        logger.info("🌸 空氣品質推播開始...")
        for guild_id, conf in list(self.data_manager.guild_config.items()):
            air_conf = conf.get("air")
            if not air_conf or not air_conf.get("channel_id"):
                continue

            channel_id = int(air_conf["channel_id"])
            country = air_conf.get("country")
            city = air_conf.get("city")
            cities = self.data_manager.resolve_cities(country, city)
            _, region = self.data_manager.get_region(country)
            region_label = region.get("label", country or "預設")

            results = []
            for c in cities:
                data = await self.fetch_station(c.get("name"), c.get("air"))
                if data:
                    # 🌸 新增：計算趨勢
                    data["trend"] = self._get_trend(data["city"], data["aqi"])
                    results.append(data)

            if not results:
                continue

            max_aqi = max(r["aqi"] for r in results)
            _, _, color = get_aqi_info(max_aqi)
            scope = f"{region_label}" + (f" / {city}" if city else "（重點城市）")

            embed = discord.Embed(
                title="🌸 空氣品質更新",
                description=f"幽幽子幫你盯著空氣～\n範圍：**{scope}**",
                color=color,
                timestamp=datetime.now(LOCAL_TIMEZONE),
            )

            for item in results:
                level, advice, _ = get_aqi_info(item["aqi"])
                trend = item.get("trend", "")
                embed.add_field(
                    name=f"📍 {item['city']}",
                    value=(
                        f"**AQI：{item['aqi']}**\n"
                        f"**趨勢：{trend}**\n"
                        f"等級：{level}\n"
                        f"主要污染物：`{item['dominent']}`\n"
                        f"**🏃 跑步建議：** {advice}\n"
                        f"更新時間：{item['time']}"
                    ),
                    inline=False,
                )

            embed.set_footer(text="資料來源：WAQI • 每 1 小時 • /notify")
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    logger.error(f"找不到空氣頻道 {channel_id}")
                    continue

            try:
                await channel.send(embed=embed)
            except Exception as e:
                logger.error(f"空氣推播失敗 {guild_id}: {e}")

    @check_air.before_loop
    async def before_check_air(self):
        await self.bot.wait_until_ready()


def setup(bot: discord.Bot):
    bot.add_cog(AirQualityMonitor(bot))
    logger.info("空氣品質 V2 已綻放（含趨勢對比）")
