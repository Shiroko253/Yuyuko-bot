import discord
from discord.ext import commands
from discord import Option
from discord.ui import View, Button, Modal, InputText, Select
import logging

logger = logging.getLogger("SakuraBot.commands.notify")

GROUP_LABELS = {
    "Asia": "🌏 亞洲",
    "Americas": "🌎 美洲",
    "Europe": "🌍 歐洲",
    "Oceania": "🌊 大洋洲",
    "Other": "📍 其他",
}


class CityModal(Modal):
    def __init__(self, cog, guild_id, key, channel, country_key, region):
        super().__init__(title="🌸 指定城市")
        self.cog = cog
        self.guild_id = guild_id
        self.key = key
        self.channel = channel
        self.country_key = country_key
        self.region = region
        self.add_item(
            InputText(
                label="城市名稱（英文）",
                placeholder="例如：Kuching / Tokyo / Los Angeles",
                required=True,
                max_length=50,
            )
        )

    async def callback(self, interaction: discord.Interaction):
        city_input = self.children[0].value.strip()
        names = [c["name"] for c in self.region.get("cities") or []]
        match = next((n for n in names if n.lower() == city_input.lower()), None)
        if not match:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="🌸 城市不在清單內",
                    description=(
                        f"「{city_input}」不在 **{self.region.get('label', '')}**。\n\n"
                        f"**可用：**\n" + "\n".join(f"• {n}" for n in names)
                    ),
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return
        await self.cog._save_and_confirm(
            interaction, self.guild_id, self.key, self.channel,
            self.country_key, self.region, match,
        )


class CityChooseView(View):
    def __init__(self, cog, author_id, guild_id, key, channel, country_key, region):
        super().__init__(timeout=120)
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id
        self.key = key
        self.channel = channel
        self.country_key = country_key
        self.region = region

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("這不是你的設定面板哦～", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="使用重點城市", style=discord.ButtonStyle.success, emoji="🌏")
    async def use_major(self, button: Button, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await self.cog._save_and_confirm(
            interaction, self.guild_id, self.key, self.channel,
            self.country_key, self.region, None, followup=True,
        )
        self.stop()

    @discord.ui.button(label="指定單一城市", style=discord.ButtonStyle.primary, emoji="📍")
    async def use_city(self, button: Button, interaction: discord.Interaction):
        await interaction.response.send_modal(
            CityModal(
                self.cog, self.guild_id, self.key, self.channel,
                self.country_key, self.region,
            )
        )

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, button: Button, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🌸 已取消",
                description="沒有變更推播設定。",
                color=discord.Color.light_grey(),
            ),
            view=self,
        )
        self.stop()


class CountrySelect(Select):
    def __init__(self, cog, author_id, guild_id, key, channel, group_name, items):
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id
        self.key = key
        self.channel = channel
        options = [
            discord.SelectOption(
                label=(region.get("label") or ck)[:100],
                value=ck,
                description=f"重點城市 {len(region.get('cities') or [])} 座"[:100],
            )
            for ck, region in items[:25]
        ]
        super().__init__(
            placeholder=f"{GROUP_LABELS.get(group_name, group_name)} — 選擇國家",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("這不是你的設定面板哦～", ephemeral=True)
            return

        country_key = self.values[0]
        _, region = self.cog.data_manager.get_region(country_key)
        major_list = "、".join(c["name"] for c in region.get("cities") or [])
        type_name = "天氣" if self.key == "weather" else "空氣品質"

        embed = discord.Embed(
            title="🌸 選擇推播範圍",
            description=(
                f"**類型**：`{type_name}`\n"
                f"**頻道**：{self.channel.mention}\n"
                f"**國家 / 地區**：**{region.get('label', country_key)}**\n\n"
                f"請選擇全部重點城市，或只推單一城市。"
            ),
            color=discord.Color.from_rgb(255, 182, 193),
        )
        embed.add_field(
            name=f"{region.get('label', '')} 重點城市",
            value=major_list or "（無）",
            inline=False,
        )
        embed.set_footer(text="2 分鐘內有效")

        view = CityChooseView(
            self.cog, self.author_id, self.guild_id, self.key,
            self.channel, country_key, region,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class CountrySelectView(View):
    def __init__(self, cog, author_id, guild_id, key, channel):
        super().__init__(timeout=180)
        grouped = cog.data_manager.regions_by_group()
        # View 最多約 5 個 Select；group 過多時只放前幾個 group 的 chunk
        row_count = 0
        for group_name, items in grouped.items():
            for i in range(0, len(items), 25):
                if row_count >= 5:
                    break
                chunk = items[i:i + 25]
                self.add_item(
                    CountrySelect(
                        cog, author_id, guild_id, key, channel, group_name, chunk
                    )
                )
                row_count += 1
            if row_count >= 5:
                break


class Notify(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.data_manager = bot.data_manager

    async def _save_and_confirm(
        self, interaction, guild_id, key, channel, country_key, region, city,
        followup=False,
    ):
        gc = self.data_manager.guild_config
        if guild_id not in gc:
            gc[guild_id] = {}

        gc[guild_id][key] = {
            "channel_id": channel.id,
            "country": country_key,
            "city": city,
        }
        await self.data_manager.save_all_async()

        type_label = "天氣 weather" if key == "weather" else "空氣品質 air"
        city_display = city if city else "（該國全部重點城市）"
        major_list = "、".join(c["name"] for c in region.get("cities") or [])

        embed = discord.Embed(
            title="🌸 推播設定完成",
            description="幽幽子記住了，之後會每小時幫你推播～",
            color=discord.Color.from_rgb(144, 238, 144),
        )
        embed.add_field(name="類型", value=f"`{type_label}`", inline=True)
        embed.add_field(name="頻道", value=channel.mention, inline=True)
        embed.add_field(
            name="國家 / 地區",
            value=f"**{region.get('label', country_key)}**",
            inline=False,
        )
        embed.add_field(name="城市", value=f"**{city_display}**", inline=False)
        if not city:
            embed.add_field(name="將包含的重點城市", value=major_list or "—", inline=False)
        embed.set_footer(
            text=f"由 {interaction.user.display_name} 設定 • 不填頻道再執行可關閉"
        )
        embed.timestamp = discord.utils.utcnow()

        logger.info(
            f"guild={guild_id} notify {key} -> #{channel.id} {country_key}/{city}"
        )

        if followup or interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=False)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=False)

    @discord.slash_command(
        name="notify",
        description="設定本伺服器的天氣或空氣品質推播（僅管理員）",
    )
    @discord.default_permissions(manage_guild=True)
    async def notify(
        self,
        ctx: discord.ApplicationContext,
        type: str = Option(str, "推播類型", choices=["weather", "air"]),
        channel: discord.TextChannel | None = Option(
            discord.TextChannel, "推播頻道（不填 = 關閉）", required=False
        ),
    ):
        try:
            if ctx.guild is None:
                await ctx.respond("🌸 只能在伺服器裡使用～", ephemeral=True)
                return

            guild_id = str(ctx.guild.id)
            gc = self.data_manager.guild_config
            if guild_id not in gc:
                gc[guild_id] = {}

            key = "weather" if type == "weather" else "air"
            type_name = "天氣" if key == "weather" else "空氣品質"

            if channel is None:
                old = gc[guild_id].pop(key, None)
                await self.data_manager.save_all_async()
                if old:
                    _, old_region = self.data_manager.get_region(old.get("country"))
                    old_label = old_region.get("label", old.get("country", "未知"))
                    old_city = old.get("city") or "重點城市"
                    desc = (
                        f"**{type_name}** 推播已關閉。\n\n"
                        f"先前：國家 **{old_label}** / 城市 **{old_city}**"
                    )
                else:
                    desc = f"**{type_name}** 本來就沒開啟。"
                await ctx.respond(
                    embed=discord.Embed(
                        title="🌸 推播已關閉",
                        description=desc,
                        color=discord.Color.from_rgb(255, 182, 193),
                    ),
                    ephemeral=True,
                )
                return

            embed = discord.Embed(
                title="🌸 選擇國家 / 地區",
                description=(
                    f"**類型**：`{type_name}`\n"
                    f"**頻道**：{channel.mention}\n\n"
                    f"請從下方各區清單選擇國家～"
                ),
                color=discord.Color.from_rgb(255, 182, 193),
            )
            embed.set_footer(text="選完國家後可再選重點城市或單一城市")

            view = CountrySelectView(self, ctx.user.id, guild_id, key, channel)
            await ctx.respond(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            logger.exception(f"notify 錯誤: {e}")
            await ctx.respond("🌸 設定時發生錯誤～", ephemeral=True)


def setup(bot: discord.Bot):
    bot.add_cog(Notify(bot))
    logger.info("推播設定模組已綻放")
