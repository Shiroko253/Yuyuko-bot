import os
import logging
import aiohttp
import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta, time

logger = logging.getLogger("SakuraBot.events.on_weather")
LOCAL_TIMEZONE = timezone(timedelta(hours=8))
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

HOURLY_TIMES = [
    time(hour=h, minute=0, second=0, tzinfo=LOCAL_TIMEZONE) for h in range(24)
]


def weather_with_emoji(text: str | None, code: int | None = None) -> str:
    if not text:
        text = "未知天氣"
    t = text.lower()
    rules = [
        (["雷暴", "雷", "thunder"], "⛈️"),
        (["暴雨", "大雨", "heavy rain", "torrential"], "🌧️"),
        (["陣雨", "showers"], "🌦️"),
        (["雨", "rain", "drizzle", "毛毛", "細雨"], "🌧️"),
        (["雪", "snow", "blizzard"], "❄️"),
        (["霧", "mist", "fog", "haze", "霾"], "🌫️"),
        (["陰", "overcast"], "☁️"),
        (["多雲", "partly", "cloud"], "⛅"),
        (["晴", "clear", "sunny"], "☀️"),
        (["風", "wind"], "💨"),
    ]
    for keys, emoji in rules:
        if any(k in t for k in keys):
            return f"{text} {emoji}"
    code_map = {
        1000: "☀️",
        1003: "⛅",
        1006: "☁️",
        1009: "☁️",
        1030: "🌫️",
        1063: "🌦️",
        1183: "🌧️",
        1189: "🌧️",
        1195: "🌧️",
        1273: "⛈️",
        1276: "⛈️",
    }
    if code in code_map:
        return f"{text} {code_map[code]}"
    return text


def get_wind_direction_text(degree=None, dir_text=None) -> str:
    if dir_text:
        return f" ({dir_text})"
    if degree is None:
        return ""
    dirs = ["北風", "東北風", "東風", "東南風", "南風", "西南風", "西風", "西北風"]
    return f" ({dirs[round(degree / 45) % 8]})"


def _fmt_delta(diff: float, unit: str = "") -> str:
    if diff > 0:
        return f"🔺 +{diff:.1f}{unit}"
    if diff < 0:
        return f"🔽 {diff:.1f}{unit}"
    return "➡️ 持平"


class WeatherMonitor(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.data_manager = bot.data_manager
        self.session = None
        self._startup_done = False
        self.weather_task.start()
        logger.info("天氣 V2：WeatherAPI · notify_cache · 整點")

    def cog_unload(self):
        self.weather_task.cancel()
        if self.session and not self.session.closed:
            self.bot.loop.create_task(self.session.close())

    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def _get_trends(self, city: str, temp, feels, rain_prob) -> str:
        prev = self.data_manager.get_weather_cache(city)
        self.data_manager.set_weather_cache(city, temp, feels, rain_prob=rain_prob)

        if not prev:
            return "🆕 首次記錄"

        parts = []
        if temp is not None and prev.get("temp") is not None:
            parts.append(f"氣溫 {_fmt_delta(temp - prev['temp'], '°C')}")
        if feels is not None and prev.get("feels") is not None:
            parts.append(f"體感 {_fmt_delta(feels - prev['feels'], '°C')}")
        if rain_prob is not None and prev.get("rain_prob") is not None:
            d = rain_prob - prev["rain_prob"]
            if d > 0:
                parts.append(f"降雨機率 🔺 +{d}%")
            elif d < 0:
                parts.append(f"降雨機率 🔽 {d}%")
            else:
                parts.append("降雨機率 ➡️ 持平")
        return " · ".join(parts) if parts else "➡️ 持平"

    async def fetch_weather(self, city: str, lat: float, lon: float):
        if not WEATHER_API_KEY:
            logger.error("未設定 WEATHER_API_KEY")
            return None

        url = (
            "https://api.weatherapi.com/v1/forecast.json"
            f"?key={WEATHER_API_KEY}"
            f"&q={lat},{lon}"
            "&days=2&aqi=no&alerts=no&lang=zh"
        )
        try:
            session = await self.get_session()
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning(
                        f"WeatherAPI {city} HTTP {resp.status}: {text[:200]}"
                    )
                    return None
                data = await resp.json()

            current = data.get("current") or {}
            condition = current.get("condition") or {}
            forecast_days = (data.get("forecast") or {}).get("forecastday") or []

            rain_prob = None
            if forecast_days:
                hours = forecast_days[0].get("hour") or []
                now_h = datetime.now(LOCAL_TIMEZONE).hour
                for h in hours:
                    t = h.get("time") or ""
                    try:
                        if int(t[-5:-3]) == now_h:
                            rain_prob = h.get("chance_of_rain")
                            break
                    except (ValueError, TypeError):
                        continue
                if rain_prob is None and hours:
                    rain_prob = hours[0].get("chance_of_rain")

            tmr = {}
            if len(forecast_days) > 1:
                day = forecast_days[1].get("day") or {}
                tmr_cond = day.get("condition") or {}
                tmr = {
                    "text": weather_with_emoji(
                        tmr_cond.get("text"), tmr_cond.get("code")
                    ),
                    "max": day.get("maxtemp_c"),
                    "min": day.get("mintemp_c"),
                    "rain": day.get("daily_chance_of_rain"),
                }

            temp = current.get("temp_c")
            feels = current.get("feelslike_c")
            text = weather_with_emoji(condition.get("text"), condition.get("code"))
            trend = self._get_trends(city, temp, feels, rain_prob)

            return {
                "city": city,
                "temp": temp,
                "feels": feels,
                "humidity": current.get("humidity"),
                "wind": current.get("wind_kph"),
                "wind_dir": current.get("wind_dir"),
                "wind_degree": current.get("wind_degree"),
                "text": text,
                "precip": current.get("precip_mm"),
                "rain_prob": rain_prob,
                "tomorrow": tmr,
                "trend": trend,
            }
        except Exception as e:
            logger.error(f"WeatherAPI 取得 {city} 失敗: {e}")
            return None

    async def _do_weather_task(self):
        logger.info("🌸 天氣整點推播開始（WeatherAPI）...")
        if not WEATHER_API_KEY:
            logger.error("WEATHER_API_KEY 未設定，跳過")
            return

        changed = False
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
                name, lat, lon = c.get("name"), c.get("lat"), c.get("lon")
                if name is None or lat is None or lon is None:
                    continue
                data = await self.fetch_weather(name, lat, lon)
                if data:
                    changed = True
                    results.append(data)

            if not results:
                continue

            scope = f"{region_label}" + (f" / {city}" if city else "（重點城市）")
            embed = discord.Embed(
                title="🌤️ 天氣報告",
                description=f"幽幽子整點幫你看天氣～\n範圍：**{scope}**",
                color=discord.Color.from_rgb(135, 206, 250),
                timestamp=datetime.now(LOCAL_TIMEZONE),
            )

            for item in results:
                rain = item.get("rain_prob")
                rain_text = f"{rain}%" if rain is not None else "—"
                precip = item.get("precip")
                precip_text = f"{precip} mm" if precip is not None else "—"
                wind_extra = get_wind_direction_text(
                    item.get("wind_degree"), item.get("wind_dir")
                )

                tmr = item.get("tomorrow") or {}
                if tmr.get("min") is not None and tmr.get("max") is not None:
                    tmr_rain = tmr.get("rain")
                    tmr_rain_text = f"{tmr_rain}%" if tmr_rain is not None else "—"
                    tmr_text = (
                        f"🔮 **明日：** {tmr.get('text') or '—'} | "
                        f"{tmr['min']}~{tmr['max']}°C | 降雨 {tmr_rain_text}"
                    )
                else:
                    tmr_text = "🔮 **明日：** 資料暫無"

                embed.add_field(
                    name=f"📍 {item['city']}",
                    value=(
                        f"**現在：** {item.get('text')} | {item.get('temp')}°C"
                        f"（體感 {item.get('feels')}°C）\n"
                        f"**趨勢：** {item.get('trend', '')}\n"
                        f"**濕度：** {item.get('humidity')}% | "
                        f"**風況：** {item.get('wind')} km/h{wind_extra}\n"
                        f"**降雨機率：** {rain_text} | **降水：** {precip_text}\n"
                        f"{tmr_text}"
                    ),
                    inline=False,
                )

            embed.set_footer(text="資料來源：WeatherAPI · 每整點 · /notify")

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

        if changed:
            await self.data_manager.save_all_async()

    @tasks.loop(time=HOURLY_TIMES)
    async def weather_task(self):
        await self._do_weather_task()

    @weather_task.before_loop
    async def before_weather_task(self):
        await self.bot.wait_until_ready()
        if not self._startup_done:
            self._startup_done = True
            logger.info("🌸 天氣：啟動首次推播...")
            await self._do_weather_task()


def setup(bot: discord.Bot):
    bot.add_cog(WeatherMonitor(bot))
    logger.info("天氣 V2 已綻放（WeatherAPI + notify_cache）")
