# ============================================================
# MyAI BOT — PROFESSIONAL AI GROUP SYSTEM
# ============================================================
#
# AI GROUP
# ├── Main MyAI Bot
# ├── Secondary Bot 1
# ├── Secondary Bot 2
# ├── Secondary Bot 3
# ├── Secondary Bot 4
# └── Secondary Bot 5
#
# Features:
# - 5 independent Discord bot accounts
# - Shared AI provider/model from Main MyAI
# - Per-bot personality
# - Per-bot speaking style
# - Per-bot power
# - Per-bot participation
# - Per-bot memory preference
# - Real Discord username changing
# - Group modes
# - Cooldowns
# - Turn limits
# - Leader mode
# - Random mode
# - Round-robin mode
# - Statistics
# - Automatic DB migrations
# - Safe background tasks
# - Error recovery
# - Sequential AI replies
# - Bot-to-bot Discord replies
# - No token logging
#
# ============================================================

from __future__ import annotations

import os
import asyncio
import random
import sqlite3
import traceback
import time

from dataclasses import dataclass
from typing import (
    Optional,
    Callable,
    Awaitable,
    Any,
)

import discord
from discord import app_commands
from discord.ext import commands


# ============================================================
# CONSTANTS
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
DEFAULT_ROUND_DELAY = 2.0


# ============================================================
# DATA CLASSES
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


# ============================================================
# DATABASE
# ============================================================

class AIGroupDB:

    """
    Database layer dedicated to AI Group.

    This class NEVER deletes the existing database.

    Old installations are automatically migrated.
    """

    def __init__(self, db_path: str):

        self.db_path = db_path

        self._setup()

    # --------------------------------------------------------
    # CONNECTION
    # --------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:

        conn = sqlite3.connect(
            self.db_path,
            timeout=10,
        )

        conn.row_factory = sqlite3.Row

        try:

            conn.execute(
                "PRAGMA journal_mode=WAL"
            )

            conn.execute(
                "PRAGMA foreign_keys=ON"
            )

            conn.execute(
                "PRAGMA busy_timeout=10000"
            )

        except Exception:
            pass

        return conn

    # --------------------------------------------------------
    # TABLE EXISTS
    # --------------------------------------------------------

    def _table_exists(
        self,
        conn: sqlite3.Connection,
        table_name: str,
    ) -> bool:

        row = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            AND name = ?
            """,
            (table_name,),
        ).fetchone()

        return row is not None

    # --------------------------------------------------------
    # COLUMNS
    # --------------------------------------------------------

    def _get_columns(
        self,
        conn: sqlite3.Connection,
        table_name: str,
    ) -> set[str]:

        if not self._table_exists(
            conn,
            table_name,
        ):
            return set()

        rows = conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()

        return {
            str(row["name"])
            for row in rows
        }

    # --------------------------------------------------------
    # SAFE ADD COLUMN
    # --------------------------------------------------------

    def _add_column_if_missing(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ):

        columns = self._get_columns(
            conn,
            table_name,
        )

        if column_name in columns:
            return

        conn.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name} {definition}
            """
        )

        print(
            f"[AI_GROUP][DB] "
            f"Added missing column "
            f"{table_name}.{column_name}"
        )

    # --------------------------------------------------------
    # SETUP
    # --------------------------------------------------------

    def _setup(self):

        with self._connect() as conn:

            # =================================================
            # GROUP SETTINGS
            # =================================================

            conn.execute(
                """
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
                """
            )

            # =================================================
            # GROUP BOTS
            # =================================================

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

                    PRIMARY KEY (
                        guild_id,
                        slot
                    )

                )
                """
            )

            # =================================================
            # GROUP STATS
            # =================================================

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_group_stats (

                    guild_id INTEGER NOT NULL,

                    slot INTEGER NOT NULL,

                    messages INTEGER DEFAULT 0,

                    errors INTEGER DEFAULT 0,

                    PRIMARY KEY (
                        guild_id,
                        slot
                    )

                )
                """
            )

            # =================================================
            # MIGRATION
            # =================================================

            stats_columns = self._get_columns(
                conn,
                "ai_group_stats",
            )

            if stats_columns:

                # ------------------------------------------------
                # Old table without slot
                # ------------------------------------------------

                if "slot" not in stats_columns:

                    print(
                        "[AI_GROUP][DB] "
                        "Migrating legacy ai_group_stats..."
                    )

                    old_rows = conn.execute(
                        """
                        SELECT *
                        FROM ai_group_stats
                        """
                    ).fetchall()

                    conn.execute(
                        """
                        ALTER TABLE ai_group_stats
                        RENAME TO ai_group_stats_legacy
                        """
                    )

                    conn.execute(
                        """
                        CREATE TABLE ai_group_stats (

                            guild_id INTEGER NOT NULL,

                            slot INTEGER NOT NULL,

                            messages INTEGER DEFAULT 0,

                            errors INTEGER DEFAULT 0,

                            PRIMARY KEY (
                                guild_id,
                                slot
                            )

                        )
                        """
                    )

                    for row in old_rows:

                        keys = row.keys()

                        guild_id = (
                            row["guild_id"]
                            if "guild_id" in keys
                            else None
                        )

                        messages = (
                            row["messages"]
                            if "messages" in keys
                            else 0
                        )

                        errors = (
                            row["errors"]
                            if "errors" in keys
                            else 0
                        )

                        if guild_id is None:
                            continue

                        conn.execute(
                            """
                            INSERT OR IGNORE INTO ai_group_stats (
                                guild_id,
                                slot,
                                messages,
                                errors
                            )
                            VALUES (?, 1, ?, ?)
                            """,
                            (
                                guild_id,
                                messages or 0,
                                errors or 0,
                            ),
                        )

                    conn.execute(
                        """
                        DROP TABLE ai_group_stats_legacy
                        """
                    )

                    print(
                        "[AI_GROUP][DB] "
                        "Legacy statistics migrated."
                    )

                else:

                    self._add_column_if_missing(
                        conn,
                        "ai_group_stats",
                        "errors",
                        "INTEGER DEFAULT 0",
                    )

            # =================================================
            # SETTINGS MIGRATION
            # =================================================

            settings_columns = self._get_columns(
                conn,
                "ai_group_settings",
            )

            if settings_columns:

                self._add_column_if_missing(
                    conn,
                    "ai_group_settings",
                    "enabled",
                    "INTEGER DEFAULT 0",
                )

                self._add_column_if_missing(
                    conn,
                    "ai_group_settings",
                    "channel_id",
                    "INTEGER",
                )

                self._add_column_if_missing(
                    conn,
                    "ai_group_settings",
                    "mode",
                    "TEXT DEFAULT 'round_robin'",
                )

                self._add_column_if_missing(
                    conn,
                    "ai_group_settings",
                    "max_turns",
                    "INTEGER DEFAULT 5",
                )

                self._add_column_if_missing(
                    conn,
                    "ai_group_settings",
                    "cooldown",
                    "REAL DEFAULT 5.0",
                )

                self._add_column_if_missing(
                    conn,
                    "ai_group_settings",
                    "round_delay",
                    "REAL DEFAULT 2.0",
                )

                self._add_column_if_missing(
                    conn,
                    "ai_group_settings",
                    "leader_slot",
                    "INTEGER DEFAULT 1",
                )

            # =================================================
            # BOT MIGRATION
            # =================================================

            bot_columns = self._get_columns(
                conn,
                "ai_group_bots",
            )

            if bot_columns:

                self._add_column_if_missing(
                    conn,
                    "ai_group_bots",
                    "name",
                    "TEXT DEFAULT 'MyAI'",
                )

                self._add_column_if_missing(
                    conn,
                    "ai_group_bots",
                    "power",
                    "INTEGER DEFAULT 50",
                )

                self._add_column_if_missing(
                    conn,
                    "ai_group_bots",
                    "personality",
                    "TEXT DEFAULT ''",
                )

                self._add_column_if_missing(
                    conn,
                    "ai_group_bots",
                    "speaking_style",
                    "TEXT DEFAULT ''",
                )

                self._add_column_if_missing(
                    conn,
                    "ai_group_bots",
                    "participation",
                    "INTEGER DEFAULT 100",
                )

                self._add_column_if_missing(
                    conn,
                    "ai_group_bots",
                    "memory",
                    "INTEGER DEFAULT 1",
                )

                self._add_column_if_missing(
                    conn,
                    "ai_group_bots",
                    "reply_mode",
                    "TEXT DEFAULT 'reply'",
                )

                self._add_column_if_missing(
                    conn,
                    "ai_group_bots",
                    "enabled",
                    "INTEGER DEFAULT 1",
                )

            # =================================================
            # INDEXES
            # =================================================

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_ai_group_bots_guild
                ON ai_group_bots(guild_id)
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_ai_group_stats_guild
                ON ai_group_stats(guild_id)
                """
            )

            conn.commit()

        print(
            "[AI_GROUP][DB] Database ready."
        )

    # ========================================================
    # SETTINGS
    # ========================================================

    def get_settings(
        self,
        guild_id: int,
    ) -> GroupSettings:

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT *
                FROM ai_group_settings
                WHERE guild_id = ?
                """,
                (guild_id,),
            ).fetchone()

        if row is None:

            settings = GroupSettings(
                guild_id=guild_id
            )

            self.save_settings(
                settings
            )

            return settings

        mode = (
            row["mode"]
            if row["mode"] in VALID_MODES
            else "round_robin"
        )

        return GroupSettings(

            guild_id=guild_id,

            enabled=bool(
                row["enabled"] or 0
            ),

            channel_id=row["channel_id"],

            mode=mode,

            max_turns=max(
                1,
                min(
                    20,
                    int(
                        row["max_turns"]
                        or DEFAULT_MAX_TURNS
                    ),
                ),
            ),

            cooldown=max(
                0,
                float(
                    row["cooldown"]
                    if row["cooldown"] is not None
                    else DEFAULT_COOLDOWN
                ),
            ),

            round_delay=max(
                0,
                float(
                    row["round_delay"]
                    if row["round_delay"] is not None
                    else DEFAULT_ROUND_DELAY
                ),
            ),

            leader_slot=max(
                1,
                min(
                    MAX_BOTS,
                    int(
                        row["leader_slot"]
                        or 1
                    ),
                ),
            ),
        )

    def save_settings(
        self,
        settings: GroupSettings,
    ):

        mode = (
            settings.mode
            if settings.mode in VALID_MODES
            else "round_robin"
        )

        settings.max_turns = max(
            1,
            min(
                20,
                int(settings.max_turns),
            ),
        )

        settings.cooldown = max(
            0,
            float(settings.cooldown),
        )

        settings.round_delay = max(
            0,
            float(settings.round_delay),
        )

        settings.leader_slot = max(
            1,
            min(
                MAX_BOTS,
                int(settings.leader_slot),
            ),
        )

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

                    enabled =
                        excluded.enabled,

                    channel_id =
                        excluded.channel_id,

                    mode =
                        excluded.mode,

                    max_turns =
                        excluded.max_turns,

                    cooldown =
                        excluded.cooldown,

                    round_delay =
                        excluded.round_delay,

                    leader_slot =
                        excluded.leader_slot
                """,
                (
                    settings.guild_id,
                    int(settings.enabled),
                    settings.channel_id,
                    mode,
                    settings.max_turns,
                    settings.cooldown,
                    settings.round_delay,
                    settings.leader_slot,
                ),
            )

            conn.commit()

    # ========================================================
    # BOT
    # ========================================================

    def get_bot(
        self,
        guild_id: int,
        slot: int,
    ) -> GroupBotConfig:

        slot = max(
            1,
            min(
                MAX_BOTS,
                int(slot),
            ),
        )

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT *
                FROM ai_group_bots
                WHERE guild_id = ?
                AND slot = ?
                """,
                (
                    guild_id,
                    slot,
                ),
            ).fetchone()

            if row is None:

                name = DEFAULT_NAMES[
                    slot - 1
                ]

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
                        DEFAULT_POWER,
                        "",
                        "",
                        DEFAULT_PARTICIPATION,
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

        reply_mode = (
            row["reply_mode"]
            if row["reply_mode"] in VALID_REPLY_MODES
            else "reply"
        )

        return GroupBotConfig(

            guild_id=guild_id,

            slot=slot,

            name=(
                row["name"]
                or DEFAULT_NAMES[slot - 1]
            ),

            power=max(
                1,
                min(
                    100,
                    int(
                        row["power"]
                        if row["power"] is not None
                        else DEFAULT_POWER
                    ),
                ),
            ),

            personality=(
                row["personality"]
                or ""
            ),

            speaking_style=(
                row["speaking_style"]
                or ""
            ),

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

            memory=bool(
                row["memory"]
            ),

            reply_mode=reply_mode,

            enabled=bool(
                row["enabled"]
            ),
        )

    def save_bot(
        self,
        config: GroupBotConfig,
    ):

        config.slot = max(
            1,
            min(
                MAX_BOTS,
                int(config.slot),
            ),
        )

        config.name = (
            config.name.strip()
            or DEFAULT_NAMES[
                config.slot - 1
            ]
        )

        config.name = config.name[
            :MAX_USERNAME_LENGTH
        ]

        config.power = max(
            1,
            min(
                100,
                int(config.power),
            ),
        )

        config.participation = max(
            0,
            min(
                100,
                int(config.participation),
            ),
        )

        if (
            config.reply_mode
            not in VALID_REPLY_MODES
        ):
            config.reply_mode = "reply"

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

                    name =
                        excluded.name,

                    power =
                        excluded.power,

                    personality =
                        excluded.personality,

                    speaking_style =
                        excluded.speaking_style,

                    participation =
                        excluded.participation,

                    memory =
                        excluded.memory,

                    reply_mode =
                        excluded.reply_mode,

                    enabled =
                        excluded.enabled
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

    # ========================================================
    # STATS
    # ========================================================

    def add_message_stat(
        self,
        guild_id: int,
        slot: int,
    ):

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

                    messages =
                        messages + 1
                """,
                (
                    guild_id,
                    slot,
                ),
            )

            conn.commit()

    def add_error_stat(
        self,
        guild_id: int,
        slot: int,
    ):

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

                    errors =
                        errors + 1
                """,
                (
                    guild_id,
                    slot,
                ),
            )

            conn.commit()

    def get_stats(
        self,
        guild_id: int,
        slot: int,
    ) -> tuple[int, int]:

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT
                    messages,
                    errors
                FROM ai_group_stats
                WHERE guild_id = ?
                AND slot = ?
                """,
                (
                    guild_id,
                    slot,
                ),
            ).fetchone()

        if row is None:
            return 0, 0

        return (
            int(row["messages"] or 0),
            int(row["errors"] or 0),
        )


# ============================================================
# SECONDARY DISCORD CLIENT
# ============================================================

class SecondaryBotClient(
    discord.Client
):

    def __init__(
        self,
        manager: "AIGroupManager",
        slot: int,
    ):

        intents = discord.Intents.default()

        # ----------------------------------------------------
        # Secondary bots do not process messages themselves.
        # Main bot controls the AI Group sequence.
        # ----------------------------------------------------

        intents.message_content = False

        super().__init__(
            intents=intents,
            chunk_guilds_at_startup=False,
        )

        self.manager = manager

        self.slot = slot

    async def on_ready(self):

        self.manager.online[
            self.slot
        ] = True

        self.manager.ready_events[
            self.slot
        ].set()

        try:

            user = self.user

            if user is None:

                print(
                    f"[AI_GROUP] "
                    f"Bot {self.slot} ONLINE"
                )

                return

            print(
                f"[AI_GROUP] "
                f"Bot {self.slot} ONLINE "
                f"as {user}"
            )

        except Exception:

            print(
                f"[AI_GROUP] "
                f"Bot {self.slot} ONLINE"
            )

    async def on_disconnect(self):

        self.manager.online[
            self.slot
        ] = False

        print(
            f"[AI_GROUP] "
            f"Bot {self.slot} disconnected."
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

        self.db = AIGroupDB(
            db_path
        )

        self.ai_generate = ai_generate

        # ----------------------------------------------------
        # Discord clients
        # ----------------------------------------------------

        self.clients: dict[
            int,
            SecondaryBotClient
        ] = {}

        self.client_tasks: dict[
            int,
            asyncio.Task
        ] = {}

        # ----------------------------------------------------
        # Online state
        # ----------------------------------------------------

        self.online: dict[
            int,
            bool
        ] = {
            slot: False
            for slot in range(
                1,
                MAX_BOTS + 1
            )
        }

        self.ready_events: dict[
            int,
            asyncio.Event
        ] = {
            slot: asyncio.Event()
            for slot in range(
                1,
                MAX_BOTS + 1
            )
        }

        # ----------------------------------------------------
        # Guild locks
        # ----------------------------------------------------

        self.locks: dict[
            int,
            asyncio.Lock
        ] = {}

        # ----------------------------------------------------
        # Cooldown
        # ----------------------------------------------------

        self.last_message_time: dict[
            int,
            float
        ] = {}

        # ----------------------------------------------------
        # Background group tasks
        # ----------------------------------------------------

        self.group_tasks: set[
            asyncio.Task
        ] = set()

        # ----------------------------------------------------
        # Shutdown state
        # ----------------------------------------------------

        self.shutting_down = False

        # ----------------------------------------------------
        # Round-robin state
        # ----------------------------------------------------

        self.round_robin_index: dict[
            int,
            int
        ] = {}

    # ========================================================
    # TOKEN
    # ========================================================

    def get_token(
        self,
        slot: int,
    ) -> Optional[str]:

        if slot < 1 or slot > MAX_BOTS:
            return None

        token = os.getenv(
            BOT_ENV_NAMES[
                slot - 1
            ]
        )

        if not token:
            return None

        token = token.strip()

        if not token:
            return None

        return token

    # ========================================================
    # COUNTERS
    # ========================================================

    def configured_count(self) -> int:

        return sum(
            1
            for slot in range(
                1,
                MAX_BOTS + 1
            )
            if self.get_token(slot)
        )

    def ready_count(self) -> int:

        return sum(
            1
            for slot in range(
                1,
                MAX_BOTS + 1
            )
            if self.online.get(
                slot,
                False
            )
        )

    # ========================================================
    # START CLIENTS
    # ========================================================

    async def start_clients(self):

        configured = (
            self.configured_count()
        )

        print(
            f"[AI_GROUP] "
            f"configured={configured}/{MAX_BOTS}"
        )

        for slot in range(
            1,
            MAX_BOTS + 1
        ):

            token = self.get_token(
                slot
            )

            if not token:

                print(
                    f"[AI_GROUP] "
                    f"Bot {slot}: "
                    f"{BOT_ENV_NAMES[slot - 1]} "
                    f"is missing."
                )

                continue

            if slot in self.clients:
                continue

            client = SecondaryBotClient(
                manager=self,
                slot=slot,
            )

            self.clients[
                slot
            ] = client

            task = asyncio.create_task(
                self._run_client(
                    slot,
                    client,
                    token,
                ),
                name=(
                    f"AIGroup-Bot-{slot}"
                ),
            )

            self.client_tasks[
                slot
            ] = task

    # ========================================================
    # RUN CLIENT
    # ========================================================

    async def _run_client(
        self,
        slot: int,
        client: SecondaryBotClient,
        token: str,
    ):

        try:

            await client.start(
                token
            )

        except discord.LoginFailure as exc:

            self.online[
                slot
            ] = False

            print(
                f"[AI_GROUP] "
                f"Bot {slot} failed: "
                f"LoginFailure: {exc}"
            )

        except asyncio.CancelledError:

            self.online[
                slot
            ] = False

            try:
                await client.close()
            except Exception:
                pass

            raise

        except Exception as exc:

            self.online[
                slot
            ] = False

            print(
                f"[AI_GROUP] "
                f"Bot {slot} failed: "
                f"{type(exc).__name__}: {exc}"
            )

            traceback.print_exc()

        finally:

            self.online[
                slot
            ] = False

    # ========================================================
    # REGISTER SLASH COMMAND
    # ========================================================

    async def register_command(
        self,
        tree: app_commands.CommandTree,
    ):

        @tree.command(
            name="ai_group",
            description="لوحة التحكم بمجموعة MyAI",
        )
        @app_commands.default_permissions(
            manage_guild=True
        )
        async def ai_group_command(
            interaction: discord.Interaction,
        ):

            if interaction.guild is None:

                await interaction.response.send_message(
                    "❌ هذا الأمر يعمل داخل السيرفر فقط.",
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
    # DASHBOARD EMBED
    # ========================================================

    def build_dashboard_embed(
        self,
        guild_id: int,
    ) -> discord.Embed:

        settings = self.db.get_settings(
            guild_id
        )

        if settings.enabled:
            status = "🟢 مفعلة"
        else:
            status = "🔴 متوقفة"

        if settings.channel_id:
            channel_text = (
                f"<#{settings.channel_id}>"
            )
        else:
            channel_text = "غير محدد"

        mode_names = {
            "round_robin": "Round Robin",
            "random": "Random",
            "leader": "Leader",
        }

        embed = discord.Embed(
            title="🤖 MyAI AI Group",
            description=(
                "نظام مجموعة الذكاء الاصطناعي.\n\n"

                f"**الحالة:** {status}\n"
                f"**الروم:** {channel_text}\n"
                f"**النمط:** "
                f"`{mode_names.get(settings.mode, settings.mode)}`\n"
                f"**عدد الجولات:** "
                f"`{settings.max_turns}`\n"
                f"**التأخير:** "
                f"`{settings.round_delay}s`\n"
                f"**Cooldown:** "
                f"`{settings.cooldown}s`\n\n"

                f"**البوتات المتصلة:** "
                f"`{self.ready_count()}/{MAX_BOTS}`"
            ),
            color=discord.Color.blurple(),
        )

        for slot in range(
            1,
            MAX_BOTS + 1
        ):

            cfg = self.db.get_bot(
                guild_id,
                slot,
            )

            online = self.online.get(
                slot,
                False,
            )

            if online:
                state = "🟢"
            else:
                state = "🔴"

            enabled = (
                "مفعّل"
                if cfg.enabled
                else "متوقف"
            )

            embed.add_field(
                name=(
                    f"{state} Bot {slot} "
                    f"— {cfg.name}"
                ),
                value=(
                    f"Power: `{cfg.power}/100`\n"
                    f"Participation: "
                    f"`{cfg.participation}%`\n"
                    f"State: `{enabled}`"
                ),
                inline=True,
            )

        embed.set_footer(
            text=(
                "MyAI AI Group • "
                "Professional Control System"
            )
        )

        return embed

    # ========================================================
    # REAL DISCORD USERNAME
    # ========================================================

    async def change_real_username(
        self,
        slot: int,
        new_name: str,
    ) -> tuple[bool, str]:

        client = self.clients.get(
            slot
        )

        if client is None:

            return (
                False,
                "البوت غير محمل داخل النظام.",
            )

        if not client.is_ready():

            return (
                False,
                "البوت غير متصل حاليًا.",
            )

        if client.user is None:

            return (
                False,
                "Discord لم يعطِ بيانات حساب البوت.",
            )

        new_name = (
            new_name.strip()
        )

        if not new_name:

            return (
                False,
                "اسم البوت لا يمكن أن يكون فارغًا.",
            )

        if len(new_name) > MAX_USERNAME_LENGTH:

            return (
                False,
                "اسم Discord يجب ألا يتجاوز 32 حرفًا.",
            )

        old_name = client.user.name

        if old_name == new_name:

            return (
                True,
                "الاسم الحالي هو نفسه الاسم المطلوب.",
            )

        try:

            await client.user.edit(
                username=new_name
            )

            await asyncio.sleep(
                0.5
            )

            actual_name = (
                client.user.name
                if client.user
                else new_name
            )

            return (
                True,
                (
                    f"تم تغيير اسم Discord "
                    f"فعليًا من "
                    f"`{old_name}` إلى "
                    f"`{actual_name}`."
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
                    "Discord رفض تغيير الاسم.\n"
                    f"HTTP: `{status}`\n"
                    f"التفاصيل: `{exc}`"
                ),
            )

        except Exception as exc:

            return (
                False,
                (
                    "حدث خطأ غير متوقع:\n"
                    f"`{type(exc).__name__}: {exc}`"
                ),
            )

    # ========================================================
    # EDIT BOT NAME
    # ========================================================

    async def edit_bot_name(
        self,
        guild_id: int,
        slot: int,
        new_name: str,
    ) -> tuple[bool, str]:

        new_name = (
            new_name.strip()
        )

        if not new_name:

            return (
                False,
                "الاسم فارغ.",
            )

        cfg = self.db.get_bot(
            guild_id,
            slot,
        )

        success, message = (
            await self.change_real_username(
                slot,
                new_name,
            )
        )

        if not success:
            return False, message

        cfg.name = new_name

        self.db.save_bot(
            cfg
        )

        return (
            True,
            message,
        )

    # ========================================================
    # UPDATE BOT
    # ========================================================

    def update_bot(
        self,
        guild_id: int,
        slot: int,
        **kwargs: Any,
    ):

        cfg = self.db.get_bot(
            guild_id,
            slot,
        )

        for key, value in kwargs.items():

            if hasattr(
                cfg,
                key
            ):

                setattr(
                    cfg,
                    key,
                    value,
                )

        self.db.save_bot(
            cfg
        )

    # ========================================================
    # GROUP ENABLE
    # ========================================================

    def set_enabled(
        self,
        guild_id: int,
        enabled: bool,
    ):

        settings = self.db.get_settings(
            guild_id
        )

        settings.enabled = bool(
            enabled
        )

        self.db.save_settings(
            settings
        )

    # ========================================================
    # CHANNEL
    # ========================================================

    def set_channel(
        self,
        guild_id: int,
        channel_id: Optional[int],
    ):

        settings = self.db.get_settings(
            guild_id
        )

        settings.channel_id = channel_id

        self.db.save_settings(
            settings
        )

    # ========================================================
    # MODE
    # ========================================================

    def set_mode(
        self,
        guild_id: int,
        mode: str,
    ):

        if mode not in VALID_MODES:
            mode = "round_robin"

        settings = self.db.get_settings(
            guild_id
        )

        settings.mode = mode

        self.db.save_settings(
            settings
        )

    # ========================================================
    # HANDLE MESSAGE
    # ========================================================

    async def handle_message(
        self,
        message: discord.Message,
    ) -> bool:

        if self.shutting_down:
            return False

        if message.guild is None:
            return False

        # ----------------------------------------------------
        # Only HUMAN messages start an AI Group round.
        # Secondary bot messages are never used to trigger
        # another group round.
        # ----------------------------------------------------

        if message.author.bot:
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

        now = time.monotonic()

        last = self.last_message_time.get(
            guild_id,
            0,
        )

        if (
            now - last
            < settings.cooldown
        ):

            return True

        self.last_message_time[
            guild_id
        ] = now

        lock = self.locks.setdefault(
            guild_id,
            asyncio.Lock(),
        )

        if lock.locked():
            return True

        task = asyncio.create_task(
            self._safe_run_group(
                message
            ),
            name=(
                f"AIGroup-Guild-{guild_id}"
            ),
        )

        self.group_tasks.add(
            task
        )

        task.add_done_callback(
            self.group_tasks.discard
        )

        return True

    # ========================================================
    # SAFE GROUP TASK
    # ========================================================

    async def _safe_run_group(
        self,
        message: discord.Message,
    ):

        try:

            await self.run_group(
                message
            )

        except asyncio.CancelledError:

            raise

        except Exception as exc:

            print(
                "[AI_GROUP] "
                f"Unhandled group error: "
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

        if message.guild is None:
            return

        guild_id = message.guild.id

        lock = self.locks.setdefault(
            guild_id,
            asyncio.Lock(),
        )

        async with lock:

            settings = self.db.get_settings(
                guild_id
            )

            if not settings.enabled:
                return

            # =================================================
            # COLLECT AVAILABLE BOTS
            # =================================================

            candidates = []

            for slot in range(
                1,
                MAX_BOTS + 1
            ):

                cfg = self.db.get_bot(
                    guild_id,
                    slot,
                )

                if not cfg.enabled:
                    continue

                if not self.online.get(
                    slot,
                    False
                ):
                    continue

                # ------------------------------------------------
                # Participation probability
                # ------------------------------------------------

                if (
                    cfg.participation < 100
                ):

                    roll = random.randint(
                        1,
                        100,
                    )

                    if roll > cfg.participation:
                        continue

                candidates.append(
                    cfg
                )

            if not candidates:
                return

            # =================================================
            # MODE
            # =================================================

            if settings.mode == "random":

                random.shuffle(
                    candidates
                )

            elif settings.mode == "leader":

                leader = next(
                    (
                        bot
                        for bot in candidates
                        if bot.slot
                        == settings.leader_slot
                    ),
                    None,
                )

                if leader:

                    candidates.remove(
                        leader
                    )

                    candidates.insert(
                        0,
                        leader,
                    )

            elif settings.mode == "round_robin":

                candidates.sort(
                    key=lambda x: x.slot
                )

                if candidates:

                    start_index = (
                        self.round_robin_index.get(
                            guild_id,
                            0,
                        )
                        % len(candidates)
                    )

                    candidates = (
                        candidates[start_index:]
                        +
                        candidates[:start_index]
                    )

                    self.round_robin_index[
                        guild_id
                    ] = (
                        start_index + 1
                    )

            # =================================================
            # LIMIT TURNS
            # =================================================

            candidates = candidates[
                :settings.max_turns
            ]

            if not candidates:
                return

            # =================================================
            # CONVERSATION CONTEXT
            # =================================================

            conversation = (
                message.content
                or "(رسالة فارغة)"
            )

            # -------------------------------------------------
            # This is the Discord message that the NEXT bot
            # will reply to.
            #
            # First bot -> user message
            # Second bot -> first bot message
            # Third bot -> second bot message
            # etc.
            # -------------------------------------------------

            previous_message: Optional[
                discord.Message
            ] = None

            # =================================================
            # BOT TURNS
            # =================================================

            for index, cfg in enumerate(
                candidates
            ):

                if self.shutting_down:
                    break

                client = self.clients.get(
                    cfg.slot
                )

                if client is None:
                    continue

                if not client.is_ready():
                    continue

                try:

                    # ------------------------------------------------
                    # Generate AI response
                    # ------------------------------------------------

                    result = (
                        await self.generate_for_bot(
                            message=message,
                            cfg=cfg,
                            conversation=conversation,
                        )
                    )

                    if not result:
                        continue

                    # ------------------------------------------------
                    # Send from the SECONDARY BOT account.
                    # ------------------------------------------------

                    sent = (
                        await self.send_bot_message(
                            message=message,
                            previous_message=previous_message,
                            client=client,
                            cfg=cfg,
                            text=result,
                        )
                    )

                    if sent:

                        self.db.add_message_stat(
                            guild_id,
                            cfg.slot,
                        )

                        # ------------------------------------------------
                        # Add this bot's response to the AI context.
                        # ------------------------------------------------

                        conversation += (
                            f"\n\n"
                            f"{cfg.name}: "
                            f"{result}"
                        )

                        # ------------------------------------------------
                        # IMPORTANT:
                        # The next bot replies to THIS message.
                        # ------------------------------------------------

                        previous_message = sent

                except asyncio.CancelledError:

                    raise

                except Exception as exc:

                    self.db.add_error_stat(
                        guild_id,
                        cfg.slot,
                    )

                    print(
                        "[AI_GROUP] "
                        f"Bot {cfg.slot} "
                        f"generation error: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    )

                # ------------------------------------------------
                # Delay between bots
                # ------------------------------------------------

                if (
                    index
                    < len(candidates) - 1
                ):

                    await asyncio.sleep(
                        settings.round_delay
                    )

    # ========================================================
    # GENERATE AI
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
            "تكلم بطريقة طبيعية وعفوية."
        )

        system_context = f"""
أنت Bot {cfg.slot} داخل مجموعة MyAI.

اسم الشخصية:
{cfg.name}

قوة الشخصية:
{cfg.power}/100

الشخصية:
{personality}

أسلوب الكلام:
{speaking_style}

قواعد المجموعة:

1. أنت عضو مستقل داخل مجموعة AI.
2. لا تدّعي أنك البوت الرئيسي.
3. لا تدّعي أنك إنسان.
4. لا تقل إنك تستخدم API.
5. لا تتحدث باسم بقية البوتات.
6. حافظ على شخصيتك وأسلوبك.
7. إذا كان السياق عربيًا، تحدث بالعربية.
8. اجعل الرد مناسبًا للمحادثة.
9. لا تكرر الرسالة الأصلية بلا فائدة.
10. لا تبدأ الرد باسمك إلا إذا كان ذلك طبيعيًا.
11. تفاعل مع ردود البوتات السابقة.
12. اعتبر آخر بوت متحدثًا كأنه شخص يحاورك.
13. لا تخرج عن موضوع المحادثة.
14. لا تستخدم ردودًا طويلة بلا داعٍ.
15. لا تحاول إنشاء Loop بنفسك.
16. إذا كنت ترد على بوت آخر، اجعل ردك مرتبطًا مباشرة بكلامه.
"""

        prompt = f"""
رسالة المستخدم الأصلية:

{message.content}

سياق محادثة AI Group:

{conversation}

أنت الآن Bot {cfg.slot}.

اكتب ردك على آخر رسالة في المحادثة.

اسمك:
{cfg.name}

شخصيتك:
{personality}

أسلوبك:
{speaking_style}

قوتك:
{cfg.power}/100

إذا كان هناك بوت آخر تحدث قبلك،
تفاعل مع كلامه مباشرة وكأنك ترد عليه.

لا تشرح أنك تستخدم API.
لا تقل إنك البوت الرئيسي.
لا تبدأ محادثة جديدة منفصلة عن السياق.
"""

        # =====================================================
        # MAIN.PY COMPATIBILITY
        # =====================================================
        #
        # Current main.py signature:
        #
        # ai_group_generate(
        #     guild_id,
        #     slot,
        #     user_id,
        #     channel_id,
        #     prompt,
        #     bot_name,
        #     personality,
        #     speaking_style,
        #     power,
        # )
        #
        # There is NO system_prompt parameter.
        #
        # Provider/model are taken by main.py from the
        # main MyAI configuration.
        # =====================================================

        result = await self.ai_generate(
            guild_id=message.guild.id,
            slot=cfg.slot,
            user_id=message.author.id,
            channel_id=message.channel.id,
            prompt=(
                system_context
                + "\n\n"
                + prompt
            ),
            bot_name=cfg.name,
            personality=personality,
            speaking_style=speaking_style,
            power=cfg.power,
        )

        if result is None:
            return ""

        result = str(
            result
        ).strip()

        # -----------------------------------------------------
        # Discord message limit
        # -----------------------------------------------------

        if len(result) > MAX_AI_RESPONSE_LENGTH:

            result = (
                result[
                    :MAX_AI_RESPONSE_LENGTH - 3
                ]
                + "..."
            )

        return result

    # ========================================================
    # SEND MESSAGE
    # ========================================================

    async def send_bot_message(
        self,
        message: discord.Message,
        previous_message: Optional[discord.Message],
        client: SecondaryBotClient,
        cfg: GroupBotConfig,
        text: str,
    ) -> Optional[discord.Message]:

        if not text:
            return None

        if len(text) > MAX_AI_RESPONSE_LENGTH:

            text = (
                text[
                    :MAX_AI_RESPONSE_LENGTH - 3
                ]
                + "..."
            )

        allowed_mentions = discord.AllowedMentions(
            users=False,
            roles=False,
            everyone=False,
            replied_user=False,
        )

        try:

            # =================================================
            # IMPORTANT:
            # Get the channel USING THE SECONDARY BOT CLIENT.
            #
            # This guarantees that Bot 1/2/3/4/5 actually
            # sends as its own Discord account.
            # =================================================

            channel = client.get_channel(
                message.channel.id
            )

            if channel is None:

                channel = await client.fetch_channel(
                    message.channel.id
                )

            if channel is None:

                print(
                    "[AI_GROUP] "
                    f"Bot {cfg.slot}: "
                    "channel not found."
                )

                return None

            # =================================================
            # FIRST BOT
            #
            # Reply to the user's original message.
            # =================================================

            if previous_message is None:

                try:

                    return await channel.send(
                        text,
                        reference=message,
                        mention_author=False,
                        allowed_mentions=allowed_mentions,
                    )

                except discord.HTTPException:

                    # ------------------------------------------------
                    # Fallback:
                    # If Discord refuses the message reference,
                    # send a normal message.
                    # ------------------------------------------------

                    return await channel.send(
                        text,
                        allowed_mentions=allowed_mentions,
                    )

            # =================================================
            # NEXT BOT
            #
            # Reply to the previous AI bot.
            # =================================================

            try:

                return await channel.send(
                    text,
                    reference=previous_message,
                    mention_author=False,
                    allowed_mentions=allowed_mentions,
                )

            except discord.HTTPException:

                # ------------------------------------------------
                # Fallback if Discord refuses the reference.
                # ------------------------------------------------

                return await channel.send(
                    text,
                    allowed_mentions=allowed_mentions,
                )

        except discord.Forbidden as exc:

            print(
                "[AI_GROUP] "
                f"Bot {cfg.slot} "
                f"permission error: {exc}"
            )

            return None

        except discord.NotFound as exc:

            print(
                "[AI_GROUP] "
                f"Bot {cfg.slot} "
                f"channel/message not found: {exc}"
            )

            return None

        except discord.HTTPException as exc:

            print(
                "[AI_GROUP] "
                f"Bot {cfg.slot} "
                f"failed to send message: {exc}"
            )

            return None

        except Exception as exc:

            print(
                "[AI_GROUP] "
                f"Bot {cfg.slot} "
                f"unexpected send error: "
                f"{type(exc).__name__}: {exc}"
            )

            traceback.print_exc()

            return None

    # ========================================================
    # ALL STATS
    # ========================================================

    def get_all_stats(
        self,
        guild_id: int,
    ) -> list[dict[str, Any]]:

        result = []

        for slot in range(
            1,
            MAX_BOTS + 1
        ):

            cfg = self.db.get_bot(
                guild_id,
                slot,
            )

            messages, errors = (
                self.db.get_stats(
                    guild_id,
                    slot,
                )
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
                    "enabled": cfg.enabled,
                }
            )

        return result

    # ========================================================
    # SHUTDOWN
    # ========================================================

    async def stop_clients(self):

        self.shutting_down = True

        # ----------------------------------------------------
        # Cancel group tasks
        # ----------------------------------------------------

        tasks = list(
            self.group_tasks
        )

        for task in tasks:

            if not task.done():
                task.cancel()

        if tasks:

            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        self.group_tasks.clear()

        # ----------------------------------------------------
        # Close secondary clients
        # ----------------------------------------------------

        for slot, client in list(
            self.clients.items()
        ):

            try:

                await client.close()

            except Exception:
                pass

            self.online[
                slot
            ] = False

        self.clients.clear()

        # ----------------------------------------------------
        # Cancel client tasks
        # ----------------------------------------------------

        for slot, task in list(
            self.client_tasks.items()
        ):

            if not task.done():

                task.cancel()

        if self.client_tasks:

            await asyncio.gather(
                *self.client_tasks.values(),
                return_exceptions=True,
            )

        self.client_tasks.clear()

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

        lock = self.locks.get(
            guild_id
        )

        # The running task will finish its
        # current await point safely.
        if lock and lock.locked():
            pass


# ============================================================
# DASHBOARD
# ============================================================

class GroupDashboardView(
    discord.ui.View
):

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

    # ========================================================
    # ENABLE
    # ========================================================

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

    # ========================================================
    # DISABLE
    # ========================================================

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

    # ========================================================
    # BOTS
    # ========================================================

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

        embed = discord.Embed(
            title="🤖 إدارة بوتات AI Group",
            description=(
                "اختر البوت الذي تريد التحكم فيه:"
            ),
            color=discord.Color.blurple(),
        )

        await interaction.response.edit_message(
            embed=embed,
            view=BotPickerView(
                self.manager,
                self.guild_id,
            ),
        )

    # ========================================================
    # SETTINGS
    # ========================================================

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

        embed = discord.Embed(
            title="⚙️ إعدادات AI Group",
            description=(
                "تحكم في طريقة تشغيل المجموعة."
            ),
            color=discord.Color.blurple(),
        )

        await interaction.response.edit_message(
            embed=embed,
            view=GroupSettingsView(
                self.manager,
                self.guild_id,
            ),
        )

    # ========================================================
    # STATS
    # ========================================================

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

        stats = (
            self.manager.get_all_stats(
                self.guild_id
            )
        )

        lines = []

        for item in stats:

            status = (
                "🟢"
                if item["online"]
                else "🔴"
            )

            enabled = (
                "مفعّل"
                if item["enabled"]
                else "متوقف"
            )

            lines.append(
                (
                    f"{status} **Bot "
                    f"{item['slot']} — "
                    f"{item['name']}**\n"
                    f"الحالة: `{enabled}`\n"
                    f"الرسائل: "
                    f"`{item['messages']}`\n"
                    f"الأخطاء: "
                    f"`{item['errors']}`"
                )
            )

        embed = discord.Embed(
            title="📊 AI Group Statistics",
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

class BotPickerView(
    discord.ui.View
):

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

        for slot in range(
            1,
            MAX_BOTS + 1
        ):

            cfg = manager.db.get_bot(
                guild_id,
                slot,
            )

            button = discord.ui.Button(
                label=(
                    f"Bot {slot}: "
                    f"{cfg.name[:60]}"
                ),
                style=discord.ButtonStyle.primary,
                row=(slot - 1) // 2,
            )

            async def callback(
                interaction: discord.Interaction,
                selected_slot=slot,
            ):

                selected_cfg = (
                    self.manager.db.get_bot(
                        self.guild_id,
                        selected_slot,
                    )
                )

                online = (
                    self.manager.online.get(
                        selected_slot,
                        False,
                    )
                )

                status = (
                    "🟢 ONLINE"
                    if online
                    else "🔴 OFFLINE"
                )

                embed = discord.Embed(
                    title=(
                        f"🤖 Bot "
                        f"{selected_slot}"
                    ),
                    description=(
                        f"**Discord:** "
                        f"`{selected_cfg.name}`\n"
                        f"**الحالة:** {status}\n\n"
                        f"**Power:** "
                        f"`{selected_cfg.power}/100`\n"
                        f"**Participation:** "
                        f"`{selected_cfg.participation}%`\n"
                        f"**Enabled:** "
                        f"`{selected_cfg.enabled}`"
                    ),
                    color=discord.Color.blurple(),
                )

                await interaction.response.edit_message(
                    embed=embed,
                    view=BotEditView(
                        self.manager,
                        self.guild_id,
                        selected_slot,
                    ),
                )

            button.callback = callback

            self.add_item(
                button
            )

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

        self.add_item(
            back
        )


# ============================================================
# BOT EDIT VIEW
# ============================================================

class BotEditView(
    discord.ui.View
):

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

    # ========================================================
    # REAL DISCORD NAME
    # ========================================================

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

    # ========================================================
    # TOGGLE
    # ========================================================

    @discord.ui.button(
        label="تفعيل / تعطيل",
        emoji="🔘",
        style=discord.ButtonStyle.secondary,
        row=0,
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

        self.manager.db.save_bot(
            cfg
        )

        state = (
            "🟢 مفعّل"
            if cfg.enabled
            else "🔴 متوقف"
        )

        await interaction.response.send_message(
            (
                f"Bot {self.slot}: "
                f"{state}"
            ),
            ephemeral=True,
        )

    # ========================================================
    # PERSONALITY
    # ========================================================

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

    # ========================================================
    # POWER
    # ========================================================

    @discord.ui.button(
        label="القوة",
        emoji="⚡",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def power(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            BotPowerModal(
                self.manager,
                self.guild_id,
                self.slot,
            )
        )

    # ========================================================
    # BACK
    # ========================================================

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
                    "اختر البوت الذي تريد التحكم فيه:"
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

class BotNameModal(
    discord.ui.Modal
):

    def __init__(
        self,
        manager: AIGroupManager,
        guild_id: int,
        slot: int,
    ):

        super().__init__(
            title=(
                f"تغيير اسم Bot {slot}"
            )
        )

        self.manager = manager

        self.guild_id = guild_id

        self.slot = slot

        cfg = manager.db.get_bot(
            guild_id,
            slot,
        )

        self.name_input = (
            discord.ui.TextInput(
                label="اسم Discord الجديد",
                placeholder=(
                    "اكتب الاسم الجديد..."
                ),
                default=cfg.name,
                min_length=1,
                max_length=32,
                required=True,
            )
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

        success, message = (
            await self.manager.edit_bot_name(
                self.guild_id,
                self.slot,
                new_name,
            )
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

class BotPersonalityModal(
    discord.ui.Modal
):

    def __init__(
        self,
        manager: AIGroupManager,
        guild_id: int,
        slot: int,
    ):

        super().__init__(
            title=(
                f"شخصية Bot {slot}"
            )
        )

        self.manager = manager

        self.guild_id = guild_id

        self.slot = slot

        cfg = manager.db.get_bot(
            guild_id,
            slot,
        )

        self.personality_input = (
            discord.ui.TextInput(
                label="الشخصية",
                placeholder=(
                    "مثال: مرح، هادئ، ذكي..."
                ),
                default=cfg.personality,
                max_length=1000,
                required=False,
                style=discord.TextStyle.paragraph,
            )
        )

        self.style_input = (
            discord.ui.TextInput(
                label="أسلوب الكلام",
                placeholder=(
                    "مثال: عفوي، مختصر..."
                ),
                default=cfg.speaking_style,
                max_length=1000,
                required=False,
                style=discord.TextStyle.paragraph,
            )
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
            (
                "✅ تم حفظ الشخصية "
                "وأسلوب الكلام."
            ),
            ephemeral=True,
        )


# ============================================================
# POWER MODAL
# ============================================================

class BotPowerModal(
    discord.ui.Modal
):

    def __init__(
        self,
        manager: AIGroupManager,
        guild_id: int,
        slot: int,
    ):

        super().__init__(
            title=(
                f"قوة Bot {slot}"
            )
        )

        self.manager = manager

        self.guild_id = guild_id

        self.slot = slot

        cfg = manager.db.get_bot(
            guild_id,
            slot,
        )

        self.power_input = (
            discord.ui.TextInput(
                label="Power من 1 إلى 100",
                placeholder="50",
                default=str(
                    cfg.power
                ),
                min_length=1,
                max_length=3,
                required=True,
            )
        )

        self.add_item(
            self.power_input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):

        try:

            power = int(
                str(
                    self.power_input.value
                ).strip()
            )

        except ValueError:

            await interaction.response.send_message(
                "❌ اكتب رقمًا من 1 إلى 100.",
                ephemeral=True,
            )

            return

        if power < 1 or power > 100:

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

        self.manager.db.save_bot(
            cfg
        )

        await interaction.response.send_message(
            (
                f"✅ تم تغيير قوة Bot "
                f"{self.slot} إلى "
                f"`{power}/100`."
            ),
            ephemeral=True,
        )


# ============================================================
# GROUP SETTINGS VIEW
# ============================================================

class GroupSettingsView(
    discord.ui.View
):

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

    # ========================================================
    # MODE SELECT
    # ========================================================

    @discord.ui.select(
        placeholder="اختر نمط المجموعة",
        options=[
            discord.SelectOption(
                label="Round Robin",
                value="round_robin",
                description=(
                    "البوتات تتحدث بالترتيب"
                ),
            ),
            discord.SelectOption(
                label="Random",
                value="random",
                description=(
                    "اختيار البوتات عشوائيًا"
                ),
            ),
            discord.SelectOption(
                label="Leader",
                value="leader",
                description=(
                    "البوت القائد يبدأ"
                ),
            ),
        ],
        row=0,
    )
    async def mode_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ):

        mode = select.values[0]

        self.manager.set_mode(
            self.guild_id,
            mode,
        )

        await interaction.response.send_message(
            (
                f"✅ تم اختيار النمط "
                f"`{mode}`."
            ),
            ephemeral=True,
        )

    # ========================================================
    # CURRENT CHANNEL
    # ========================================================

    @discord.ui.button(
        label="تعيين هذا الروم",
        emoji="📢",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def current_channel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if interaction.channel is None:

            await interaction.response.send_message(
                "❌ لم أستطع تحديد الروم.",
                ephemeral=True,
            )

            return

        self.manager.set_channel(
            self.guild_id,
            interaction.channel.id,
        )

        await interaction.response.send_message(
            (
                "✅ تم تعيين هذا الروم "
                "لمجموعة AI."
            ),
            ephemeral=True,
        )

    # ========================================================
    # BACK
    # ========================================================

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
# BACK TO DASHBOARD
# ============================================================

class BackToDashboardView(
    discord.ui.View
):

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


# ============================================================
# END
# ============================================================
