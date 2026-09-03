import os
import logging
import aiohttp
import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta, time

logger = logging.getLogger("SakuraBot.events.on_air")
LOCAL_TIMEZONE = timezone(timedelta(hours=8))

WAQI_TOKEN = os.getenv("WAQI_TOKEN")
OPENAQ_API_KEY = os.getenv("OPENAQ_API_KEY")

HOURLY_TIMES = [
    time(hour=h, minute=0, second=0, tzinfo=LOCAL_TIMEZONE) for h in range(24)
]


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


def pm25_to_us_aqi(c: float) -> int | None:
    if c is None:
        return None
    bp = [
        (0.0, 12.0, 0, 50),
        (12.1, 35.4, 51, 100),
        (35.5, 55.4, 101, 150),
        (55.5, 150.4, 151, 200),
        (150.5, 250.4, 201, 300),
        (250.5, 350.4, 301, 400),
        (350.5, 500.4, 401, 500),
    ]
    for c_low, c_high, i_low, i_high in bp:
        if c_low <= c <= c_high:
            return round((i_high - i_low) / (c_high - c_low) * (c - c_low) + i_low)
    if c > 500.4:
        return 500
    return None


def pick_dominant(pollutants: dict) -> str:
    if not pollutants:
        return "資料未提供"
    best_name, best_val = None, -1.0
    for k, v in pollutants.items():
        if v is None:
            continue
        try:
            val = float(v)
        except (TypeError, ValueError):
            continue
        key = k.lower().replace("_", "").replace(".", "")
        score = val * 1.2 if "pm25" in key else val
        if score > best_val:
            best_val = score
            best_name = k
    return best_name or "資料未提供"


class AirQualityMonitor(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.data_manager = bot.data_manager
        self.session = None
        self._startup_done = False
        self.check_air.start()
        logger.info("空氣 V2：WAQI + OpenAQ 補洞 + OMAQ backup · notify_cache")

    def cog_unload(self):
        self.check_air.cancel()
        if self.session and not self.session.closed:
            self.bot.loop.create_task(self.session.close())

    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def _get_trend(self, city: str, current_aqi: int) -> str:
        prev = self.data_manager.get_air_cache(city)
        self.data_manager.set_air_cache(city, current_aqi)

        if not prev or prev.get("aqi") is None:
            return "🆕 首次記錄"
        diff = current_aqi - int(prev["aqi"])
        if diff > 0:
            return f"🔺 上升 +{diff}（空氣變差）"
        if diff < 0:
            return f"🔽 下降 {diff}（空氣好轉）"
        return "➡️ 持平"

    async def fetch_waqi(self, city_name: str, slug: str) -> dict | None:
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
            d = data.get("data") or {}
            aqi = d.get("aqi")
            if aqi is None or aqi == "-":
                return None
            try:
                aqi = int(aqi)
            except (ValueError, TypeError):
                return None

            dominent = d.get("dominentpol")
            if not dominent or dominent == "-":
                dominent = None

            pollutants = {}
            for k, v in (d.get("iaqi") or {}).items():
                if isinstance(v, dict) and "v" in v:
                    pollutants[k] = v["v"]

            return {
                "city": city_name,
                "aqi": aqi,
                "dominent": dominent,
                "time": (d.get("time") or {}).get("s", "未知時間"),
                "pollutants": pollutants,
                "source": "WAQI",
            }
        except Exception as e:
            logger.error(f"WAQI {city_name} 失敗: {e}")
            return None

    async def fetch_openaq(self, city_name: str, lat, lon) -> dict | None:
        if not OPENAQ_API_KEY or lat is None or lon is None:
            return None
        headers = {"X-API-Key": OPENAQ_API_KEY}
        try:
            session = await self.get_session()
            loc_url = (
                "https://api.openaq.org/v3/locations"
                f"?coordinates={round(float(lat), 4)},{round(float(lon), 4)}"
                "&radius=25000&limit=5"
            )
            async with session.get(loc_url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    return None
                loc_data = await resp.json()

            results = loc_data.get("results") or []
            if not results:
                return None

            location = results[0]
            loc_id = location.get("id")
            sensor_param = {}
            for s in location.get("sensors") or []:
                sid = s.get("id")
                param = (s.get("parameter") or {}).get("name") or s.get("name")
                if sid is not None and param:
                    sensor_param[sid] = str(param).lower()

            latest_url = f"https://api.openaq.org/v3/locations/{loc_id}/latest"
            async with session.get(latest_url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    return None
                latest_data = await resp.json()

            pollutants = {}
            time_str = None
            for row in latest_data.get("results") or []:
                pname = sensor_param.get(row.get("sensorsId"))
                val = row.get("value")
                if not pname or val is None:
                    continue
                pollutants[pname] = val
                dt = (row.get("datetime") or {}).get("local") or (
                    row.get("datetime") or {}
                ).get("utc")
                if dt:
                    time_str = dt

            if not pollutants:
                return None

            pm25 = None
            for k, v in pollutants.items():
                key = k.replace(".", "").replace("_", "")
                if "pm25" in key:
                    try:
                        pm25 = float(v)
                        break
                    except (TypeError, ValueError):
                        pass

            aqi = pm25_to_us_aqi(pm25) if pm25 is not None else None
            return {
                "city": city_name,
                "aqi": aqi,
                "dominent": pick_dominant(pollutants),
                "time": time_str or "未知時間",
                "pollutants": pollutants,
                "source": "OpenAQ",
            }
        except Exception as e:
            logger.error(f"OpenAQ {city_name} 失敗: {e}")
            return None

    async def fetch_omaq(self, city_name: str, lat, lon) -> dict | None:
        if lat is None or lon is None:
            return None
        url = (
            "https://air-quality-api.open-meteo.com/v1/air-quality"
            f"?latitude={lat}&longitude={lon}"
            "&current=us_aqi,pm2_5,pm10,carbon_monoxide,nitrogen_dioxide,ozone,sulphur_dioxide"
            "&timezone=auto"
        )
        try:
            session = await self.get_session()
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
            cur = data.get("current") or {}
            aqi = cur.get("us_aqi")
            if aqi is None:
                return None
            try:
                aqi = int(aqi)
            except (TypeError, ValueError):
                return None

            pollutants = {}
            mapping = {
                "pm2_5": "pm25",
                "pm10": "pm10",
                "carbon_monoxide": "co",
                "nitrogen_dioxide": "no2",
                "ozone": "o3",
                "sulphur_dioxide": "so2",
            }
            for src, name in mapping.items():
                if cur.get(src) is not None:
                    pollutants[name] = cur.get(src)

            return {
                "city": city_name,
                "aqi": aqi,
                "dominent": pick_dominant(pollutants),
                "time": cur.get("time") or "未知時間",
                "pollutants": pollutants,
                "source": "Open-Meteo",
            }
        except Exception as e:
            logger.error(f"OMAQ {city_name} 失敗: {e}")
            return None

    async def fetch_station(self, city_name: str, slug, lat, lon) -> dict | None:
        waqi = await self.fetch_waqi(city_name, slug or "")
        openaq = None
        if waqi is None or not waqi.get("dominent"):
            openaq = await self.fetch_openaq(city_name, lat, lon)

        if waqi and openaq:
            return {
                "city": city_name,
                "aqi": waqi["aqi"],
                "dominent": waqi.get("dominent")
                or openaq.get("dominent")
                or "資料未提供",
                "time": waqi.get("time") or openaq.get("time") or "未知時間",
                "source": "WAQI + OpenAQ",
            }
        if waqi:
            return {
                "city": city_name,
                "aqi": waqi["aqi"],
                "dominent": waqi.get("dominent") or "資料未提供",
                "time": waqi.get("time") or "未知時間",
                "source": "WAQI",
            }
        if openaq and openaq.get("aqi") is not None:
            return {
                "city": city_name,
                "aqi": openaq["aqi"],
                "dominent": openaq.get("dominent") or "資料未提供",
                "time": openaq.get("time") or "未知時間",
                "source": "OpenAQ",
            }
        return await self.fetch_omaq(city_name, lat, lon)

    async def _do_check_air(self):
        logger.info("🌸 空氣品質整點推播開始...")
        changed = False

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
                data = await self.fetch_station(
                    c.get("name"), c.get("air"), c.get("lat"), c.get("lon")
                )
                if data and data.get("aqi") is not None:
                    data["trend"] = self._get_trend(data["city"], data["aqi"])
                    changed = True
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
                embed.add_field(
                    name=f"📍 {item['city']}",
                    value=(
                        f"**AQI：{item['aqi']}**\n"
                        f"**趨勢：{item.get('trend', '')}**\n"
                        f"等級：{level}\n"
                        f"主要污染物：`{item.get('dominent') or '資料未提供'}`\n"
                        f"**🏃 跑步建議：** {advice}\n"
                        f"更新時間：{item.get('time', '—')}\n"
                        f"來源：{item.get('source', '—')}"
                    ),
                    inline=False,
                )
            sources = sorted({r.get("source", "") for r in results})
            embed.set_footer(text=f"資料：{' / '.join(sources)} · 每整點 · /notify")

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

        if changed:
            await self.data_manager.save_all_async()

    @tasks.loop(time=HOURLY_TIMES)
    async def check_air(self):
        await self._do_check_air()

    @check_air.before_loop
    async def before_check_air(self):
        await self.bot.wait_until_ready()
        if not self._startup_done:
            self._startup_done = True
            logger.info("🌸 空氣：啟動首次推播...")
            await self._do_check_air()


def setup(bot: discord.Bot):
    bot.add_cog(AirQualityMonitor(bot))
    logger.info("空氣品質 V2 已綻放")
