from __future__ import annotations

import os
import asyncio
import random
import sqlite3
import traceback
import time
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable, Any

import discord
from discord import app_commands
from discord.ext import commands


# ============================================================
# CONFIG
# ============================================================

MAX_BOTS = 5

BOT_ENV_NAMES = [
    "BOT_TOKEN_1",
    "BOT_TOKEN_2",
    "BOT_TOKEN_3",
    "BOT_TOKEN_4",
    "BOT_TOKEN_5",
]

DEFAULT_NAMES = [
    "MyAI-1",
    "MyAI-2",
    "MyAI-3",
    "MyAI-4",
    "MyAI-5",
]

VALID_MODES = {
    "round_robin",
    "random",
    "leader",
}

VALID_REPLY_MODES = {
    "reply",
    "channel",
}

MAX_USERNAME_LENGTH = 32
MAX_AI_RESPONSE_LENGTH = 2000

DEFAULT_POWER = 50
DEFAULT_PARTICIPATION = 100

DEFAULT_MAX_TURNS = 5
DEFAULT_COOLDOWN = 5.0
DEFAULT_ROUND_DELAY = 0.0

# ============================================================
# NEW CHAT TIMING
# ============================================================

# أول بوت يبدأ مباشرة.
# البوتات التالية تنتظر 3 ثواني لقراءة رد البوت السابق.
BOT_READ_DELAY = 3.0

# وقت انتظار التوليد قبل إرسال الرد.
BOT_GENERATION_DELAY = 2.0

# مدة الدردشة الافتراضية: ساعة واحدة.
DEFAULT_CHAT_DURATION = 60 * 60

# الحد الأقصى: 12 ساعة.
MAX_CHAT_DURATION = 12 * 60 * 60

# الحد الأدنى: دقيقة واحدة.
MIN_CHAT_DURATION = 60


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class GroupBotConfig:
    guild_id: int
    slot: int
    name: str
    power: int = DEFAULT_POWER
    personality: str = ""
    speaking_style: str = ""
    participation: int = DEFAULT_PARTICIPATION
    memory: bool = True
    reply_mode: str = "reply"
    enabled: bool = True


@dataclass
class GroupSettings:
    guild_id: int
    enabled: bool = False
    channel_id: Optional[int] = None
    mode: str = "round_robin"
    max_turns: int = DEFAULT_MAX_TURNS
    cooldown: float = DEFAULT_COOLDOWN
    round_delay: float = DEFAULT_ROUND_DELAY
    leader_slot: int = 1

    # NEW
    chat_duration: int = DEFAULT_CHAT_DURATION


# ============================================================
# DATABASE
# ============================================================

class AIGroupDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._setup()

    def _connect(self):
        conn = sqlite3.connect(
            self.db_path,
            timeout=30,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row

        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
        except Exception:
            pass

        return conn

    def _column_exists(self, conn, table: str, column: str) -> bool:
        rows = conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()

        return any(row["name"] == column for row in rows)

    def _setup(self):
        conn = self._connect()

        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_group_settings (
                    guild_id INTEGER PRIMARY KEY,
                    enabled INTEGER DEFAULT 0,
                    channel_id INTEGER,
                    mode TEXT DEFAULT 'round_robin',
                    max_turns INTEGER DEFAULT 5,
                    cooldown REAL DEFAULT 5.0,
                    round_delay REAL DEFAULT 0.0,
                    leader_slot INTEGER DEFAULT 1,
                    chat_duration INTEGER DEFAULT 3600
                )
                """
            )

            # ------------------------------------------------
            # SETTINGS MIGRATION
            # ------------------------------------------------

            if not self._column_exists(
                conn,
                "ai_group_settings",
                "chat_duration",
            ):
                conn.execute(
                    """
                    ALTER TABLE ai_group_settings
                    ADD COLUMN chat_duration INTEGER DEFAULT 3600
                    """
                )

                print(
                    "[AI_GROUP][DB] Added chat_duration column."
                )

            conn.execute(
                """
                UPDATE ai_group_settings
                SET chat_duration = ?
                WHERE chat_duration IS NULL
                   OR chat_duration <= 0
                """,
                (DEFAULT_CHAT_DURATION,),
            )

            # ------------------------------------------------
            # BOTS
            # ------------------------------------------------

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_group_bots (
                    guild_id INTEGER NOT NULL,
                    slot INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    power INTEGER DEFAULT 50,
                    personality TEXT DEFAULT '',
                    speaking_style TEXT DEFAULT '',
                    participation INTEGER DEFAULT 100,
                    memory INTEGER DEFAULT 1,
                    reply_mode TEXT DEFAULT 'reply',
                    enabled INTEGER DEFAULT 1,
                    PRIMARY KEY(guild_id, slot)
                )
                """
            )

            # Bot migrations
            bot_columns = [
                ("power", "INTEGER DEFAULT 50"),
                ("personality", "TEXT DEFAULT ''"),
                ("speaking_style", "TEXT DEFAULT ''"),
                ("participation", "INTEGER DEFAULT 100"),
                ("memory", "INTEGER DEFAULT 1"),
                ("reply_mode", "TEXT DEFAULT 'reply'"),
                ("enabled", "INTEGER DEFAULT 1"),
            ]

            for column, definition in bot_columns:
                if not self._column_exists(
                    conn,
                    "ai_group_bots",
                    column,
                ):
                    conn.execute(
                        f"""
                        ALTER TABLE ai_group_bots
                        ADD COLUMN {column} {definition}
                        """
                    )

            # ------------------------------------------------
            # STATS
            # ------------------------------------------------

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_group_stats (
                    guild_id INTEGER NOT NULL,
                    slot INTEGER NOT NULL,
                    messages INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    PRIMARY KEY(guild_id, slot)
                )
                """
            )

            conn.commit()

            print("[AI_GROUP][DB] Database ready.")

        finally:
            conn.close()

    # ========================================================
    # SETTINGS
    # ========================================================

    def get_settings(self, guild_id: int) -> GroupSettings:
        conn = self._connect()

        try:
            row = conn.execute(
                """
                SELECT *
                FROM ai_group_settings
                WHERE guild_id = ?
                """,
                (guild_id,),
            ).fetchone()

            if row is None:
                return GroupSettings(guild_id=guild_id)

            duration = row["chat_duration"]

            if duration is None:
                duration = DEFAULT_CHAT_DURATION

            duration = int(duration)

            duration = max(
                MIN_CHAT_DURATION,
                min(MAX_CHAT_DURATION, duration),
            )

            return GroupSettings(
                guild_id=guild_id,
                enabled=bool(row["enabled"]),
                channel_id=row["channel_id"],
                mode=row["mode"] or "round_robin",
                max_turns=max(
                    1,
                    min(100, int(row["max_turns"] or DEFAULT_MAX_TURNS)),
                ),
                cooldown=max(
                    0.0,
                    float(row["cooldown"] or DEFAULT_COOLDOWN),
                ),
                round_delay=max(
                    0.0,
                    float(row["round_delay"] or DEFAULT_ROUND_DELAY),
                ),
                leader_slot=max(
                    1,
                    min(MAX_BOTS, int(row["leader_slot"] or 1)),
                ),
                chat_duration=duration,
            )

        finally:
            conn.close()

    def save_settings(self, settings: GroupSettings):
        duration = max(
            MIN_CHAT_DURATION,
            min(
                MAX_CHAT_DURATION,
                int(settings.chat_duration),
            ),
        )

        mode = (
            settings.mode
            if settings.mode in VALID_MODES
            else "round_robin"
        )

        conn = self._connect()

        try:
            conn.execute(
                """
                INSERT INTO ai_group_settings (
                    guild_id,
                    enabled,
                    channel_id,
                    mode,
                    max_turns,
                    cooldown,
                    round_delay,
                    leader_slot,
                    chat_duration
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id)
                DO UPDATE SET
                    enabled = excluded.enabled,
                    channel_id = excluded.channel_id,
                    mode = excluded.mode,
                    max_turns = excluded.max_turns,
                    cooldown = excluded.cooldown,
                    round_delay = excluded.round_delay,
                    leader_slot = excluded.leader_slot,
                    chat_duration = excluded.chat_duration
                """,
                (
                    settings.guild_id,
                    int(settings.enabled),
                    settings.channel_id,
                    mode,
                    max(1, min(100, int(settings.max_turns))),
                    max(0.0, float(settings.cooldown)),
                    max(0.0, float(settings.round_delay)),
                    max(1, min(MAX_BOTS, int(settings.leader_slot))),
                    duration,
                ),
            )

            conn.commit()

        finally:
            conn.close()

    # ========================================================
    # BOT CONFIG
    # ========================================================

    def get_bot(
        self,
        guild_id: int,
        slot: int,
    ) -> GroupBotConfig:
        conn = self._connect()

        try:
            row = conn.execute(
                """
                SELECT *
                FROM ai_group_bots
                WHERE guild_id = ?
                  AND slot = ?
                """,
                (guild_id, slot),
            ).fetchone()

            if row is None:
                return GroupBotConfig(
                    guild_id=guild_id,
                    slot=slot,
                    name=DEFAULT_NAMES[slot - 1],
                )

            return GroupBotConfig(
                guild_id=guild_id,
                slot=slot,
                name=row["name"] or DEFAULT_NAMES[slot - 1],
                power=max(
                    1,
                    min(100, int(row["power"] or DEFAULT_POWER)),
                ),
                personality=row["personality"] or "",
                speaking_style=row["speaking_style"] or "",
                participation=max(
                    0,
                    min(
                        100,
                        int(
                            row["participation"]
                            if row["participation"] is not None
                            else DEFAULT_PARTICIPATION
                        ),
                    ),
                ),
                memory=bool(row["memory"]),
                reply_mode=(
                    row["reply_mode"]
                    if row["reply_mode"] in VALID_REPLY_MODES
                    else "reply"
                ),
                enabled=bool(row["enabled"]),
            )

        finally:
            conn.close()

    def save_bot(self, bot: GroupBotConfig):
        name = (
            bot.name.strip()
            or DEFAULT_NAMES[bot.slot - 1]
        )

        name = name[:MAX_USERNAME_LENGTH]

        conn = self._connect()

        try:
            conn.execute(
                """
                INSERT INTO ai_group_bots (
                    guild_id,
                    slot,
                    name,
                    power,
                    personality,
                    speaking_style,
                    participation,
                    memory,
                    reply_mode,
                    enabled
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, slot)
                DO UPDATE SET
                    name = excluded.name,
                    power = excluded.power,
                    personality = excluded.personality,
                    speaking_style = excluded.speaking_style,
                    participation = excluded.participation,
                    memory = excluded.memory,
                    reply_mode = excluded.reply_mode,
                    enabled = excluded.enabled
                """,
                (
                    bot.guild_id,
                    bot.slot,
                    name,
                    max(1, min(100, int(bot.power))),
                    bot.personality,
                    bot.speaking_style,
                    max(
                        0,
                        min(100, int(bot.participation)),
                    ),
                    int(bot.memory),
                    (
                        bot.reply_mode
                        if bot.reply_mode in VALID_REPLY_MODES
                        else "reply"
                    ),
                    int(bot.enabled),
                ),
            )

            conn.commit()

        finally:
            conn.close()

    # ========================================================
    # STATS
    # ========================================================

    def add_message_stat(
        self,
        guild_id: int,
        slot: int,
    ):
        conn = self._connect()

        try:
            conn.execute(
                """
                INSERT INTO ai_group_stats (
                    guild_id,
                    slot,
                    messages,
                    errors
                )
                VALUES (?, ?, 1, 0)
                ON CONFLICT(guild_id, slot)
                DO UPDATE SET
                    messages = messages + 1
                """,
                (guild_id, slot),
            )

            conn.commit()

        finally:
            conn.close()

    def add_error_stat(
        self,
        guild_id: int,
        slot: int,
    ):
        conn = self._connect()

        try:
            conn.execute(
                """
                INSERT INTO ai_group_stats (
                    guild_id,
                    slot,
                    messages,
                    errors
                )
                VALUES (?, ?, 0, 1)
                ON CONFLICT(guild_id, slot)
                DO UPDATE SET
                    errors = errors + 1
                """,
                (guild_id, slot),
            )

            conn.commit()

        finally:
            conn.close()

    def get_stats(
        self,
        guild_id: int,
        slot: int,
    ):
        conn = self._connect()

        try:
            row = conn.execute(
                """
                SELECT messages, errors
                FROM ai_group_stats
                WHERE guild_id = ?
                  AND slot = ?
                """,
                (guild_id, slot),
            ).fetchone()

            if row is None:
                return {
                    "messages": 0,
                    "errors": 0,
                }

            return {
                "messages": int(row["messages"] or 0),
                "errors": int(row["errors"] or 0),
            }

        finally:
            conn.close()


# ============================================================
# SECONDARY BOT CLIENT
# ============================================================

class SecondaryBotClient(discord.Client):

    def __init__(
        self,
        manager,
        slot: int,
    ):
        intents = discord.Intents.default()

        # مهم:
        # لا نريد البوتات الثانوية معالجة الرسائل
        # حتى لا تدخل في loop لا نهائي.
        intents.message_content = False
        intents.messages = True
        intents.guilds = True

        super().__init__(intents=intents)

        self.manager = manager
        self.slot = slot

    async def on_ready(self):
        self.manager.online[self.slot] = True
        self.manager.ready_events[self.slot].set()

        username = (
            str(self.user)
            if self.user
            else "Unknown"
        )

        print(
            f"[AI_GROUP] Bot {self.slot} ONLINE as {username}"
        )

    async def on_disconnect(self):
        self.manager.online[self.slot] = False


# ============================================================
# AI GROUP MANAGER
# ============================================================

class AIGroupManager:

    def __init__(
        self,
        main_bot: commands.Bot,
        db_path: str,
        ai_generate: Callable[..., Awaitable[str]],
    ):
        self.main_bot = main_bot

        self.db = AIGroupDB(db_path)

        self.ai_generate = ai_generate

        self.clients: dict[int, SecondaryBotClient] = {}
        self.tasks: dict[int, asyncio.Task] = {}

        self.online: dict[int, bool] = {
            slot: False
            for slot in range(1, MAX_BOTS + 1)
        }

        self.ready_events: dict[int, asyncio.Event] = {
            slot: asyncio.Event()
            for slot in range(1, MAX_BOTS + 1)
        }

        self.locks: dict[int, asyncio.Lock] = {}

        self.cooldown_until: dict[int, float] = {}

        self.group_tasks: dict[int, asyncio.Task] = {}

        self.round_robin: dict[int, int] = {}

        self.shutdown_flag = False

    # ========================================================
    # HELPERS
    # ========================================================

    def get_token(self, slot: int) -> Optional[str]:
        if not 1 <= slot <= MAX_BOTS:
            return None

        token = os.getenv(
            BOT_ENV_NAMES[slot - 1]
        )

        if not token:
            return None

        return token.strip()

    def configured_count(self) -> int:
        count = 0

        for slot in range(1, MAX_BOTS + 1):
            if self.get_token(slot):
                count += 1

        return count

    def ready_count(self) -> int:
        return sum(
            1
            for slot in range(1, MAX_BOTS + 1)
            if self.online.get(slot, False)
        )

    def get_lock(self, guild_id: int) -> asyncio.Lock:
        lock = self.locks.get(guild_id)

        if lock is None:
            lock = asyncio.Lock()
            self.locks[guild_id] = lock

        return lock

    def get_client(
        self,
        slot: int,
    ) -> Optional[SecondaryBotClient]:
        return self.clients.get(slot)

    # ========================================================
    # START CLIENTS
    # ========================================================

    async def start_clients(self):
        self.shutdown_flag = False

        for slot in range(1, MAX_BOTS + 1):
            token = self.get_token(slot)

            if not token:
                print(
                    f"[AI_GROUP] Bot {slot} skipped: "
                    f"{BOT_ENV_NAMES[slot - 1]} is missing."
                )
                continue

            client = SecondaryBotClient(
                manager=self,
                slot=slot,
            )

            self.clients[slot] = client

            task = asyncio.create_task(
                self._run_client(
                    slot,
                    token,
                    client,
                )
            )

            self.tasks[slot] = task

    async def _run_client(
        self,
        slot: int,
        token: str,
        client: SecondaryBotClient,
    ):
        try:
            await client.start(token)

        except discord.LoginFailure as exc:
            self.online[slot] = False

            print(
                f"[AI_GROUP] Bot {slot} failed: "
                f"LoginFailure: {exc}"
            )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            self.online[slot] = False

            print(
                f"[AI_GROUP] Bot {slot} failed: "
                f"{type(exc).__name__}: {exc}"
            )

            traceback.print_exc()

    # ========================================================
    # COMMAND REGISTRATION
    # ========================================================

    async def register_command(
        self,
        tree: app_commands.CommandTree,
    ):
        async def callback(
            interaction: discord.Interaction,
        ):
            await self.show_dashboard(interaction)

        command = app_commands.Command(
            name="ai_group",
            description="إدارة مجموعة البوتات الذكية",
            callback=callback,
        )

        tree.add_command(command)

    # ========================================================
    # DASHBOARD
    # ========================================================

    async def show_dashboard(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ هذا الأمر داخل السيرفر فقط.",
                ephemeral=True,
            )
            return

        settings = self.db.get_settings(
            interaction.guild.id
        )

        embed = self.build_dashboard_embed(
            interaction.guild,
            settings,
        )

        view = GroupDashboardView(
            self,
            interaction.guild.id,
        )

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
        )

    def build_dashboard_embed(
        self,
        guild: discord.Guild,
        settings: GroupSettings,
    ):
        duration_text = self.format_duration(
            settings.chat_duration
        )

        channel_text = (
            f"<#{settings.channel_id}>"
            if settings.channel_id
            else "غير محدد"
        )

        status = (
            "🟢 مفعّل"
            if settings.enabled
            else "🔴 متوقف"
        )

        mode_names = {
            "round_robin": "🔄 Round Robin",
            "random": "🎲 Random",
            "leader": "👑 Leader",
        }

        embed = discord.Embed(
            title="🤖 AI Group",
            description=(
                "لوحة التحكم بمجموعة البوتات الذكية."
            ),
        )

        embed.add_field(
            name="الحالة",
            value=status,
            inline=True,
        )

        embed.add_field(
            name="الروم",
            value=channel_text,
            inline=True,
        )

        embed.add_field(
            name="النمط",
            value=mode_names.get(
                settings.mode,
                settings.mode,
            ),
            inline=True,
        )

        embed.add_field(
            name="⏱️ مدة الدردشة",
            value=(
                f"**{duration_text}**\n"
                "الحد الأقصى: **12 ساعة**"
            ),
            inline=False,
        )

        embed.add_field(
            name="⚡ سرعة الرد",
            value=(
                "البوت الأول: **مباشرة**\n"
                "البوت التالي: **3 ثواني قراءة**\n"
                "+ **2 ثانية توليد**"
            ),
            inline=False,
        )

        embed.add_field(
            name="🔁 الحد الأقصى للجولات",
            value=str(settings.max_turns),
            inline=True,
        )

        embed.add_field(
            name="⏳ Cooldown",
            value=f"{settings.cooldown:g}s",
            inline=True,
        )

        embed.add_field(
            name="🤖 البوتات",
            value=(
                f"متصلة: **{self.ready_count()}/5**\n"
                f"مكوّنة: **{self.configured_count()}/5**"
            ),
            inline=True,
        )

        return embed

    # ========================================================
    # REAL USERNAME
    # ========================================================

    async def change_real_username(
        self,
        slot: int,
        new_name: str,
    ) -> tuple[bool, str]:
        client = self.clients.get(slot)

        if client is None:
            return (
                False,
                "❌ البوت غير متصل.",
            )

        if client.user is None:
            return (
                False,
                "❌ بيانات البوت غير جاهزة.",
            )

        new_name = new_name.strip()

        if not new_name:
            return (
                False,
                "❌ الاسم فارغ.",
            )

        new_name = new_name[:MAX_USERNAME_LENGTH]

        try:
            await client.user.edit(
                username=new_name
            )

            return (
                True,
                f"✅ تم تغيير اسم البوت فعليًا إلى **{new_name}**.",
            )

        except discord.HTTPException as exc:
            return (
                False,
                f"❌ تعذر تغيير الاسم: {exc}",
            )

        except Exception as exc:
            return (
                False,
                f"❌ خطأ: {exc}",
            )

    # ========================================================
    # SETTINGS
    # ========================================================

    async def set_enabled(
        self,
        guild_id: int,
        enabled: bool,
    ):
        settings = self.db.get_settings(guild_id)
        settings.enabled = enabled

        self.db.save_settings(settings)

    async def set_channel(
        self,
        guild_id: int,
        channel_id: Optional[int],
    ):
        settings = self.db.get_settings(guild_id)
        settings.channel_id = channel_id

        self.db.save_settings(settings)

    async def set_mode(
        self,
        guild_id: int,
        mode: str,
    ):
        if mode not in VALID_MODES:
            mode = "round_robin"

        settings = self.db.get_settings(guild_id)
        settings.mode = mode

        self.db.save_settings(settings)

    async def set_chat_duration(
        self,
        guild_id: int,
        seconds: int,
    ) -> tuple[bool, str]:
        try:
            seconds = int(seconds)
        except Exception:
            return (
                False,
                "❌ المدة يجب أن تكون رقمًا.",
            )

        if seconds < MIN_CHAT_DURATION:
            return (
                False,
                "❌ أقل مدة مسموحة هي **دقيقة واحدة**.",
            )

        if seconds > MAX_CHAT_DURATION:
            return (
                False,
                "❌ أقصى مدة للدردشة هي **12 ساعة**.",
            )

        settings = self.db.get_settings(guild_id)

        settings.chat_duration = seconds

        self.db.save_settings(settings)

        return (
            True,
            "✅ تم حفظ مدة الدردشة: "
            f"**{self.format_duration(seconds)}**",
        )

    # ========================================================
    # MESSAGE HANDLER
    # ========================================================

    async def handle_message(
        self,
        message: discord.Message,
    ) -> bool:
        if message.guild is None:
            return False

        if message.author.bot:
            return False

        guild_id = message.guild.id

        settings = self.db.get_settings(
            guild_id
        )

        if not settings.enabled:
            return False

        if settings.channel_id is None:
            return False

        if message.channel.id != settings.channel_id:
            return False

        now = time.monotonic()

        cooldown_until = self.cooldown_until.get(
            guild_id,
            0.0,
        )

        if now < cooldown_until:
            return False

        self.cooldown_until[guild_id] = (
            now + settings.cooldown
        )

        existing = self.group_tasks.get(
            guild_id
        )

        if existing and not existing.done():
            return True

        task = asyncio.create_task(
            self._safe_run_group(message)
        )

        self.group_tasks[guild_id] = task

        return True

    async def _safe_run_group(
        self,
        message: discord.Message,
    ):
        guild_id = message.guild.id

        try:
            async with self.get_lock(guild_id):
                await self.run_group(message)

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                "[AI_GROUP] Group generation error: "
                f"{type(exc).__name__}: {exc}"
            )

            traceback.print_exc()

    # ========================================================
    # RUN GROUP
    # ========================================================

    async def run_group(
        self,
        message: discord.Message,
    ):
        guild_id = message.guild.id

        settings = self.db.get_settings(
            guild_id
        )

        if not settings.enabled:
            return

        session_started = time.monotonic()

        session_deadline = (
            session_started
            + settings.chat_duration
        )

        candidates = []

        for slot in range(1, MAX_BOTS + 1):
            cfg = self.db.get_bot(
                guild_id,
                slot,
            )

            if not cfg.enabled:
                continue

            if cfg.participation <= 0:
                continue

            if not self.online.get(
                slot,
                False,
            ):
                continue

            # participation
            if cfg.participation < 100:
                roll = random.randint(
                    1,
                    100,
                )

                if roll > cfg.participation:
                    continue

            candidates.append(cfg)

        if not candidates:
            print(
                "[AI_GROUP] No available secondary bots."
            )
            return

        # ----------------------------------------------------
        # ORDER
        # ----------------------------------------------------

        if settings.mode == "random":
            random.shuffle(candidates)

        elif settings.mode == "leader":
            leader = None
            others = []

            for cfg in candidates:
                if cfg.slot == settings.leader_slot:
                    leader = cfg
                else:
                    others.append(cfg)

            if leader is not None:
                candidates = [
                    leader,
                    *others,
                ]
            else:
                candidates = others

        else:
            # round robin
            start = self.round_robin.get(
                guild_id,
                0,
            )

            if candidates:
                start %= len(candidates)

                candidates = (
                    candidates[start:]
                    + candidates[:start]
                )

                self.round_robin[guild_id] = (
                    (start + 1)
                    % len(candidates)
                )

        conversation = (
            message.content
            or "(رسالة فارغة)"
        )

        previous_message: Optional[
            discord.Message
        ] = None

        turns = 0

        # ----------------------------------------------------
        # CHAT LOOP
        # ----------------------------------------------------

        while (
            turns < settings.max_turns
            and candidates
        ):
            # ------------------------------------------------
            # 12 HOUR SESSION LIMIT
            # ------------------------------------------------

            if time.monotonic() >= session_deadline:
                print(
                    f"[AI_GROUP] Chat session expired "
                    f"for guild {guild_id}."
                )
                break

            for cfg in candidates:

                # --------------------------------------------
                # Check session time before each bot
                # --------------------------------------------

                if time.monotonic() >= session_deadline:
                    print(
                        "[AI_GROUP] Chat duration reached."
                    )
                    return

                # --------------------------------------------
                # FIRST BOT
                # --------------------------------------------

                if previous_message is None:
                    # أول بوت يبدأ مباشرة.
                    pass

                else:
                    # ----------------------------------------
                    # 3 SECONDS READING DELAY
                    # ----------------------------------------

                    remaining = (
                        session_deadline
                        - time.monotonic()
                    )

                    if remaining <= 0:
                        return

                    await asyncio.sleep(
                        min(
                            BOT_READ_DELAY,
                            remaining,
                        )
                    )

                    if (
                        time.monotonic()
                        >= session_deadline
                    ):
                        return

                # --------------------------------------------
                # BUILD PROMPT
                # --------------------------------------------

                prompt = (
                    "رسالة المستخدم الأصلية:\n"
                    f"{message.content}\n\n"
                    "سياق المحادثة بين أعضاء المجموعة:\n"
                    f"{conversation}\n\n"
                    "اكتب ردك الطبيعي الآن."
                )

                # --------------------------------------------
                # GENERATION
                # --------------------------------------------

                remaining = (
                    session_deadline
                    - time.monotonic()
                )

                if remaining <= 0:
                    return

                try:
                    result = await self.generate_for_bot(
                        message=message,
                        cfg=cfg,
                        prompt=prompt,
                        generation_time_limit=remaining,
                    )

                except Exception as exc:
                    self.db.add_error_stat(
                        guild_id,
                        cfg.slot,
                    )

                    print(
                        f"[AI_GROUP] Bot {cfg.slot} "
                        "generation error: "
                        f"{type(exc).__name__}: {exc}"
                    )

                    continue

                if not result:
                    continue

                # --------------------------------------------
                # SEND
                # --------------------------------------------

                try:
                    sent = await self.send_bot_message(
                        message=message,
                        cfg=cfg,
                        text=result,
                        previous_message=previous_message,
                    )

                    if sent is None:
                        self.db.add_error_stat(
                            guild_id,
                            cfg.slot,
                        )
                        continue

                except Exception as exc:
                    self.db.add_error_stat(
                        guild_id,
                        cfg.slot,
                    )

                    print(
                        f"[AI_GROUP] Bot {cfg.slot} "
                        "send error: "
                        f"{type(exc).__name__}: {exc}"
                    )

                    continue

                # --------------------------------------------
                # SUCCESS
                # --------------------------------------------

                self.db.add_message_stat(
                    guild_id,
                    cfg.slot,
                )

                conversation += (
                    f"\n\n{cfg.name}: {result}"
                )

                previous_message = sent

                turns += 1

                if turns >= settings.max_turns:
                    break

                # --------------------------------------------
                # OPTIONAL EXTRA ROUND DELAY
                # --------------------------------------------

                # افتراضيًا 0 ثانية حتى لا يكون هناك
                # تأخير إضافي فوق 3 + 2.
                if settings.round_delay > 0:
                    remaining = (
                        session_deadline
                        - time.monotonic()
                    )

                    if remaining <= 0:
                        return

                    await asyncio.sleep(
                        min(
                            settings.round_delay,
                            remaining,
                        )
                    )

            # end for

        # end while

    # ========================================================
    # GENERATE
    # ========================================================

    async def generate_for_bot(
        self,
        message: discord.Message,
        cfg: GroupBotConfig,
        prompt: str,
        generation_time_limit: float,
    ) -> str:
        personality = (
            cfg.personality.strip()
            or "ودود، ذكي، طبيعي."
        )

        speaking_style = (
            cfg.speaking_style.strip()
            or "تكلم بشكل طبيعي ومختصر."
        )

        system_context = (
            f"أنت {cfg.name}، عضو رقم {cfg.slot} "
            "في مجموعة AI.\n"
            f"قوة شخصيتك: {cfg.power}/100.\n"
            f"شخصيتك: {personality}\n"
            f"أسلوب كلامك: {speaking_style}\n"
            "\n"
            "أنت عضو في مجموعة من البوتات."
            " لا تدّعي أنك البوت الرئيسي."
            " لا تكرر كلام الأعضاء بلا سبب."
            " تابع سياق الحوار ورد بشكل طبيعي."
        )

        final_prompt = (
            system_context
            + "\n\n"
            + prompt
        )

        # ----------------------------------------------------
        # GENERATION DELAY
        # ----------------------------------------------------
        #
        # هذا هو وقت التوليد المحدد:
        # 2 ثانية.
        #
        # ملاحظة:
        # هذا delay وليس إجبارًا على أن API نفسها تنتهي
        # خلال ثانيتين.
        #
        # إذا انتهى API قبلها نكمل بقية الثانية.
        # وإذا API استغرق أكثر، ننتظر نتيجته حتى timeout
        # الخاص بالمحرك.
        # ----------------------------------------------------

        generation_started = time.monotonic()

        result = await asyncio.wait_for(
            self.ai_generate(
                guild_id=message.guild.id,
                slot=cfg.slot,
                user_id=message.author.id,
                channel_id=message.channel.id,
                prompt=final_prompt,
                bot_name=cfg.name,
                personality=personality,
                speaking_style=speaking_style,
                power=cfg.power,
            ),
            timeout=max(
                1.0,
                generation_time_limit,
            ),
        )

        # ----------------------------------------------------
        # Keep the visible timing at 2 seconds minimum.
        # ----------------------------------------------------

        elapsed = (
            time.monotonic()
            - generation_started
        )

        if elapsed < BOT_GENERATION_DELAY:
            wait_time = (
                BOT_GENERATION_DELAY
                - elapsed
            )

            remaining = (
                generation_time_limit
                - elapsed
            )

            if remaining > 0:
                await asyncio.sleep(
                    min(
                        wait_time,
                        remaining,
                    )
                )

        if not result:
            return ""

        result = str(result).strip()

        if len(result) > MAX_AI_RESPONSE_LENGTH:
            result = result[
                :MAX_AI_RESPONSE_LENGTH
            ]

        return result

    # ========================================================
    # SEND BOT MESSAGE
    # ========================================================

    async def send_bot_message(
        self,
        message: discord.Message,
        cfg: GroupBotConfig,
        text: str,
        previous_message: Optional[discord.Message],
    ) -> Optional[discord.Message]:

        client = self.clients.get(
            cfg.slot
        )

        if client is None:
            raise RuntimeError(
                "Secondary client not found."
            )

        channel = client.get_channel(
            message.channel.id
        )

        if channel is None:
            channel = await client.fetch_channel(
                message.channel.id
            )

        allowed_mentions = discord.AllowedMentions(
            users=False,
            roles=False,
            everyone=False,
            replied_user=False,
        )

        # ----------------------------------------------------
        # FIRST BOT
        # ----------------------------------------------------

        if previous_message is None:

            if cfg.reply_mode == "channel":
                return await channel.send(
                    text,
                    allowed_mentions=allowed_mentions,
                )

            return await channel.send(
                text,
                reference=message,
                mention_author=False,
                allowed_mentions=allowed_mentions,
            )

        # ----------------------------------------------------
        # NEXT BOTS
        # ----------------------------------------------------

        if cfg.reply_mode == "channel":
            return await channel.send(
                text,
                allowed_mentions=allowed_mentions,
            )

        return await channel.send(
            text,
            reference=previous_message,
            mention_author=False,
            allowed_mentions=allowed_mentions,
        )

    # ========================================================
    # FORMAT DURATION
    # ========================================================

    @staticmethod
    def format_duration(
        seconds: int,
    ) -> str:
        seconds = max(0, int(seconds))

        hours = seconds // 3600
        minutes = (
            seconds % 3600
        ) // 60
        secs = seconds % 60

        parts = []

        if hours:
            parts.append(
                f"{hours} ساعة"
            )

        if minutes:
            parts.append(
                f"{minutes} دقيقة"
            )

        if secs and not hours:
            parts.append(
                f"{secs} ثانية"
            )

        if not parts:
            return "0 ثانية"

        return " و ".join(parts)

    # ========================================================
    # SHUTDOWN
    # ========================================================

    async def stop_clients(self):
        self.shutdown_flag = True

        # Stop group tasks
        for task in list(
            self.group_tasks.values()
        ):
            if task and not task.done():
                task.cancel()

        self.group_tasks.clear()

        # Stop secondary clients
        for client in list(
            self.clients.values()
        ):
            try:
                await client.close()
            except Exception:
                pass

        self.clients.clear()

        for slot in self.online:
            self.online[slot] = False

    async def emergency_stop(self):
        for task in list(
            self.group_tasks.values()
        ):
            if task and not task.done():
                task.cancel()

        self.group_tasks.clear()


# ============================================================
# DASHBOARD VIEW
# ============================================================

class GroupDashboardView(discord.ui.View):

    def __init__(
        self,
        manager: AIGroupManager,
        guild_id: int,
    ):
        super().__init__(
            timeout=300
        )

        self.manager = manager
        self.guild_id = guild_id

    @discord.ui.button(
        label="تشغيل / إيقاف",
        emoji="⚡",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def toggle(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        settings = self.manager.db.get_settings(
            self.guild_id
        )

        settings.enabled = not settings.enabled

        self.manager.db.save_settings(
            settings
        )

        await self.refresh(
            interaction
        )

    @discord.ui.button(
        label="إعدادات القروب",
        emoji="⚙️",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def settings(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        embed = discord.Embed(
            title="⚙️ إعدادات AI Group",
            description=(
                "تحكم في مدة الدردشة وسرعة التفاعل "
                "وباقي إعدادات المجموعة."
            ),
        )

        current = self.manager.db.get_settings(
            self.guild_id
        )

        embed.add_field(
            name="⏱️ مدة الدردشة الحالية",
            value=(
                f"**{self.manager.format_duration(current.chat_duration)}**"
            ),
            inline=False,
        )

        embed.add_field(
            name="🔒 الحد الأقصى",
            value="**12 ساعة**",
            inline=True,
        )

        embed.add_field(
            name="👀 قراءة الرد",
            value="**3 ثوانٍ**",
            inline=True,
        )

        embed.add_field(
            name="🧠 التوليد",
            value="**2 ثانية**",
            inline=True,
        )

        embed.add_field(
            name="⚡ أول بوت",
            value="**يرد مباشرة**",
            inline=False,
        )

        embed.add_field(
            name="🔄 الحد الأقصى للجولات",
            value=str(current.max_turns),
            inline=True,
        )

        embed.add_field(
            name="⏳ Cooldown",
            value=f"{current.cooldown:g}s",
            inline=True,
        )

        view = GroupSettingsView(
            self.manager,
            self.guild_id,
        )

        await interaction.response.edit_message(
            embed=embed,
            view=view,
        )

    @discord.ui.button(
        label="البوتات",
        emoji="🤖",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def bots(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        view = BotPickerView(
            self.manager,
            self.guild_id,
        )

        embed = discord.Embed(
            title="🤖 بوتات AI Group",
            description=(
                "اختر البوت الذي تريد تعديل إعداداته."
            ),
        )

        for slot in range(1, MAX_BOTS + 1):
            cfg = self.manager.db.get_bot(
                self.guild_id,
                slot,
            )

            online = (
                "🟢"
                if self.manager.online.get(
                    slot,
                    False,
                )
                else "🔴"
            )

            enabled = (
                "مفعّل"
                if cfg.enabled
                else "متوقف"
            )

            embed.add_field(
                name=f"{online} Bot {slot}",
                value=(
                    f"**{cfg.name}**\n"
                    f"{enabled} • قوة {cfg.power}/100"
                ),
                inline=True,
            )

        await interaction.response.edit_message(
            embed=embed,
            view=view,
        )

    async def refresh(
        self,
        interaction: discord.Interaction,
    ):
        settings = self.manager.db.get_settings(
            self.guild_id
        )

        embed = self.manager.build_dashboard_embed(
            interaction.guild,
            settings,
        )

        await interaction.response.edit_message(
            embed=embed,
            view=GroupDashboardView(
                self.manager,
                self.guild_id,
            ),
        )


# ============================================================
# GROUP SETTINGS VIEW
# ============================================================

class GroupSettingsView(discord.ui.View):

    def __init__(
        self,
        manager: AIGroupManager,
        guild_id: int,
    ):
        super().__init__(
            timeout=300
        )

        self.manager = manager
        self.guild_id = guild_id

    @discord.ui.button(
        label="⏱️ مدة الدردشة",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def duration(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        current = self.manager.db.get_settings(
            self.guild_id
        )

        await interaction.response.send_modal(
            ChatDurationModal(
                self.manager,
                self.guild_id,
                current.chat_duration,
            )
        )

    @discord.ui.button(
        label="🔄 النمط",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def mode(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.send_message(
            "اختر نمط المجموعة:",
            view=GroupModeView(
                self.manager,
                self.guild_id,
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="🔙 رجوع",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        settings = self.manager.db.get_settings(
            self.guild_id
        )

        embed = self.manager.build_dashboard_embed(
            interaction.guild,
            settings,
        )

        await interaction.response.edit_message(
            embed=embed,
            view=GroupDashboardView(
                self.manager,
                self.guild_id,
            ),
        )


# ============================================================
# CHAT DURATION MODAL
# ============================================================

class ChatDurationModal(
    discord.ui.Modal,
    title="⏱️ مدة دردشة AI Group",
):

    duration = discord.ui.TextInput(
        label="مدة الدردشة",
        placeholder=(
            "مثال: 30m أو 2h أو 12h"
        ),
        required=True,
        max_length=10,
    )

    def __init__(
        self,
        manager: AIGroupManager,
        guild_id: int,
        current: int,
    ):
        super().__init__()

        self.manager = manager
        self.guild_id = guild_id

        self.duration.default = (
            self._format_input(current)
        )

    @staticmethod
    def _format_input(
        seconds: int,
    ) -> str:
        seconds = int(seconds)

        if seconds % 3600 == 0:
            return f"{seconds // 3600}h"

        if seconds % 60 == 0:
            return f"{seconds // 60}m"

        return f"{seconds}s"

    @staticmethod
    def parse_duration(
        value: str,
    ) -> Optional[int]:
        value = value.strip().lower()

        try:
            if value.endswith("h"):
                number = float(
                    value[:-1]
                )

                seconds = int(
                    number * 3600
                )

            elif value.endswith("m"):
                number = float(
                    value[:-1]
                )

                seconds = int(
                    number * 60
                )

            elif value.endswith("s"):
                number = float(
                    value[:-1]
                )

                seconds = int(number)

            else:
                # بدون وحدة = دقائق
                number = float(value)

                seconds = int(
                    number * 60
                )

            return seconds

        except Exception:
            return None

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        seconds = self.parse_duration(
            str(self.duration.value)
        )

        if seconds is None:
            await interaction.response.send_message(
                "❌ الصيغة غير صحيحة.\n\n"
                "أمثلة:\n"
                "`30m` = 30 دقيقة\n"
                "`2h` = ساعتان\n"
                "`12h` = 12 ساعة",
                ephemeral=True,
            )
            return

        success, text = (
            await self.manager.set_chat_duration(
                self.guild_id,
                seconds,
            )
        )

        if not success:
            await interaction.response.send_message(
                text,
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            (
                f"{text}\n\n"
                "👀 البوت التالي سيقرأ الرد "
                "**3 ثوانٍ**.\n"
                "🧠 ثم ينتظر **2 ثانية** للتوليد."
            ),
            ephemeral=True,
        )


# ============================================================
# GROUP MODE VIEW
# ============================================================

class GroupModeView(discord.ui.View):

    def __init__(
        self,
        manager: AIGroupManager,
        guild_id: int,
    ):
        super().__init__(
            timeout=120
        )

        self.manager = manager
        self.guild_id = guild_id

    @discord.ui.button(
        label="Round Robin",
        emoji="🔄",
        style=discord.ButtonStyle.primary,
    )
    async def round_robin(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.set_mode(
            interaction,
            "round_robin",
        )

    @discord.ui.button(
        label="Random",
        emoji="🎲",
        style=discord.ButtonStyle.secondary,
    )
    async def random_mode(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.set_mode(
            interaction,
            "random",
        )

    @discord.ui.button(
        label="Leader",
        emoji="👑",
        style=discord.ButtonStyle.success,
    )
    async def leader(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.set_mode(
            interaction,
            "leader",
        )

    async def set_mode(
        self,
        interaction: discord.Interaction,
        mode: str,
    ):
        await self.manager.set_mode(
            self.guild_id,
            mode,
        )

        names = {
            "round_robin": "🔄 Round Robin",
            "random": "🎲 Random",
            "leader": "👑 Leader",
        }

        await interaction.response.send_message(
            f"✅ تم تغيير النمط إلى **{names[mode]}**.",
            ephemeral=True,
        )


# ============================================================
# BOT PICKER
# ============================================================

class BotPickerView(discord.ui.View):

    def __init__(
        self,
        manager: AIGroupManager,
        guild_id: int,
    ):
        super().__init__(
            timeout=300
        )

        self.manager = manager
        self.guild_id = guild_id

        for slot in range(1, MAX_BOTS + 1):
            cfg = manager.db.get_bot(
                guild_id,
                slot,
            )

            button = discord.ui.Button(
                label=f"Bot {slot}: {cfg.name[:20]}",
                style=discord.ButtonStyle.secondary,
                row=(slot - 1) // 2,
            )

            async def callback(
                interaction: discord.Interaction,
                slot=slot,
            ):
                await self.open_bot(
                    interaction,
                    slot,
                )

            button.callback = callback

            self.add_item(button)

    async def open_bot(
        self,
        interaction: discord.Interaction,
        slot: int,
    ):
        cfg = self.manager.db.get_bot(
            self.guild_id,
            slot,
        )

        stats = self.manager.db.get_stats(
            self.guild_id,
            slot,
        )

        online = (
            "🟢 Online"
            if self.manager.online.get(
                slot,
                False,
            )
            else "🔴 Offline"
        )

        embed = discord.Embed(
            title=f"🤖 Bot {slot}",
            description=(
                f"**{cfg.name}**\n"
                f"{online}"
            ),
        )

        embed.add_field(
            name="💪 القوة",
            value=f"{cfg.power}/100",
            inline=True,
        )

        embed.add_field(
            name="🎭 المشاركة",
            value=f"{cfg.participation}%",
            inline=True,
        )

        embed.add_field(
            name="🧠 الذاكرة",
            value=(
                "مفعلة"
                if cfg.memory
                else "متوقفة"
            ),
            inline=True,
        )

        embed.add_field(
            name="📊 الإحصائيات",
            value=(
                f"رسائل: {stats['messages']}\n"
                f"أخطاء: {stats['errors']}"
            ),
            inline=True,
        )

        embed.add_field(
            name="🗣️ الشخصية",
            value=(
                cfg.personality[:500]
                if cfg.personality
                else "غير محددة"
            ),
            inline=False,
        )

        await interaction.response.edit_message(
            embed=embed,
            view=BotEditView(
                self.manager,
                self.guild_id,
                slot,
            ),
        )


# ============================================================
# BOT EDIT VIEW
# ============================================================

class BotEditView(discord.ui.View):

    def __init__(
        self,
        manager: AIGroupManager,
        guild_id: int,
        slot: int,
    ):
        super().__init__(
            timeout=300
        )

        self.manager = manager
        self.guild_id = guild_id
        self.slot = slot

    @discord.ui.button(
        label="تغيير الاسم",
        emoji="✏️",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def name(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        cfg = self.manager.db.get_bot(
            self.guild_id,
            self.slot,
        )

        await interaction.response.send_modal(
            BotNameModal(
                self.manager,
                self.guild_id,
                self.slot,
                cfg.name,
            )
        )

    @discord.ui.button(
        label="الشخصية",
        emoji="🎭",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def personality(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        cfg = self.manager.db.get_bot(
            self.guild_id,
            self.slot,
        )

        await interaction.response.send_modal(
            BotPersonalityModal(
                self.manager,
                self.guild_id,
                self.slot,
                cfg.personality,
            )
        )

    @discord.ui.button(
        label="القوة",
        emoji="💪",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def power(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        cfg = self.manager.db.get_bot(
            self.guild_id,
            self.slot,
        )

        await interaction.response.send_modal(
            BotPowerModal(
                self.manager,
                self.guild_id,
                self.slot,
                cfg.power,
            )
        )

    @discord.ui.button(
        label="تفعيل / إيقاف",
        emoji="⚡",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def enabled(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        cfg = self.manager.db.get_bot(
            self.guild_id,
            self.slot,
        )

        cfg.enabled = not cfg.enabled

        self.manager.db.save_bot(cfg)

        await interaction.response.send_message(
            (
                "🟢 تم تفعيل البوت."
                if cfg.enabled
                else "🔴 تم إيقاف البوت."
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="🔙 رجوع",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        embed = discord.Embed(
            title="🤖 بوتات AI Group",
            description=(
                "اختر البوت الذي تريد تعديله."
            ),
        )

        view = BotPickerView(
            self.manager,
            self.guild_id,
        )

        await interaction.response.edit_message(
            embed=embed,
            view=view,
        )


# ============================================================
# BOT NAME MODAL
# ============================================================

class BotNameModal(
    discord.ui.Modal,
    title="✏️ تغيير اسم البوت",
):

    name_input = discord.ui.TextInput(
        label="الاسم الجديد",
        required=True,
        max_length=32,
    )

    def __init__(
        self,
        manager: AIGroupManager,
        guild_id: int,
        slot: int,
        current_name: str,
    ):
        super().__init__()

        self.manager = manager
        self.guild_id = guild_id
        self.slot = slot

        self.name_input.default = current_name

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        new_name = (
            str(self.name_input.value)
            .strip()
        )

        if not new_name:
            await interaction.response.send_message(
                "❌ الاسم لا يمكن أن يكون فارغًا.",
                ephemeral=True,
            )
            return

        cfg = self.manager.db.get_bot(
            self.guild_id,
            self.slot,
        )

        success, text = (
            await self.manager.change_real_username(
                self.slot,
                new_name,
            )
        )

        if success:
            cfg.name = new_name
            self.manager.db.save_bot(cfg)

        await interaction.response.send_message(
            text,
            ephemeral=True,
        )


# ============================================================
# BOT PERSONALITY MODAL
# ============================================================

class BotPersonalityModal(
    discord.ui.Modal,
    title="🎭 شخصية البوت",
):

    personality_input = discord.ui.TextInput(
        label="الشخصية",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
    )

    def __init__(
        self,
        manager: AIGroupManager,
        guild_id: int,
        slot: int,
        current: str,
    ):
        super().__init__()

        self.manager = manager
        self.guild_id = guild_id
        self.slot = slot

        self.personality_input.default = current

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        cfg = self.manager.db.get_bot(
            self.guild_id,
            self.slot,
        )

        cfg.personality = str(
            self.personality_input.value
        ).strip()

        self.manager.db.save_bot(cfg)

        await interaction.response.send_message(
            "✅ تم حفظ شخصية البوت.",
            ephemeral=True,
        )


# ============================================================
# BOT POWER MODAL
# ============================================================

class BotPowerModal(
    discord.ui.Modal,
    title="💪 قوة البوت",
):

    power_input = discord.ui.TextInput(
        label="القوة من 1 إلى 100",
        placeholder="مثال: 80",
        required=True,
        max_length=3,
    )

    def __init__(
        self,
        manager: AIGroupManager,
        guild_id: int,
        slot: int,
        current: int,
    ):
        super().__init__()

        self.manager = manager
        self.guild_id = guild_id
        self.slot = slot

        self.power_input.default = str(
            current
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        try:
            power = int(
                str(self.power_input.value)
            )
        except Exception:
            await interaction.response.send_message(
                "❌ اكتب رقمًا من 1 إلى 100.",
                ephemeral=True,
            )
            return

        if not 1 <= power <= 100:
            await interaction.response.send_message(
                "❌ القوة يجب أن تكون بين 1 و100.",
                ephemeral=True,
            )
            return

        cfg = self.manager.db.get_bot(
            self.guild_id,
            self.slot,
        )

        cfg.power = power

        self.manager.db.save_bot(cfg)

        await interaction.response.send_message(
            f"✅ تم ضبط قوة البوت على **{power}/100**.",
            ephemeral=True,
        )


# ============================================================
# END
# ============================================================
