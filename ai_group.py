# ai_group.py
# ============================================================
# MyAI BOT — AI GROUP
# 5 Secondary Discord Bots
# ============================================================

import os
import asyncio
import sqlite3
import random
import traceback
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable

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


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class GroupBotConfig:
    guild_id: int
    slot: int

    name: str
    power: int = 50

    personality: str = ""
    speaking_style: str = ""

    participation: int = 100
    memory: bool = True

    reply_mode: str = "reply"
    enabled: bool = True


@dataclass
class GroupSettings:
    guild_id: int

    enabled: bool = False
    channel_id: Optional[int] = None

    mode: str = "round_robin"
    max_turns: int = 5

    cooldown: float = 5.0
    round_delay: float = 2.0

    leader_slot: int = 1


# ============================================================
# DATABASE
# ============================================================

class AIGroupDB:

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._setup()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            pass

        return conn

    def _setup(self):
        with self._connect() as conn:

            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_group_settings (
                    guild_id INTEGER PRIMARY KEY,
                    enabled INTEGER DEFAULT 0,
                    channel_id INTEGER,
                    mode TEXT DEFAULT 'round_robin',
                    max_turns INTEGER DEFAULT 5,
                    cooldown REAL DEFAULT 5.0,
                    round_delay REAL DEFAULT 2.0,
                    leader_slot INTEGER DEFAULT 1
                )
            """)

            conn.execute("""
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

                    PRIMARY KEY (guild_id, slot)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_group_stats (
                    guild_id INTEGER NOT NULL,
                    slot INTEGER NOT NULL,

                    messages INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,

                    PRIMARY KEY (guild_id, slot)
                )
            """)

            conn.commit()

    # --------------------------------------------------------
    # SETTINGS
    # --------------------------------------------------------

    def get_settings(self, guild_id: int) -> GroupSettings:

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM ai_group_settings
                WHERE guild_id = ?
                """,
                (guild_id,),
            ).fetchone()

        if not row:
            return GroupSettings(guild_id=guild_id)

        return GroupSettings(
            guild_id=guild_id,
            enabled=bool(row["enabled"]),
            channel_id=row["channel_id"],
            mode=row["mode"] or "round_robin",
            max_turns=int(row["max_turns"] or 5),
            cooldown=float(row["cooldown"] or 5.0),
            round_delay=float(row["round_delay"] or 2.0),
            leader_slot=int(row["leader_slot"] or 1),
        )

    def save_settings(self, settings: GroupSettings):

        with self._connect() as conn:

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
                    leader_slot
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)

                ON CONFLICT(guild_id)
                DO UPDATE SET
                    enabled = excluded.enabled,
                    channel_id = excluded.channel_id,
                    mode = excluded.mode,
                    max_turns = excluded.max_turns,
                    cooldown = excluded.cooldown,
                    round_delay = excluded.round_delay,
                    leader_slot = excluded.leader_slot
                """,
                (
                    settings.guild_id,
                    int(settings.enabled),
                    settings.channel_id,
                    settings.mode,
                    settings.max_turns,
                    settings.cooldown,
                    settings.round_delay,
                    settings.leader_slot,
                ),
            )

            conn.commit()

    # --------------------------------------------------------
    # BOTS
    # --------------------------------------------------------

    def get_bot(self, guild_id: int, slot: int) -> GroupBotConfig:

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT *
                FROM ai_group_bots
                WHERE guild_id = ?
                AND slot = ?
                """,
                (guild_id, slot),
            ).fetchone()

            if not row:

                name = DEFAULT_NAMES[slot - 1]

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
                    """,
                    (
                        guild_id,
                        slot,
                        name,
                        50,
                        "",
                        "",
                        100,
                        1,
                        "reply",
                        1,
                    ),
                )

                conn.commit()

                return GroupBotConfig(
                    guild_id=guild_id,
                    slot=slot,
                    name=name,
                )

        return GroupBotConfig(
            guild_id=guild_id,
            slot=slot,
            name=row["name"],
            power=int(row["power"] or 50),
            personality=row["personality"] or "",
            speaking_style=row["speaking_style"] or "",
            participation=int(row["participation"] or 100),
            memory=bool(row["memory"]),
            reply_mode=row["reply_mode"] or "reply",
            enabled=bool(row["enabled"]),
        )

    def save_bot(self, config: GroupBotConfig):

        with self._connect() as conn:

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
                    config.guild_id,
                    config.slot,
                    config.name,
                    config.power,
                    config.personality,
                    config.speaking_style,
                    config.participation,
                    int(config.memory),
                    config.reply_mode,
                    int(config.enabled),
                ),
            )

            conn.commit()

    def add_message_stat(self, guild_id: int, slot: int):

        with self._connect() as conn:

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

    def add_error_stat(self, guild_id: int, slot: int):

        with self._connect() as conn:

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

    def get_stats(self, guild_id: int, slot: int):

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT messages, errors
                FROM ai_group_stats
                WHERE guild_id = ?
                AND slot = ?
                """,
                (guild_id, slot),
            ).fetchone()

        if not row:
            return 0, 0

        return int(row["messages"]), int(row["errors"])


# ============================================================
# BOT CLIENT
# ============================================================

class SecondaryBotClient(discord.Client):

    def __init__(self, manager, slot: int):

        intents = discord.Intents.default()

        # We don't need message_content for normal operation.
        intents.message_content = False

        super().__init__(
            intents=intents,
            chunk_guilds_at_startup=False,
        )

        self.manager = manager
        self.slot = slot

    async def on_ready(self):

        self.manager.online[self.slot] = True

        try:
            username = self.user.name if self.user else "Unknown"

            print(
                f"[AI_GROUP] Bot {self.slot} ONLINE "
                f"as {username}"
                f"{'#' + self.user.discriminator if self.user and self.user.discriminator != '0' else ''}"
            )

        except Exception:
            print(
                f"[AI_GROUP] Bot {self.slot} ONLINE"
            )


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

        self.running: dict[int, bool] = {}

        self.locks: dict[int, asyncio.Lock] = {}

        self.last_message_time: dict[int, float] = {}

    # ========================================================
    # TOKEN MANAGEMENT
    # ========================================================

    def get_token(self, slot: int) -> Optional[str]:

        if slot < 1 or slot > MAX_BOTS:
            return None

        token = os.getenv(BOT_ENV_NAMES[slot - 1])

        if not token:
            return None

        token = token.strip()

        if not token:
            return None

        return token

    def configured_count(self) -> int:

        return sum(
            1
            for slot in range(1, MAX_BOTS + 1)
            if self.get_token(slot)
        )

    def ready_count(self) -> int:

        return sum(
            1
            for slot in range(1, MAX_BOTS + 1)
            if self.online.get(slot, False)
        )

    # ========================================================
    # START CLIENTS
    # ========================================================

    async def start_clients(self):

        configured = self.configured_count()

        print(
            f"[AI_GROUP] configured={configured}/{MAX_BOTS}"
        )

        for slot in range(1, MAX_BOTS + 1):

            token = self.get_token(slot)

            if not token:
                print(
                    f"[AI_GROUP] Bot {slot}: "
                    f"{BOT_ENV_NAMES[slot - 1]} is missing"
                )
                continue

            client = SecondaryBotClient(
                manager=self,
                slot=slot,
            )

            self.clients[slot] = client

            task = asyncio.create_task(
                self._start_client(
                    slot,
                    client,
                    token,
                )
            )

            self.tasks[slot] = task

    async def _start_client(
        self,
        slot: int,
        client: SecondaryBotClient,
        token: str,
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

            self.online[slot] = False

            try:
                await client.close()
            except Exception:
                pass

            raise

        except Exception as exc:

            self.online[slot] = False

            print(
                f"[AI_GROUP] Bot {slot} failed: "
                f"{type(exc).__name__}: {exc}"
            )

            traceback.print_exc()

    # ========================================================
    # REGISTER COMMAND
    # ========================================================

    async def register_command(self, tree: app_commands.CommandTree):

        @tree.command(
            name="ai_group",
            description="لوحة التحكم بمجموعة MyAI"
        )
        @app_commands.default_permissions(
            manage_guild=True
        )
        async def ai_group_command(
            interaction: discord.Interaction
        ):

            if interaction.guild is None:

                await interaction.response.send_message(
                    "❌ هذا الأمر داخل السيرفر فقط.",
                    ephemeral=True,
                )

                return

            await interaction.response.send_message(
                embed=self.build_dashboard_embed(
                    interaction.guild.id
                ),
                view=GroupDashboardView(
                    self,
                    interaction.guild.id,
                ),
                ephemeral=True,
            )

    # ========================================================
    # DASHBOARD
    # ========================================================

    def build_dashboard_embed(
        self,
        guild_id: int,
    ) -> discord.Embed:

        settings = self.db.get_settings(guild_id)

        status = (
            "🟢 مفعلة"
            if settings.enabled
            else
            "🔴 متوقفة"
        )

        channel_text = (
            f"<#{settings.channel_id}>"
            if settings.channel_id
            else
            "غير محدد"
        )

        embed = discord.Embed(
            title="🤖 AI Group",
            description=(
                "لوحة التحكم بمجموعة البوتات.\n\n"
                f"**الحالة:** {status}\n"
                f"**الروم:** {channel_text}\n"
                f"**النمط:** `{settings.mode}`\n"
                f"**الجولات:** `{settings.max_turns}`\n"
                f"**البوتات المتصلة:** "
                f"`{self.ready_count()}/{MAX_BOTS}`"
            ),
            color=discord.Color.blurple(),
        )

        for slot in range(1, MAX_BOTS + 1):

            cfg = self.db.get_bot(
                guild_id,
                slot,
            )

            online = self.online.get(
                slot,
                False,
            )

            icon = "🟢" if online else "🔴"

            embed.add_field(
                name=f"{icon} Bot {slot} — {cfg.name}",
                value=(
                    f"Power: `{cfg.power}/100`\n"
                    f"Participation: `{cfg.participation}%`\n"
                    f"Enabled: "
                    f"`{'Yes' if cfg.enabled else 'No'}`"
                ),
                inline=True,
            )

        return embed

    # ========================================================
    # ACTUAL DISCORD USERNAME CHANGE
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
                "البوت غير موجود في الذاكرة.",
            )

        if not client.is_ready():
            return (
                False,
                "البوت غير متصل حاليًا.",
            )

        if client.user is None:
            return (
                False,
                "لم يتم التعرف على حساب البوت.",
            )

        new_name = new_name.strip()

        if not new_name:
            return (
                False,
                "اسم البوت لا يمكن أن يكون فارغًا.",
            )

        # Discord username limit
        if len(new_name) > 32:
            return (
                False,
                "اسم Discord يجب ألا يتجاوز 32 حرفًا.",
            )

        old_name = client.user.name

        try:

            # =================================================
            # THIS CHANGES THE REAL DISCORD ACCOUNT USERNAME
            # =================================================

            await client.user.edit(
                username=new_name
            )

            # Give Discord a moment to update cache
            await asyncio.sleep(0.5)

            actual_name = (
                client.user.name
                if client.user
                else new_name
            )

            return (
                True,
                (
                    f"تم تغيير اسم البوت فعليًا من "
                    f"`{old_name}` إلى `{actual_name}`."
                ),
            )

        except discord.HTTPException as exc:

            status = getattr(
                exc,
                "status",
                "unknown",
            )

            return (
                False,
                (
                    f"Discord رفض تغيير الاسم.\n"
                    f"HTTP Status: `{status}`\n"
                    f"السبب: `{exc}`"
                ),
            )

        except Exception as exc:

            return (
                False,
                (
                    "حدث خطأ أثناء تغيير اسم البوت:\n"
                    f"`{type(exc).__name__}: {exc}`"
                ),
            )

    # ========================================================
    # EDIT BOT
    # ========================================================

    async def edit_bot_name(
        self,
        guild_id: int,
        slot: int,
        new_name: str,
    ) -> tuple[bool, str]:

        cfg = self.db.get_bot(
            guild_id,
            slot,
        )

        # Change the REAL Discord username first.
        success, message = await self.change_real_username(
            slot,
            new_name,
        )

        if not success:
            return False, message

        # Save only after Discord accepts the change.
        cfg.name = new_name.strip()

        self.db.save_bot(cfg)

        return True, message

    # ========================================================
    # EDIT BOT SETTINGS
    # ========================================================

    def update_bot(
        self,
        guild_id: int,
        slot: int,
        **kwargs,
    ):

        cfg = self.db.get_bot(
            guild_id,
            slot,
        )

        for key, value in kwargs.items():

            if hasattr(cfg, key):
                setattr(
                    cfg,
                    key,
                    value,
                )

        self.db.save_bot(cfg)

    # ========================================================
    # SETTINGS
    # ========================================================

    def set_enabled(
        self,
        guild_id: int,
        enabled: bool,
    ):

        settings = self.db.get_settings(
            guild_id
        )

        settings.enabled = enabled

        self.db.save_settings(settings)

    def set_channel(
        self,
        guild_id: int,
        channel_id: Optional[int],
    ):

        settings = self.db.get_settings(
            guild_id
        )

        settings.channel_id = channel_id

        self.db.save_settings(settings)

    def set_mode(
        self,
        guild_id: int,
        mode: str,
    ):

        settings = self.db.get_settings(
            guild_id
        )

        settings.mode = mode

        self.db.save_settings(settings)

    # ========================================================
    # MESSAGE HANDLING
    # ========================================================

    async def handle_message(
        self,
        message: discord.Message,
    ) -> bool:

        if message.guild is None:
            return False

        guild_id = message.guild.id

        settings = self.db.get_settings(
            guild_id
        )

        if not settings.enabled:
            return False

        if not settings.channel_id:
            return False

        if message.channel.id != settings.channel_id:
            return False

        if message.author.bot:
            return False

        lock = self.locks.setdefault(
            guild_id,
            asyncio.Lock(),
        )

        if lock.locked():
            return True

        now = asyncio.get_running_loop().time()

        last = self.last_message_time.get(
            guild_id,
            0,
        )

        if now - last < settings.cooldown:
            return True

        self.last_message_time[guild_id] = now

        asyncio.create_task(
            self.run_group(
                message
            )
        )

        return True

    # ========================================================
    # RUN GROUP
    # ========================================================

    async def run_group(
        self,
        message: discord.Message,
    ):

        guild_id = message.guild.id

        lock = self.locks.setdefault(
            guild_id,
            asyncio.Lock(),
        )

        async with lock:

            settings = self.db.get_settings(
                guild_id
            )

            bots = []

            for slot in range(
                1,
                MAX_BOTS + 1,
            ):

                cfg = self.db.get_bot(
                    guild_id,
                    slot,
                )

                if not cfg.enabled:
                    continue

                if not self.online.get(
                    slot,
                    False,
                ):
                    continue

                if random.randint(
                    1,
                    100,
                ) > cfg.participation:
                    continue

                bots.append(cfg)

            if not bots:
                return

            if settings.mode == "random":

                random.shuffle(bots)

            elif settings.mode == "leader":

                leader = next(
                    (
                        b
                        for b in bots
                        if b.slot == settings.leader_slot
                    ),
                    None,
                )

                if leader:

                    bots.remove(leader)
                    bots.insert(0, leader)

            # round_robin keeps normal slot order.

            bots = bots[
                : max(
                    1,
                    settings.max_turns,
                )
            ]

            conversation = message.content

            for index, cfg in enumerate(bots):

                client = self.clients.get(
                    cfg.slot
                )

                if not client or not client.is_ready():
                    continue

                try:

                    result = await self.generate_for_bot(
                        message=message,
                        cfg=cfg,
                        conversation=conversation,
                    )

                    if not result:
                        continue

                    sent = await self.send_bot_message(
                        message=message,
                        client=client,
                        cfg=cfg,
                        text=result,
                    )

                    if sent:

                        self.db.add_message_stat(
                            guild_id,
                            cfg.slot,
                        )

                        conversation += (
                            f"\n{cfg.name}: {result}"
                        )

                except Exception as exc:

                    self.db.add_error_stat(
                        guild_id,
                        cfg.slot,
                    )

                    print(
                        f"[AI_GROUP] "
                        f"Bot {cfg.slot} error: "
                        f"{type(exc).__name__}: {exc}"
                    )

                if index < len(bots) - 1:

                    await asyncio.sleep(
                        settings.round_delay
                    )

    # ========================================================
    # AI GENERATION
    # ========================================================

    async def generate_for_bot(
        self,
        message: discord.Message,
        cfg: GroupBotConfig,
        conversation: str,
    ) -> str:

        personality = (
            cfg.personality.strip()
            or
            "شخصية طبيعية وذكية."
        )

        speaking_style = (
            cfg.speaking_style.strip()
            or
            "تكلم بطريقة طبيعية ومختصرة."
        )

        system_context = f"""
أنت بوت رقم {cfg.slot} داخل مجموعة AI.

اسمك:
{cfg.name}

قوة الشخصية:
{cfg.power}/100

الشخصية:
{personality}

أسلوب الكلام:
{speaking_style}

قواعد مهمة:
- أنت عضو في مجموعة من عدة بوتات.
- لا تدّعي أنك البوت الرئيسي.
- لا تذكر أنك تستخدم API.
- لا تقل إنك إنسان.
- لا تكرر كلام الأعضاء الآخرين بلا سبب.
- تكلم بالعربية بشكل طبيعي إذا كان المستخدم عربيًا.
- لا تستخدم Markdown مبالغ فيه.
- اجعل الرد مناسبًا للمحادثة.
- لا تبدأ الرد باسمك.
"""

        prompt = f"""
رسالة المستخدم:
{message.content}

سياق المجموعة:
{conversation}

اكتب ردك الآن.
"""

        result = await self.ai_generate(
            guild_id=message.guild.id,
            user_id=message.author.id,
            bot_name=cfg.name,
            personality=personality,
            speaking_style=speaking_style,
            power=cfg.power,
            prompt=prompt,
            system_prompt=system_context,
        )

        if result is None:
            return ""

        return str(result).strip()

    # ========================================================
    # SEND MESSAGE
    # ========================================================

    async def send_bot_message(
        self,
        message: discord.Message,
        client: SecondaryBotClient,
        cfg: GroupBotConfig,
        text: str,
    ) -> Optional[discord.Message]:

        if not text:
            return None

        if len(text) > 2000:
            text = text[:1997] + "..."

        try:

            if cfg.reply_mode == "reply":

                return await message.reply(
                    text,
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions(
                        users=False,
                        roles=False,
                        everyone=False,
                    ),
                )

            return await message.channel.send(
                text,
                allowed_mentions=discord.AllowedMentions(
                    users=False,
                    roles=False,
                    everyone=False,
                ),
            )

        except discord.HTTPException as exc:

            print(
                f"[AI_GROUP] "
                f"Bot {cfg.slot} send failed: "
                f"{exc}"
            )

            return None

    # ========================================================
    # STOP
    # ========================================================

    async def stop_clients(self):

        for slot, client in list(
            self.clients.items()
        ):

            try:
                await client.close()
            except Exception:
                pass

            self.online[slot] = False

        self.clients.clear()

    # ========================================================
    # EMERGENCY STOP
    # ========================================================

    async def emergency_stop(
        self,
        guild_id: int,
    ):

        self.set_enabled(
            guild_id,
            False,
        )

        task = self.tasks.get(
            guild_id
        )

        if task and not task.done():
            task.cancel()

    # ========================================================
    # STATS
    # ========================================================

    def get_all_stats(
        self,
        guild_id: int,
    ):

        result = []

        for slot in range(
            1,
            MAX_BOTS + 1,
        ):

            messages, errors = self.db.get_stats(
                guild_id,
                slot,
            )

            cfg = self.db.get_bot(
                guild_id,
                slot,
            )

            result.append(
                {
                    "slot": slot,
                    "name": cfg.name,
                    "messages": messages,
                    "errors": errors,
                    "online": self.online.get(
                        slot,
                        False,
                    ),
                }
            )

        return result


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
        label="تشغيل",
        emoji="▶️",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def enable(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        self.manager.set_enabled(
            self.guild_id,
            True,
        )

        await interaction.response.edit_message(
            embed=self.manager.build_dashboard_embed(
                self.guild_id
            ),
            view=self,
        )

    @discord.ui.button(
        label="إيقاف",
        emoji="⏹️",
        style=discord.ButtonStyle.danger,
        row=0,
    )
    async def disable(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        self.manager.set_enabled(
            self.guild_id,
            False,
        )

        await interaction.response.edit_message(
            embed=self.manager.build_dashboard_embed(
                self.guild_id
            ),
            view=self,
        )

    @discord.ui.button(
        label="البوتات",
        emoji="🤖",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def bots(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🤖 إدارة بوتات AI Group",
                description=(
                    "اختر البوت الذي تريد تعديله:"
                ),
                color=discord.Color.blurple(),
            ),
            view=BotPickerView(
                self.manager,
                self.guild_id,
            ),
        )

    @discord.ui.button(
        label="الإعدادات",
        emoji="⚙️",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def settings(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="⚙️ إعدادات AI Group",
                description=(
                    "تحكم في طريقة عمل المجموعة."
                ),
                color=discord.Color.blurple(),
            ),
            view=GroupSettingsView(
                self.manager,
                self.guild_id,
            ),
        )

    @discord.ui.button(
        label="الإحصائيات",
        emoji="📊",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def stats(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        stats = self.manager.get_all_stats(
            self.guild_id
        )

        lines = []

        for item in stats:

            status = (
                "🟢"
                if item["online"]
                else
                "🔴"
            )

            lines.append(
                f"{status} **Bot {item['slot']} — "
                f"{item['name']}**\n"
                f"رسائل: `{item['messages']}` | "
                f"أخطاء: `{item['errors']}`"
            )

        embed = discord.Embed(
            title="📊 AI Group Stats",
            description="\n\n".join(lines),
            color=discord.Color.blurple(),
        )

        await interaction.response.edit_message(
            embed=embed,
            view=BackToDashboardView(
                self.manager,
                self.guild_id,
            ),
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
                label=f"Bot {slot}: {cfg.name[:70]}",
                style=discord.ButtonStyle.primary,
                row=(slot - 1) // 2,
            )

            async def callback(
                interaction: discord.Interaction,
                selected_slot=slot,
            ):

                cfg2 = self.manager.db.get_bot(
                    self.guild_id,
                    selected_slot,
                )

                await interaction.response.edit_message(
                    embed=discord.Embed(
                        title=(
                            f"🤖 Bot {selected_slot}"
                        ),
                        description=(
                            f"**الاسم الحالي:** "
                            f"`{cfg2.name}`\n"
                            f"**Power:** `{cfg2.power}/100`\n"
                            f"**Participation:** "
                            f"`{cfg2.participation}%`\n\n"
                            "يمكنك تغيير الاسم أو "
                            "إعدادات الشخصية."
                        ),
                        color=discord.Color.blurple(),
                    ),
                    view=BotEditView(
                        self.manager,
                        self.guild_id,
                        selected_slot,
                    ),
                )

            button.callback = callback
            self.add_item(button)

        back = discord.ui.Button(
            label="رجوع",
            emoji="↩️",
            style=discord.ButtonStyle.secondary,
            row=3,
        )

        async def back_callback(
            interaction: discord.Interaction,
        ):

            await interaction.response.edit_message(
                embed=self.manager.build_dashboard_embed(
                    self.guild_id
                ),
                view=GroupDashboardView(
                    self.manager,
                    self.guild_id,
                ),
            )

        back.callback = back_callback
        self.add_item(back)


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
        label="تغيير اسم Discord",
        emoji="✏️",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def change_name(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            BotNameModal(
                self.manager,
                self.guild_id,
                self.slot,
            )
        )

    @discord.ui.button(
        label="تفعيل/تعطيل",
        emoji="🔘",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def toggle(
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

        state = (
            "🟢 مفعّل"
            if cfg.enabled
            else
            "🔴 متوقف"
        )

        await interaction.response.send_message(
            f"Bot {self.slot}: {state}",
            ephemeral=True,
        )

    @discord.ui.button(
        label="الشخصية",
        emoji="🎭",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def personality(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            BotPersonalityModal(
                self.manager,
                self.guild_id,
                self.slot,
            )
        )

    @discord.ui.button(
        label="رجوع",
        emoji="↩️",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🤖 إدارة بوتات AI Group",
                description=(
                    "اختر البوت الذي تريد تعديله:"
                ),
                color=discord.Color.blurple(),
            ),
            view=BotPickerView(
                self.manager,
                self.guild_id,
            ),
        )


# ============================================================
# NAME MODAL
# ============================================================

class BotNameModal(discord.ui.Modal):

    def __init__(
        self,
        manager: AIGroupManager,
        guild_id: int,
        slot: int,
    ):

        super().__init__(
            title=f"تغيير اسم Bot {slot}"
        )

        self.manager = manager
        self.guild_id = guild_id
        self.slot = slot

        cfg = manager.db.get_bot(
            guild_id,
            slot,
        )

        self.name_input = discord.ui.TextInput(
            label="اسم Discord الجديد",
            placeholder="اكتب اسم البوت...",
            default=cfg.name,
            min_length=1,
            max_length=32,
            required=True,
        )

        self.add_item(
            self.name_input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):

        new_name = str(
            self.name_input.value
        ).strip()

        await interaction.response.defer(
            ephemeral=True
        )

        success, message = await self.manager.edit_bot_name(
            self.guild_id,
            self.slot,
            new_name,
        )

        if success:

            await interaction.followup.send(
                f"✅ {message}",
                ephemeral=True,
            )

        else:

            await interaction.followup.send(
                f"❌ {message}",
                ephemeral=True,
            )


# ============================================================
# PERSONALITY MODAL
# ============================================================

class BotPersonalityModal(discord.ui.Modal):

    def __init__(
        self,
        manager: AIGroupManager,
        guild_id: int,
        slot: int,
    ):

        super().__init__(
            title=f"شخصية Bot {slot}"
        )

        self.manager = manager
        self.guild_id = guild_id
        self.slot = slot

        cfg = manager.db.get_bot(
            guild_id,
            slot,
        )

        self.personality_input = discord.ui.TextInput(
            label="الشخصية",
            placeholder="مثال: هادئ، ذكي، مرح...",
            default=cfg.personality,
            max_length=1000,
            required=False,
            style=discord.TextStyle.paragraph,
        )

        self.style_input = discord.ui.TextInput(
            label="أسلوب الكلام",
            placeholder="مثال: مختصر وعفوي...",
            default=cfg.speaking_style,
            max_length=1000,
            required=False,
            style=discord.TextStyle.paragraph,
        )

        self.add_item(
            self.personality_input
        )

        self.add_item(
            self.style_input
        )

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

        cfg.speaking_style = str(
            self.style_input.value
        ).strip()

        self.manager.db.save_bot(
            cfg
        )

        await interaction.response.send_message(
            "✅ تم حفظ شخصية البوت وأسلوب كلامه.",
            ephemeral=True,
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

    @discord.ui.select(
        placeholder="اختر نمط المجموعة",
        options=[
            discord.SelectOption(
                label="Round Robin",
                value="round_robin",
                description="البوتات تتكلم بالترتيب",
            ),
            discord.SelectOption(
                label="Random",
                value="random",
                description="اختيار البوتات عشوائيًا",
            ),
            discord.SelectOption(
                label="Leader",
                value="leader",
                description="البوت القائد يبدأ",
            ),
        ],
        row=0,
    )
    async def mode_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ):

        self.manager.set_mode(
            self.guild_id,
            select.values[0],
        )

        await interaction.response.send_message(
            f"✅ تم اختيار النمط `{select.values[0]}`.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="اختيار الروم الحالي",
        emoji="📢",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def current_channel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if interaction.channel:

            self.manager.set_channel(
                self.guild_id,
                interaction.channel.id,
            )

            await interaction.response.send_message(
                "✅ تم تعيين هذا الروم لمجموعة AI.",
                ephemeral=True,
            )

    @discord.ui.button(
        label="رجوع",
        emoji="↩️",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.edit_message(
            embed=self.manager.build_dashboard_embed(
                self.guild_id
            ),
            view=GroupDashboardView(
                self.manager,
                self.guild_id,
            ),
        )


# ============================================================
# BACK VIEW
# ============================================================

class BackToDashboardView(discord.ui.View):

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
        label="رجوع للوحة",
        emoji="↩️",
        style=discord.ButtonStyle.primary,
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.edit_message(
            embed=self.manager.build_dashboard_embed(
                self.guild_id
            ),
            view=GroupDashboardView(
                self.manager,
                self.guild_id,
            ),
        )
