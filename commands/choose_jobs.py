import discord
from discord.ext import commands
import logging
import asyncio
import os

logger = logging.getLogger("SakuraBot.commands.choose_jobs")
# [Debug 修復] 引入專門的 Commands 錯誤日誌記錄器
commands_error_logger = logging.getLogger("SakuraBot.CommandsError")


class ChooseJob(commands.Cog):
    """✿ 冥界職業祭典 ✿"""
    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @discord.slash_command(name="choose_job", description="幽幽子邀你選擇靈魂的工作～")
    async def choose_job(self, ctx: discord.ApplicationContext):
        if not await self.data_manager.check_economy_enabled(ctx, "choose_job"):
            return
        
        try:
            if not await self.bot.data_manager.check_backup_status(ctx, "choose_job"):
                return

            guild_id = str(ctx.guild.id)
            user_id = str(ctx.user.id)
            user_config = self.bot.data_manager.user_config

            config_path = os.path.join(self.bot.data_manager.config_dir, "config.json")
            config_data = await asyncio.to_thread(self.bot.data_manager._load_json, config_path, {})
            
            jobs_list = config_data.get("jobs", [])
            jobs_data = jobs_list[0] if isinstance(jobs_list, list) and jobs_list else jobs_list if isinstance(jobs_list, dict) else {}

            if not isinstance(jobs_data, dict) or not jobs_data:
                await ctx.respond("職業數據尚未正確配置！", ephemeral=True)
                return

            # 獲取當前職業狀態
            user_info = user_config.get(guild_id, {}).get(user_id, {})
            current_job = user_info.get("job")
            current_sub_job = user_info.get("sub_job")

            # 計算 IT 程序員人數 (僅計算正職)
            it_count = sum(1 for u_info in user_config.get(guild_id, {}).values() if isinstance(u_info, dict) and u_info.get("job") == "IT程序員")

            options = []
            for job, data in jobs_data.items():
                if not isinstance(data, dict) or "min" not in data: continue
                
                # 定義被動描述
                passive_desc = ""
                if job == "賭徒": passive_desc = "【被動：賭徒的決定】下注x3/勝x6"
                elif job == "漁夫": passive_desc = "【被動：漁民的直覺】稀有漁獲機率提升"
                elif job == "釣魚佬": passive_desc = "【被動：釣魚佬的直覺】30%空軍率"
                
                desc = f"薪資: {data['min']}-{data['max']}\n{passive_desc}" if passive_desc else f"薪資: {data['min']}-{data['max']}"
                
                if job == "IT程序員" and it_count >= 2:
                    options.append(discord.SelectOption(label=f"{job} (正職)", description="已滿員", value=f"{job}_disabled", emoji="❌"))
                else:
                    suffix = " [副職]" if job == "釣魚佬" else " [正職]"
                    options.append(discord.SelectOption(label=f"{job}{suffix}", description=desc, value=job, emoji="🌸"))

            class JobSelect(discord.ui.Select):
                def __init__(self_inner, parent_view):
                    self_inner.parent_view = parent_view
                    super().__init__(placeholder="請選擇你的靈魂工作～", options=options[:25], min_values=1, max_values=1)

                async def callback(self_inner, interaction: discord.Interaction):
                    # [Debug 修復] 為 callback 加入 try-except，防止 Interaction 卡死
                    try:
                        if interaction.user.id != ctx.user.id:
                            await interaction.response.send_message("這不是你的冥界工作選擇喲～", ephemeral=True)
                            return

                        chosen_job = self_inner.values[0]
                        if "_disabled" in chosen_job:
                            await interaction.response.send_message("IT程序員已滿員，請選其他工作吧！", ephemeral=True)
                            return

                        # 確保數據結構存在
                        user_config.setdefault(guild_id, {}).setdefault(user_id, {})
                        u_info = user_config[guild_id][user_id]

                        # --- 核心邏輯：區分正職與副職，並處理互斥 ---
                        if chosen_job == "釣魚佬":
                            # 釣魚佬是副職
                            if not current_job:
                                await interaction.response.send_message("哎呀～你還沒有正職呢！請先選擇一個正常職業，才能成為釣魚佬哦！", ephemeral=True)
                                return
                            if current_job == "賭徒":
                                await interaction.response.send_message("賭徒的命運只在賭桌，無法成為釣魚佬副職哦！", ephemeral=True)
                                return
                            
                            # [新增互斥] 漁夫與釣魚佬衝突
                            if current_job == "漁夫":
                                await interaction.response.send_message(
                                    "哎呀～漁夫可是要駕駛小船出海捕魚的專業人士呢！\n"
                                    "每天在海上搏鬥狂風巨浪，怎麼有時間在岸邊悠閒地當釣魚佬呢？\n"
                                    "這兩者的生活方式可是完全衝突的哦～", ephemeral=True
                                )
                                return
                            
                            u_info["sub_job"] = "釣魚佬"
                            msg = f"你已將 **釣魚佬** 設為副職！\n你的正職依然是 **{current_job}**。\n*釣魚佬會在釣魚時觸發特殊被動哦～*"
                            color = discord.Color.blue()
                        else:
                            # 選擇的是正職
                            if current_job and current_job != chosen_job:
                                await interaction.response.send_message(f"你已經擁有正職 **{current_job}** 了！\n如果想更換正職，請先使用 `/reset_job` 放棄現有身份。", ephemeral=True)
                                return
                            
                            # [新增互斥] 漁夫與釣魚佬衝突
                            if chosen_job == "漁夫" and current_sub_job == "釣魚佬":
                                await interaction.response.send_message(
                                    "你已經是享受悠閒垂釣的釣魚佬了，怎麼能去當每天出海吹風的漁夫呢？\n"
                                    "快放下漁網，繼續享受岸邊的微風吧～\n"
                                    "(若想成為漁夫，請先使用 `/reset_job` 清除副職)", ephemeral=True
                                )
                                return

                            u_info["job"] = chosen_job
                            u_info.pop("sub_job", None) # 更換正職時，自動清除副職
                            msg = f"你已選擇 **{chosen_job}** 作為你的正職！"
                            color = discord.Color.green()

                        await self.bot.data_manager.save_all_async()

                        embed = discord.Embed(title="🌸 靈魂簽約成功！～", description=msg, color=color)
                        embed.set_footer(text="櫻花飄落，萬物皆美好～")

                        for child in self_inner.parent_view.children: child.disabled = True
                        self_inner.parent_view.stop()
                        await interaction.response.edit_message(embed=embed, view=self_inner.parent_view)
                        
                    except Exception as e:
                        logger.error(f"JobSelect callback 發生錯誤: {e}", exc_info=True)
                        try:
                            error_msg = "❌ 選擇職業時發生未知錯誤，請使用 `/feedback` 回報！"
                            if not interaction.response.is_done():
                                await interaction.response.send_message(error_msg, ephemeral=True)
                            else:
                                await interaction.followup.send(error_msg, ephemeral=True)
                        except Exception as e2:
                            # [Debug 修復] 記錄發送錯誤訊息失敗的錯誤
                            commands_error_logger.error(
                                f"JobSelect: 發送錯誤訊息失敗 - 原始錯誤: {e}, 發送錯誤: {e2}", 
                                exc_info=True
                            )

            class JobView(discord.ui.View):
                def __init__(self_inner, cog):
                    super().__init__(timeout=60)
                    self_inner.cog = cog
                    self_inner.message = None
                    self_inner.add_item(JobSelect(self_inner))

                async def on_timeout(self_inner):
                    for child in self_inner.children: child.disabled = True
                    if self_inner.message:
                        try: 
                            await self_inner.message.edit(view=self_inner)
                        except discord.NotFound:
                            pass
                        except Exception as e:
                            # [Debug 修復] 記錄超時編輯失敗的錯誤
                            commands_error_logger.error(f"JobView on_timeout 編輯訊息失敗: {e}", exc_info=True)

            # 顯示當前狀態提示
            status_desc = "你目前是一張白紙，快來選擇你的正職吧！"
            if current_job:
                status_desc = f"你目前的正職是 **{current_job}**"
                if current_sub_job:
                    status_desc += f"，副職是 **{current_sub_job}**"
                status_desc += "。\n(選擇正職需先重置，選擇副職則直接覆蓋)"

            view = JobView(self)
            embed = discord.Embed(title="🌸 冥界職業祭典開啟～", description=f"{status_desc}\n\n請從下方選擇：", color=discord.Color.blurple())
            embed.set_footer(text="正職決定薪資，副職決定釣魚被動！")
            
            response = await ctx.respond(embed=embed, view=view, ephemeral=True)
            view.message = await response.original_response()

        except Exception as e:
            # [Debug 修復] 為整個指令加入外層 try-except 防崩潰
            logger.error(f"choose_job 指令發生錯誤: {e}", exc_info=True)
            try:
                error_embed = discord.Embed(
                    title="❌ 職業祭典發生錯誤",
                    description=(
                        "嗚嗚...幽幽子在準備祭典時迷路了...\n"
                        "請稍後再試一次 `/choose_job`。\n\n"
                        "**如果反覆出現，請使用 `/feedback` 回報！**"
                    ),
                    color=discord.Color.dark_red()
                ).set_footer(text="請回報錯誤 · 幽幽子")
                
                if not ctx.response.is_done():
                    await ctx.respond(embed=error_embed, ephemeral=True)
                else:
                    await ctx.followup.send(embed=error_embed, ephemeral=True)
            except Exception as e2:
                commands_error_logger.error(
                    f"choose_job: 發送錯誤訊息失敗 - 原始錯誤: {e}, 發送錯誤: {e2}", 
                    exc_info=True
                )


def setup(bot: discord.Bot):
    bot.add_cog(ChooseJob(bot))
    # [修復] 加入符合幽幽子風格的載入日誌
    logger.info("🌸 冥界職業祭典系統已於櫻花樹下甦醒")
