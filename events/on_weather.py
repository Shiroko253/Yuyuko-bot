import logging
import aiohttp
import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta, time

logger = logging.getLogger("SakuraBot.events.on_weather")
LOCAL_TIMEZONE = timezone(timedelta(hours=8))

def weather_description(code: int) -> str:
    mapping = {
        0: "晴朗 ☀️", 1: "大致晴朗 🌤️", 2: "局部多雲 ⛅", 3: "陰天 ☁️",
        45: "有霧 🌫️", 48: "霧凇 🌫️",
        51: "小毛毛雨 🌦️", 53: "毛毛雨 🌦️", 55: "大毛毛雨 🌧️",
        61: "小雨 🌧️", 63: "中雨 🌧️", 65: "大雨 🌧️",
        80: "陣雨 🌦️", 81: "中等陣雨 🌧️", 82: "強陣雨 ⛈️",
        95: "雷雨 ⛈️", 96: "雷雨伴冰雹 ⛈️", 99: "強雷雨伴冰雹 ⛈️",
    }
    return mapping.get(code, f"未知天氣 ({code})")

class WeatherMonitor(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.data_manager = bot.data_manager
        self.session = None
        self.weather_task.start()
        logger.info("天氣 V2 已部署（每 1 小時正點）")

    def cog_unload(self):
        self.weather_task.cancel()
        if self.session and not self.session.closed:
            self.bot.loop.create_task(self.session.close())

    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def fetch_weather(self, city: str, lat: float, lon: float):
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
            "weather_code,wind_speed_10m,precipitation"
            "&hourly=precipitation_probability"
            "&forecast_days=1&timezone=auto"
        )
        try:
            session = await self.get_session()
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                c = data.get("current", {})
                probs = (data.get("hourly") or {}).get("precipitation_probability") or []
                return {
                    "city": city,
                    "temp": c.get("temperature_2m"),
                    "feels": c.get("apparent_temperature"),
                    "humidity": c.get("relative_humidity_2m"),
                    "wind": c.get("wind_speed_10m"),
                    "code": c.get("weather_code"),
                    "rain_prob": probs[0] if probs else None,
                }
        except Exception as e:
            logger.error(f"取得 {city} 天氣失敗: {e}")
            return None

    # 🌸 修改重點：改為每個小時的 00 分準時觸發
    @tasks.loop(time=time(minute=0, tzinfo=LOCAL_TIMEZONE))
    async def weather_task(self):
        logger.info("🌸 天氣推播開始...")
        for guild_id, conf in list(self.data_manager.guild_config.items()):
            w_conf = conf.get("weather")
            if not w_conf or not w_conf.get("channel_id"):
                continue
            
            channel_id = int(w_conf["channel_id"])
            country = w_conf.get("country")
            city = w_conf.get("city")
            cities = self.data_manager.resolve_cities(country, city)
            _, region = self.data_manager.get_region(country)
            region_label = region.get("label", country or "預設")
            
            results = []
            for c in cities:
                data = await self.fetch_weather(
                    c.get("name"), c.get("lat"), c.get("lon")
                )
                if data:
                    results.append(data)
                    
            if not results:
                continue
                
            scope = f"{region_label}" + (f" / {city}" if city else "（重點城市）")
            embed = discord.Embed(
                title="🌤️ 天氣報告",
                description=f"幽幽子每小時幫你看天氣～\n範圍：**{scope}**",
                color=discord.Color.from_rgb(135, 206, 250),
                timestamp=datetime.now(LOCAL_TIMEZONE),
            )
            
            for item in results:
                desc = weather_description(
                    item["code"] if item["code"] is not None else -1
                )
                rain = item["rain_prob"]
                rain_text = f"{rain}%" if rain is not None else "—"
                embed.add_field(
                    name=f"📍 {item['city']}",
                    value=(
                        f"**溫度**：{item['temp']}°C\n"
                        f"**體感**：{item['feels']}°C\n"
                        f"**濕度**：{item['humidity']}%\n"
                        f"**風速**：{item['wind']} km/h\n"
                        f"**降雨機率**：{rain_text}\n"
                        f"**天氣**：{desc}"
                    ),
                    inline=True,
                )
                
            embed.set_footer(text="資料來源：Open-Meteo • 每 1 小時 • /notify")
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    logger.error(f"找不到天氣頻道 {channel_id}")
                    continue
                    
            try:
                await channel.send(embed=embed)
            except Exception as e:
                logger.error(f"天氣推播失敗 {guild_id}: {e}")

    @weather_task.before_loop
    async def before_weather_task(self):
        await self.bot.wait_until_ready()

def setup(bot: discord.Bot):
    bot.add_cog(WeatherMonitor(bot))
    logger.info("天氣 V2 已綻放")
