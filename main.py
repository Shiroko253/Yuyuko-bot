import os
import sys
import logging
import json
import yaml
import sqlite3
import copy  # [Debug 修復 #3] 引入 copy 模組用於深拷貝
from time import time
from pathlib import Path  # [Debug 修復 #1] 引入 pathlib 處理絕對路徑
from typing import Optional  # [Debug 修復 #2] 引入 Optional 相容 Python 3.9
from dotenv import load_dotenv
import discord
from discord.ext import commands
import asyncio

# ----------- 靈魂日誌的啟動 -----------
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(filename='logs/Sakura-error.log', encoding='utf-8', mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("SakuraBot")

# ----------- 建立專門的 Commands 錯誤日誌記錄器 -----------
commands_error_logger = logging.getLogger("SakuraBot.CommandsError")
commands_error_handler = logging.FileHandler(
    filename='logs/commands_error.log',
    encoding='utf-8',
    mode='a'
)
commands_error_handler.setFormatter(
    logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
)
commands_error_logger.addHandler(commands_error_handler)
commands_error_logger.setLevel(logging.ERROR)
commands_error_logger.propagate = False

# ----------- 喚醒幽幽子的密鑰 -----------
load_dotenv()

_raw_arg = sys.argv[1].lower() if len(sys.argv) > 1 else "main"
if _raw_arg not in ("main", "test"):
    logger.warning(f"未知的啟動參數 '{sys.argv[1]}'，已回退為 main 模式")
    RUN_MODE = "main"
else:
    RUN_MODE = _raw_arg

if RUN_MODE == "main":
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    token_name = "BOT_TOKEN"
    logger.info("🌸 幽幽子將以【正式模式】甦醒")
else:
    BOT_TOKEN = os.getenv("TEST_BOT_TOKEN")
    token_name = "TEST_BOT_TOKEN"
    logger.info("🌸 幽幽子將以【測試模式】甦醒")

if not BOT_TOKEN:
    logger.error(f"未找到靈魂密鑰 {token_name}，幽幽子無法甦醒")
    raise RuntimeError(f"Missing {token_name} in .env file")

# ----------- 設定靈魂的感知能力 -----------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = discord.Bot(intents=intents, auto_sync_commands=True)
bot.commands_error_logger = commands_error_logger

# ----------- 各資料檔案的預設值常數 -----------
BOT_STATUS_DEFAULT = {
    "last_event_time": None,
    "history": {}
}

# ----------- 冥界資料管理之靈魂核心 -----------
class SakuraDataManager:
    """管理幽幽子花園中的資料，猶如櫻瓣隨風飄舞"""

    def __init__(self):
        self.config_dir = "config"
        self.data_dir = "data"
        self.economy_dir = "economy"
        self.game_state_dir = os.path.join(self.data_dir, "game_state")
        self.bot_state_dir = os.path.join(self.data_dir, "bot_state")
        self.player_data_dir = os.path.join(self.data_dir, "player_data")

        for directory in [
            self.config_dir, self.data_dir, self.economy_dir,
            self.game_state_dir, self.bot_state_dir, self.player_data_dir
        ]:
            os.makedirs(directory, exist_ok=True)

        self.balance_lock: Optional[asyncio.Lock] = None
        self.save_lock: Optional[asyncio.Lock] = None
        self.is_backing_up = False

        # 1. Economy - Balance, Vault, Bank
        self._initialize_json(f"{self.economy_dir}/balance.json")
        self.balance = self._load_json(f"{self.economy_dir}/balance.json")

        self._initialize_json(f"{self.economy_dir}/server_vault.json")
        self.server_vault = self._load_json(f"{self.economy_dir}/server_vault.json")

        self._initialize_json(f"{self.economy_dir}/personal_bank.json")
        self.personal_bank = self._load_json(f"{self.economy_dir}/personal_bank.json")

        # 1.2 Economy - Credit (信譽系統)
        self._initialize_json(f"{self.economy_dir}/credit.json")
        self.credit = self._load_json(f"{self.economy_dir}/credit.json")

        # 2. Game State
        self._initialize_json(f"{self.game_state_dir}/blackjack.json")
        self._initialize_json(f"{self.game_state_dir}/invalid_bets.json")
        self.blackjack_data = self._load_json(f"{self.game_state_dir}/blackjack.json")
        self.invalid_bet_count = self._load_json(f"{self.game_state_dir}/invalid_bets.json")

        # 3. Bot State
        self._initialize_json(f"{self.bot_state_dir}/bot_status.json", BOT_STATUS_DEFAULT)
        self.bot_status = self._load_json(f"{self.bot_state_dir}/bot_status.json", BOT_STATUS_DEFAULT)

        # 4. Player Data
        self._initialize_json(f"{self.player_data_dir}/fishingbackpack.json")
        self.fishingbackpack = self._load_json(f"{self.player_data_dir}/fishingbackpack.json")

        self._initialize_yaml(f"{self.player_data_dir}/user_config.yml")
        self.user_config = self._load_yaml(f"{self.player_data_dir}/user_config.yml")

        # 5. Config
        self._initialize_json(f"{self.config_dir}/dm_messages.json")
        self.dm_messages = self._load_json(f"{self.config_dir}/dm_messages.json")

        # 6. Guild Config（伺服器經濟系統開關等）
        self._initialize_json(f"{self.data_dir}/guild_config.json")
        self.guild_config = self._load_json(f"{self.data_dir}/guild_config.json")

        self.black_hole_users = set()
        self._init_db()
        
        locations_path = f"{self.config_dir}/locations.json"
        self._initialize_json(locations_path, {
            "default_country": "US-California",
            "regions": {},
        })
        self.locations = self._load_json(locations_path, {
            "default_country": "US-California",
            "regions": {},
        })
        
    def get_default_country(self) -> str:
        return self.locations.get("default_country") or "US-California"

    def get_regions(self) -> dict:
        return self.locations.get("regions") or {}

    def get_region(self, country_key: str | None) -> tuple[str, dict]:
        regions = self.get_regions()
        key = country_key or self.get_default_country()
        region = regions.get(key)
        if not region:
            key = self.get_default_country()
            region = regions.get(key) or {"label": key, "group": "Other", "cities": []}
        return key, region

    def resolve_cities(self, country: str | None, city: str | None) -> list:
        """只讀記憶體，不修改 locations"""
        _, region = self.get_region(country)
        cities = list(region.get("cities") or [])
        if city:
            filtered = [c for c in cities if c.get("name", "").lower() == city.lower()]
            if filtered:
                return filtered
        return cities

    def regions_by_group(self) -> dict[str, list[tuple[str, dict]]]:
        """依 group 分組，供多個 Select 使用"""
        grouped: dict[str, list] = {}
        for key, region in self.get_regions().items():
            g = region.get("group") or "Other"
            grouped.setdefault(g, []).append((key, region))
        return grouped

    def setup_locks(self):
        self.balance_lock = asyncio.Lock()
        self.save_lock = asyncio.Lock()
        logger.info("asyncio.Lock 已在事件循環中初始化")

    async def check_backup_status(self, interaction: discord.Interaction, command_name: str) -> bool:
        if self.is_backing_up:
            await interaction.response.send_message(
                f"⚠️ 幽幽子正在進行數據備份，`/{command_name}` 暫時無法使用，請稍候再試哦～🌸",
                ephemeral=True
            )
            return False
        return True

    async def check_economy_enabled(self, ctx_or_interaction, command_name: str) -> bool:
        """檢查該伺服器是否啟用經濟系統。關閉則攔截並回覆。"""
        guild = getattr(ctx_or_interaction, "guild", None)
        if guild is None:
            msg = "🌸 幽靈幣系統只能在伺服器裡使用哦～"
            try:
                if hasattr(ctx_or_interaction, "respond"):
                    await ctx_or_interaction.respond(msg, ephemeral=True)
                elif hasattr(ctx_or_interaction, "response"):
                    if ctx_or_interaction.response.is_done():
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    else:
                        await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass
            return False

        guild_id = str(guild.id)
        enabled = self.guild_config.get(guild_id, {}).get("economy_enabled", True)

        if not enabled:
            msg = (
                f"🌸 這個伺服器的幽靈幣系統目前已關閉～\n"
                f"`/{command_name}` 暫時無法使用。\n"
                f"想重新開啟的話，請管理員使用 `/toggle_economy` 哦。"
            )
            try:
                if hasattr(ctx_or_interaction, "respond"):
                    await ctx_or_interaction.respond(msg, ephemeral=True)
                elif hasattr(ctx_or_interaction, "response"):
                    if ctx_or_interaction.response.is_done():
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    else:
                        await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass
            return False

        return True

    @staticmethod
    def _initialize_json(file_path: str, default: dict = None):
        if default is None:
            default = {}
        if not os.path.exists(file_path):
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(default, f, indent=4, ensure_ascii=False)
                logger.info(f"已創建 JSON 檔案：{file_path}")
            except Exception as e:
                logger.error(f"無法創建 JSON 檔案 {file_path}：{e}")

    @staticmethod
    def _initialize_yaml(file_path: str, default: dict = None):
        if default is None:
            default = {}
        if not os.path.exists(file_path):
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(default, f, allow_unicode=True)
                logger.info(f"已創建 YAML 檔案：{file_path}")
            except Exception as e:
                logger.error(f"無法創建 YAML 檔案 {file_path}：{e}")

    @staticmethod
    def _load_json(file_path: str, default: dict = None) -> dict:
        if default is None:
            default = {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if data is not None else default
        except Exception as e:
            logger.error(f"無法載入 JSON 檔案 {file_path}：{e}")
            return default

    @staticmethod
    def _save_json(file_path: str, data: dict):
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"無法保存 JSON 檔案 {file_path}：{e}")

    @staticmethod
    def _load_yaml(file_path: str, default: dict = None) -> dict:
        if default is None:
            default = {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or default
        except Exception as e:
            logger.error(f"無法載入 YAML 檔案 {file_path}：{e}")
            return default

    @staticmethod
    def _save_yaml(file_path: str, data: dict):
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True)
        except Exception as e:
            logger.error(f"無法保存 YAML 檔案 {file_path}：{e}")

    def _init_db(self):
        self.db_path = os.path.join(self.config_dir, "sakura_bot.db")
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''CREATE TABLE IF NOT EXISTS UserMessages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT,
                        message TEXT,
                        repeat_count INTEGER DEFAULT 0,
                        is_permanent BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )'''
                )
                cursor.execute(
                    '''CREATE TABLE IF NOT EXISTS BackgroundInfo (
                        user_id TEXT PRIMARY KEY,
                        info TEXT
                    )'''
                )
                conn.commit()
                logger.info("已初始化 SQLite 資料庫")
        except sqlite3.Error as e:
            logger.error(f"無法初始化資料庫：{e}")

    def _save_snapshot(self, snapshot: dict):
        self._save_json(f"{self.economy_dir}/balance.json", snapshot["balance"])
        self._save_json(f"{self.economy_dir}/server_vault.json", snapshot["server_vault"])
        self._save_json(f"{self.economy_dir}/personal_bank.json", snapshot["personal_bank"])
        self._save_json(f"{self.economy_dir}/credit.json", snapshot["credit"])
        self._save_json(f"{self.game_state_dir}/blackjack.json", snapshot["blackjack_data"])
        self._save_json(f"{self.game_state_dir}/invalid_bets.json", snapshot["invalid_bet_count"])
        self._save_json(f"{self.bot_state_dir}/bot_status.json", snapshot["bot_status"])
        self._save_json(f"{self.config_dir}/dm_messages.json", snapshot["dm_messages"])
        self._save_json(f"{self.player_data_dir}/fishingbackpack.json", snapshot["fishingbackpack"])
        self._save_yaml(f"{self.player_data_dir}/user_config.yml", snapshot["user_config"])
        self._save_json(f"{self.data_dir}/guild_config.json", snapshot["guild_config"])

    def save_all(self):
        self._save_snapshot({
            "balance": self.balance,
            "server_vault": self.server_vault,
            "personal_bank": self.personal_bank,
            "credit": self.credit,
            "blackjack_data": self.blackjack_data,
            "invalid_bet_count": self.invalid_bet_count,
            "bot_status": self.bot_status,
            "dm_messages": self.dm_messages,
            "fishingbackpack": self.fishingbackpack,
            "user_config": self.user_config,
            "guild_config": self.guild_config,
        })

    async def save_all_async(self):
        if self.save_lock is None:
            logger.warning("save_lock 尚未初始化，直接同步保存")
            self.save_all()
            return

        async with self.save_lock:
            snapshot = {
                "balance": copy.deepcopy(self.balance),
                "server_vault": copy.deepcopy(self.server_vault),
                "personal_bank": copy.deepcopy(self.personal_bank),
                "credit": copy.deepcopy(self.credit),
                "blackjack_data": copy.deepcopy(self.blackjack_data),
                "invalid_bet_count": copy.deepcopy(self.invalid_bet_count),
                "bot_status": copy.deepcopy(self.bot_status),
                "dm_messages": copy.deepcopy(self.dm_messages),
                "fishingbackpack": copy.deepcopy(self.fishingbackpack),
                "user_config": copy.deepcopy(self.user_config),
                "guild_config": copy.deepcopy(self.guild_config),
            }
        await asyncio.to_thread(self._save_snapshot, snapshot)
        logger.info("數據已安全保存")


# ----------- 幽幽子的靈魂啟動 -----------
bot.data_manager = SakuraDataManager()
bot.start_time = time()
bot.last_activity_time = bot.start_time
bot.run_mode = RUN_MODE

# ----------- 載入指令與事件的花瓣 -----------
BASE_DIR = Path(__file__).parent.resolve()
CRITICAL_EXTENSIONS = {
    # "commands.economy",
}
load_errors = []

for folder_name in ['commands', 'events']:
    folder_path = BASE_DIR / folder_name
    if not folder_path.exists():
        logger.warning(f"未找到花園路徑 {folder_path}，略過載入")
        continue

    for file_path in folder_path.rglob('*.py'):
        if file_path.name == '__init__.py':
            continue

        relative_path = file_path.relative_to(BASE_DIR)
        extension_name = str(relative_path).replace(os.sep, '.')[:-3]

        try:
            bot.load_extension(extension_name)
            logger.info(f"已載入花瓣模組：{extension_name}")
        except Exception as e:
            logger.error(f"無法載入模組 {extension_name}：{e}", exc_info=True)
            if extension_name in CRITICAL_EXTENSIONS:
                load_errors.append(extension_name)

if load_errors:
    logger.critical(f"以下必要模組載入失敗，幽幽子拒絕以殘缺狀態甦醒：{load_errors}")
    sys.exit(1)

# ----------- 喚醒幽幽子，步入 Discord 世界 -----------
try:
    bot.run(BOT_TOKEN)
except KeyboardInterrupt:
    logger.info("幽幽子正在優雅地離去... (KeyboardInterrupt)")
except Exception as e:
    logger.critical(f"幽幽子遭遇致命錯誤：{e}", exp_info=True)
finally:
    logger.info("正在封存所有記憶...")
    bot.data_manager.save_all()
    logger.info("靈魂已歸於寂靜")
