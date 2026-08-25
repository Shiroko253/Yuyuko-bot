import discord
from discord.ext import commands
import random
import asyncio
import logging

logger = logging.getLogger("SakuraBot.Quiz")


class QuizView(discord.ui.View):
    """幽幽子的問答視圖，如櫻花般優雅又帶著冥界的惡意"""

    def __init__(self, ctx, question_data):
        super().__init__(timeout=30)
        self.ctx = ctx
        self.question = question_data.get("question", "")
        self.correct_answer = question_data.get("correct", "")
        self.difficulty = question_data.get("difficulty", "medium")
        self.reward = question_data.get("reward", 50)
        self.answered = False
        self.message = None

        options = [self.correct_answer] + question_data.get("incorrect", [])
        random.shuffle(options)

        for option in options:
            self.add_item(QuizButton(option, self))

    async def on_timeout(self):
        if self.answered:
            return

        # [靈魂優化] 幽幽子風格的超時台詞：輕飄飄的殘忍
        timeout_messages = [
            "⏳ 哎呀，睡著了嗎？冥界的微風很舒服，適合做夢，但不適合答題哦～",
            "⏰ 猶豫的靈魂，可是會被冥界的迷霧吞噬的呢...時間到囉。",
            "⌛ 呵呵，連思考的時間都沒有了嗎？沒關係，到了那邊就不用再思考了～",
            "⏳ 櫻花都已经落滿了白玉樓，你還沒選好呢...算了，幽幽子先去吃點心囉～"
        ]

        embed = discord.Embed(
            title="🪭 幽幽子的問答時間結束",
            description=(
                f"**題目**: {self.question}\n\n"
                f"{random.choice(timeout_messages)}\n\n"
                f"**正確答案**: `{self.correct_answer}`\n"
                f"**錯失獎勵**: `{self.reward:,}` 幽靈幣\n\n"
                f"*下次動作快一點，不要讓幽幽子等太久哦～*"
            ),
            color=discord.Color.dark_grey(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="幽靈的謎題只有 30 秒 · 猶豫就會敗北")

        for child in self.children:
            child.disabled = True

        # [Debug 修復] 加上 NotFound 保護，防止玩家刪除訊息導致崩潰
        try:
            if self.message:
                await self.message.edit(embed=embed, view=self)
            logger.info(f"⏰ 問答超時: {self.ctx.user.name} 未能在時間內作答")
        except discord.NotFound:
            logger.warning("⚠️ 問答訊息已被刪除，超時處理中止。")
        except Exception as e:
            logger.warning(f"⚠️ QuizView 超時編輯訊息失敗: {e}")


class QuizButton(discord.ui.Button):
    """問答按鈕，承載著幽幽子的惡趣味與獎勵"""

    def __init__(self, label, quiz_view):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.quiz_view = quiz_view
        self.is_correct = label == quiz_view.correct_answer

        # [靈魂優化] 幽幽子風格的答錯台詞：優雅的腹黑與天然黑
        self.wrong_messages = [
            "啊啦，選錯了呢。沒關係的，反正到了冥界之後，有的是時間慢慢學習...呵呵。",
            "呵呵，真是可愛的錯誤呢。要不要考慮直接住進白玉樓，讓我親自『教導』你？",
            "這個答案...妖夢看到了大概會忍不住拔刀的吧？呵呵，開玩笑的，她現在不在～",
            "答錯了呢。沒關係，西行妖下的土壤很肥沃，剛好需要一些靈魂來當肥料呢～🌸",
            "哎呀呀，你的靈魂似乎有點沉重呢。是不是裝了太多奇怪的東西，連思考都變慢了？",
            "呵呵，選得真好，完美避開了所有正確答案。這也是一種了不起的天賦呢～",
            "答錯囉。作為懲罰，把你的靈魂交給我吧...開玩笑的，幽幽子才不吃難吃的靈魂呢。",
            "真遺憾呢。不過別灰心，死後的世界還很漫長，你可以慢慢後悔這個選擇～"
        ]

        # [靈魂優化] 幽幽子風格的答對台詞：帶著讚許的捉弄
        self.correct_messages = [
            "哎呀，居然答對了？看來你的靈魂還挺有價值的，幽幽子捨不得把你當肥料了呢～🌸",
            "呵呵，真聰明呢。妖夢，快給這位客人準備剛做好的三色糰子～",
            "答對了呢。不過別太驕傲哦，在冥界，太聰明的人往往會看到不該看的東西呢...呵呵。",
            "真了不起～作為獎勵，幽幽子允許你請我吃大餐哦！",
            "呵呵，你的靈魂閃耀著智慧的光芒呢。要是能拿來當白玉樓的燈籠，一定很美吧？",
            "答對啦～嘻嘻，看來今天不用把你埋進西行妖的樹下了呢。"
        ]

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.quiz_view.ctx.author:
            return await interaction.response.send_message(
                "❌ 哎呀，這是給別人的謎題哦～不要搶答呢！", ephemeral=True
            )

        if self.quiz_view.answered:
            return await interaction.response.send_message(
                "⏳ 這題已經解開啦，幽靈不會重複問哦！", ephemeral=True
            )

        self.quiz_view.answered = True
        self.quiz_view.stop()

        for child in self.quiz_view.children:
            child.disabled = True
            if isinstance(child, discord.ui.Button):
                if child.label == self.quiz_view.correct_answer:
                    child.style = discord.ButtonStyle.success
                else:
                    child.style = discord.ButtonStyle.danger

        data_manager = getattr(self.quiz_view.ctx.bot, "data_manager", None)

        if self.is_correct:
            reward_amount = self.quiz_view.reward
            bonus_multiplier = random.uniform(1.0, 1.2)
            final_reward = int(reward_amount * bonus_multiplier)
            bonus_text = f" (含 {int((bonus_multiplier - 1) * 100)}% 加成)" if bonus_multiplier > 1.0 else ""

            if data_manager:
                guild_id = str(self.quiz_view.ctx.guild.id)
                user_id = str(interaction.user.id)

                async with data_manager.balance_lock:
                    if guild_id not in data_manager.balance:
                        data_manager.balance[guild_id] = {}
                    if user_id not in data_manager.balance[guild_id]:
                        data_manager.balance[guild_id][user_id] = 0

                    old_balance = data_manager.balance[guild_id][user_id]
                    data_manager.balance[guild_id][user_id] += final_reward
                    new_balance = data_manager.balance[guild_id][user_id]

                await data_manager.save_all_async()

                balance_info = (
                    f"\n\n💰 **獎勵發放**\n"
                    f"獲得: `+{final_reward:,}` 幽靈幣{bonus_text}\n"
                    f"餘額: `{old_balance:,}` → `{new_balance:,}` 幽靈幣"
                )
            else:
                balance_info = f"\n\n💰 **理論獎勵**: `{final_reward:,}` 幽靈幣（未連接數據庫）"

            description = (
                f"**題目**: {self.quiz_view.question}\n\n"
                f"✅ **{random.choice(self.correct_messages)}** 🎉\n\n"
                f"*你的靈魂在冥界閃耀著智慧之光～*"
                f"{balance_info}"
            )
            color = discord.Color.green()
            footer_text = "幽幽子的讚許 · 聰明的靈魂值得獎勵"
            logger.info(f"✅ {interaction.user.name} 答對題目，獲得 {final_reward:,} 幽靈幣")
        else:
            description = (
                f"**題目**: {self.quiz_view.question}\n\n"
                f"❌ **{random.choice(self.wrong_messages)}**\n\n"
                f"**正確答案**: `{self.quiz_view.correct_answer}`\n"
                f"**你的答案**: `{self.label}`\n\n"
                f"💔 **錯失獎勵**: `{self.quiz_view.reward:,}` 幽靈幣\n\n"
                f"*幽幽子建議你多讀點書再來挑戰哦～*"
            )
            color = discord.Color.red()
            footer_text = "幽幽子的嘲諷 · 錯誤的靈魂需要修煉"
            logger.info(f"❌ {interaction.user.name} 答錯題目（選擇: {self.label}）")

        embed = discord.Embed(
            title="🪭 幽幽子的問答結果",
            description=description,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=footer_text)

        # [Debug 修復] 加上 NotFound 保護
        try:
            await interaction.response.edit_message(embed=embed, view=self.quiz_view)
        except discord.NotFound:
            logger.warning("⚠️ 問答結果發送前，訊息已被刪除。")


class QuizCog(commands.Cog):
    """
    🌸 幽幽子的靈魂問答 🌸
    挑戰幽幽子的謎題，測試你的靈魂智慧～答對有獎勵，答錯被嘲諷
    """

    def __init__(self, bot):
        self.bot = bot
        logger.info("🌸 問答挑戰指令已甦醒")

        self.difficulty_rewards = {
            "easy":    (10,   50),
            "medium":  (70,   500),
            "hard":    (1000, 10000),
            "extreme": (6000, 700000)
        }

    @discord.slash_command(
        name="quiz",
        description="挑戰幽幽子的靈魂謎題～答對有獎勵，答錯會被嘲諷哦"
    )
    async def quiz(self, ctx: discord.ApplicationContext):
        data_manager = getattr(ctx.bot, "data_manager", None)
        
        # [Debug 修復] 加入在線備份攔截
        if data_manager and not await data_manager.check_backup_status(ctx, "quiz"):
            return
        
        if not await self.data_manager.check_economy_enabled(ctx, "quiz"):
            return

        try:
            if data_manager:
                # [Debug 修復] 使用 to_thread 包裝同步 I/O，避免阻塞 Event Loop
                quiz_data = await asyncio.to_thread(
                    data_manager._load_json, "config/quiz.json", []
                )
            else:
                logger.warning("⚠️ 未找到 data_manager，使用備用載入方式")
                import json
                quiz_data = await asyncio.to_thread(
                    lambda: json.load(open("config/quiz.json", "r", encoding="utf-8")) or []
                )
        except FileNotFoundError:
            logger.error("❌ quiz.json 檔案不存在")
            return await ctx.respond(
                embed=self._create_error_embed(
                    "題庫遺失",
                    "哎呀，題庫檔案消失了...就像幽靈一樣！\n請聯絡管理員確認 `config/quiz.json` 是否存在。"
                ),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"❌ 讀取 quiz.json 失敗: {e}")
            return await ctx.respond(
                embed=self._create_error_embed(
                    "題庫讀取失敗",
                    f"幽幽子在讀取題庫時遇到了障礙...\n錯誤: `{str(e)}`"
                ),
                ephemeral=True
            )

        if not quiz_data:
            logger.warning("⚠️ quiz.json 題庫為空")
            return await ctx.respond(
                embed=self._create_error_embed(
                    "題庫空空如也",
                    "哎呀，題庫空空的...就像幽幽子的肚子一樣！\n請管理員添加題目到 `config/quiz.json`。"
                ),
                ephemeral=True
            )

        question_data = random.choice(quiz_data)

        if "difficulty" not in question_data:
            question_data["difficulty"] = self._auto_detect_difficulty(question_data)

        if "reward" not in question_data:
            difficulty = question_data["difficulty"]
            reward_range = self.difficulty_rewards.get(difficulty, (70, 500))
            question_data["reward"] = random.randint(reward_range[0], reward_range[1])

        question = question_data.get("question", "")
        correct_answer = question_data.get("correct", "")
        incorrect_answers = question_data.get("incorrect", [])
        difficulty = question_data["difficulty"]
        reward = question_data["reward"]

        if not question or not correct_answer or len(incorrect_answers) != 3:
            logger.warning(f"⚠️ quiz.json 題目格式錯誤: {question_data}")
            return await ctx.respond(
                embed=self._create_error_embed(
                    "題目格式錯誤",
                    "這道題目的格式有問題呢...\n請檢查 `quiz.json` 格式是否正確:\n"
                    "```json\n{\n  \"question\": \"題目\",\n  \"correct\": \"正確答案\",\n  "
                    "\"incorrect\": [\"錯誤1\", \"錯誤2\", \"錯誤3\"],\n  "
                    "\"difficulty\": \"easy/medium/hard/extreme\",\n  \"reward\": 50\n}\n```"
                ),
                ephemeral=True
            )

        difficulty_display = {
            "easy":    "🟢 簡單",
            "medium":  "🟡 中等",
            "hard":    "🔴 困難",
            "extreme": "💀 超困難"
        }

        embed = discord.Embed(
            title="🪭 幽幽子的靈魂問答挑戰",
            description=(
                f"**{question}**\n\n"
                f"📊 **難度**: {difficulty_display.get(difficulty, '🟡 中等')}\n"
                f"💰 **獎勵**: `{reward:,}` 幽靈幣（答對可獲得獎勵加成!）\n\n"
                f"嘻嘻，這可不是簡單的謎題呢～\n"
                f"快選一個答案吧！答錯的話...呵呵呵..."
            ),
            color=discord.Color.from_rgb(255, 182, 193),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="⏰ 幽靈的謎題只有 30 秒 · 猶豫就會敗北")

        view = QuizView(ctx, question_data)
        
        await ctx.respond(embed=embed, view=view)
        
        # [Debug 修復] 使用 Pycord 最安全的 original_response() 獲取 Message 物件
        try:
            view.message = await ctx.interaction.original_response()
        except Exception as e:
            logger.warning(f"⚠️ QuizCog 設定 view.message 失敗: {e}")

        logger.info(f"📝 已為 {ctx.user.name} 出題 [{difficulty}]: {question}（獎勵: {reward:,}）")

    def _auto_detect_difficulty(self, question_data: dict) -> str:
        """根據題目內容自動判定難度"""
        question = question_data.get("question", "").lower()

        extreme_keywords = [
            "quantum", "qubit", "grover", "np-complete", "byzantine", "paxos",
            "zero-knowledge", "merkle", "cap 定理", "raft", "crdt", "lamport",
            "vector clock", "2pc", "bloom filter", "consistent hashing",
            "mapreduce", "gossip protocol", "chord dht", "clock tree synthesis",
            "amdahl", "量子", "分散式", "共識", "區塊鏈"
        ]

        hard_keywords = [
            "mosfet", "cmos", "ttl", "fpga", "ofdm", "mimo", "傅立葉",
            "麥克斯韋", "shannon", "rayleigh", "metastability", "jk 觸發器",
            "卡諾圖", "時序約束", "波導", "匹配網路", "setup time", "hold time",
            "clock skew", "verilog", "dynamic power"
        ]

        easy_keywords = [
            "cat", "apple", "thank you", "good morning", "bonjour",
            "hola", "danke", "arigato", "幽靈幣", "彩虹",
            "英語中的", "哪種語言的問候語", "是什麼意思"
        ]

        if any(keyword in question for keyword in extreme_keywords):
            return "extreme"
        if any(keyword in question for keyword in hard_keywords):
            return "hard"
        if any(keyword in question for keyword in easy_keywords):
            return "easy"
        return "medium"

    @staticmethod
    def _create_error_embed(title: str, description: str) -> discord.Embed:
        return discord.Embed(
            title=f"🌸 {title}",
            description=description,
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )


def setup(bot):
    bot.add_cog(QuizCog(bot))
    logger.info("✨ 問答挑戰 Cog 已載入完成")
