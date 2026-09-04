import os
import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional


# ============================================================
# CONFIG
# ============================================================

DB_PATH = os.getenv(
    "DATABASE_PATH",
    os.getenv("DB_PATH", "myai.db")
)

CURRENT_GOOGLE_MODEL = "gemini-3.5-flash-lite"

DEFAULT_SERVER_CHARACTER = "مساعد السيرفر جيميناي"
DEFAULT_DM_CHARACTER = "مساعد MyAI"


# ============================================================
# DEFAULT ADVANCED SETTINGS
# ============================================================

DEFAULT_ADVANCED_SETTINGS = {
    "memory_enabled": True,
    "history_limit": 20,
    "response_length": 1200,
    "timeout": 35,
    "security_enabled": True,
    "bot_chat_enabled": True,
    "bot_chat_max_chain": 6,
    "bot_chat_cooldown": 2.0,
    "allow_members": [],
    "deny_members": [],
    "sensitive_keywords": [
        "كيف أؤذي",
        "كيف اقتل",
        "طريقة قتل",
        "صنع سلاح",
        "صناعة سلاح",
        "متفجرات",
        "تفجير",
        "how to kill",
        "how to hurt",
        "make a weapon",
        "explosive",
    ],
}


# ============================================================
# HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalize_bool(
    value,
    default=False
):

    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    text = str(
        value
    ).strip().lower()

    if text in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
        "enable",
    }:
        return True

    if text in {
        "0",
        "false",
        "no",
        "off",
        "disabled",
        "disable",
    }:
        return False

    return default


def safe_json_loads(
    value,
    default
):

    if value is None:
        return default

    if isinstance(
        value,
        (list, dict)
    ):
        return value

    try:
        return json.loads(value)
    except Exception:
        return default


def normalize_list(
    value
):

    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, str):

        value = value.strip()

        if not value:
            return []

        parsed = safe_json_loads(
            value,
            None
        )

        if isinstance(
            parsed,
            list
        ):
            return parsed

        return [
            item.strip()
            for item in value.split(",")
            if item.strip()
        ]

    return [value]


def row_to_dict(
    row
):

    if row is None:
        return None

    if isinstance(
        row,
        dict
    ):
        return row

    try:
        return dict(row)

    except Exception:

        try:

            return {
                key: row[key]
                for key in row.keys()
            }

        except Exception:

            return {}


# ============================================================
# DATABASE
# ============================================================

class Database:

    def __init__(
        self,
        path: Optional[str] = None
    ):

        self.path = (
            path
            or DB_PATH
        )

        self.conn = sqlite3.connect(
            self.path,
            check_same_thread=False,
            timeout=30,
        )

        self.conn.row_factory = sqlite3.Row

        self.conn.execute(
            "PRAGMA journal_mode=WAL"
        )

        self.conn.execute(
            "PRAGMA foreign_keys=ON"
        )

        self.conn.execute(
            "PRAGMA busy_timeout=30000"
        )

        self._create_tables()
        self._migrate_tables()
        self._repair_database()

    # ========================================================
    # TABLE CREATION
    # ========================================================

    def _create_tables(
        self
    ):

        # ----------------------------------------------------
        # CHARACTERS
        # ----------------------------------------------------

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                personality TEXT DEFAULT '',
                system_prompt TEXT DEFAULT '',
                character_type TEXT DEFAULT 'normal',
                custom_instructions TEXT DEFAULT '',
                speaking_style TEXT DEFAULT '',
                provider TEXT DEFAULT 'google',
                model TEXT DEFAULT 'gemini-3.5-flash-lite',
                created_by INTEGER DEFAULT 0,
                created_at TEXT,
                UNIQUE(guild_id, name)
            )
        """)

        # ----------------------------------------------------
        # MESSAGES
        # guild_id = 0 => DM memory
        # ----------------------------------------------------

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                character_name TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT
            )
        """)

        # ----------------------------------------------------
        # GUILD SETTINGS
        # ----------------------------------------------------

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                active_character TEXT,
                active_provider TEXT DEFAULT 'google',
                active_model TEXT DEFAULT 'gemini-3.5-flash-lite',
                ai_enabled INTEGER DEFAULT 1,
                ai_channel_id INTEGER,
                ai_mode TEXT DEFAULT 'normal',
                reply_type TEXT DEFAULT 'mention',
                permission_preset TEXT DEFAULT 'default',
                updated_at TEXT
            )
        """)

        # ----------------------------------------------------
        # AI CONFIG
        # ----------------------------------------------------

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_config (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                channel_id INTEGER,
                mode TEXT DEFAULT 'normal',
                reply_type TEXT DEFAULT 'mention',
                character_name TEXT,
                permission_preset TEXT DEFAULT 'default',
                provider TEXT DEFAULT 'google',
                model TEXT DEFAULT 'gemini-3.5-flash-lite',
                allow_management INTEGER DEFAULT 1,
                allow_channel_management INTEGER DEFAULT 1,
                allow_role_management INTEGER DEFAULT 1,
                updated_at TEXT
            )
        """)

        # ----------------------------------------------------
        # BASIC DM SETTINGS
        # ----------------------------------------------------

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_dm_settings (
                user_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                active_character TEXT,
                reply_mode TEXT DEFAULT 'always',
                mode TEXT DEFAULT 'normal',
                history_limit INTEGER DEFAULT 20,
                response_length INTEGER DEFAULT 1200,
                updated_at TEXT
            )
        """)

        # ----------------------------------------------------
        # ADVANCED SETTINGS
        # ----------------------------------------------------

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_advanced_settings (
                guild_id INTEGER PRIMARY KEY,
                memory_enabled INTEGER DEFAULT 1,
                history_limit INTEGER DEFAULT 20,
                response_length INTEGER DEFAULT 1200,
                timeout INTEGER DEFAULT 35,
                security_enabled INTEGER DEFAULT 1,
                bot_chat_enabled INTEGER DEFAULT 1,
                bot_chat_max_chain INTEGER DEFAULT 6,
                bot_chat_cooldown REAL DEFAULT 2.0,
                allow_members TEXT DEFAULT '[]',
                deny_members TEXT DEFAULT '[]',
                sensitive_keywords TEXT DEFAULT '[]',
                updated_at TEXT
            )
        """)

        # ----------------------------------------------------
        # USER CHARACTER SETTINGS
        # ----------------------------------------------------

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS user_character_settings (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                character_name TEXT,
                updated_at TEXT,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        # ----------------------------------------------------
        # DM CHARACTERS
        # كل شخصية هنا مرتبطة بمستخدم واحد.
        # ----------------------------------------------------

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS dm_characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                personality TEXT DEFAULT '',
                system_prompt TEXT DEFAULT '',
                character_type TEXT DEFAULT 'normal',
                custom_instructions TEXT DEFAULT '',
                speaking_style TEXT DEFAULT '',
                provider TEXT DEFAULT 'google',
                model TEXT DEFAULT 'gemini-3.5-flash-lite',
                created_at TEXT,
                UNIQUE(user_id, name)
            )
        """)

        # ----------------------------------------------------
        # INDEXES
        # ----------------------------------------------------

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_characters_guild
            ON characters(guild_id)
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_guild_channel
            ON messages(guild_id, channel_id)
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_user
            ON messages(guild_id, user_id)
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_created
            ON messages(created_at)
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_character_settings
            ON user_character_settings(guild_id, user_id)
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dm_characters_user
            ON dm_characters(user_id)
        """)

        self.conn.commit()

    # ========================================================
    # MIGRATIONS
    # ========================================================

    def _column_exists(
        self,
        table_name,
        column_name
    ):

        rows = self.conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()

        return any(
            item["name"] == column_name
            for item in rows
        )

    def _add_column_if_missing(
        self,
        table_name,
        column_name,
        column_definition
    ):

        if not self._column_exists(
            table_name,
            column_name
        ):

            self.conn.execute(
                f"""
                ALTER TABLE {table_name}
                ADD COLUMN {column_name} {column_definition}
                """
            )

    def _migrate_tables(
        self
    ):

        # ----------------------------------------------------
        # CHARACTERS
        # ----------------------------------------------------

        self._add_column_if_missing(
            "characters",
            "description",
            "TEXT DEFAULT ''"
        )

        self._add_column_if_missing(
            "characters",
            "personality",
            "TEXT DEFAULT ''"
        )

        self._add_column_if_missing(
            "characters",
            "system_prompt",
            "TEXT DEFAULT ''"
        )

        self._add_column_if_missing(
            "characters",
            "character_type",
            "TEXT DEFAULT 'normal'"
        )

        self._add_column_if_missing(
            "characters",
            "custom_instructions",
            "TEXT DEFAULT ''"
        )

        self._add_column_if_missing(
            "characters",
            "speaking_style",
            "TEXT DEFAULT ''"
        )

        self._add_column_if_missing(
            "characters",
            "provider",
            "TEXT DEFAULT 'google'"
        )

        self._add_column_if_missing(
            "characters",
            "model",
            "TEXT DEFAULT 'gemini-3.5-flash-lite'"
        )

        self._add_column_if_missing(
            "characters",
            "created_by",
            "INTEGER DEFAULT 0"
        )

        self._add_column_if_missing(
            "characters",
            "created_at",
            "TEXT"
        )

        # ----------------------------------------------------
        # MESSAGES
        # ----------------------------------------------------

        self._add_column_if_missing(
            "messages",
            "character_name",
            "TEXT"
        )

        self._add_column_if_missing(
            "messages",
            "created_at",
            "TEXT"
        )

        # ----------------------------------------------------
        # GUILD SETTINGS
        # ----------------------------------------------------

        self._add_column_if_missing(
            "guild_settings",
            "active_character",
            "TEXT"
        )

        self._add_column_if_missing(
            "guild_settings",
            "active_provider",
            "TEXT DEFAULT 'google'"
        )

        self._add_column_if_missing(
            "guild_settings",
            "active_model",
            "TEXT DEFAULT 'gemini-3.5-flash-lite'"
        )

        self._add_column_if_missing(
            "guild_settings",
            "ai_enabled",
            "INTEGER DEFAULT 1"
        )

        self._add_column_if_missing(
            "guild_settings",
            "ai_channel_id",
            "INTEGER"
        )

        self._add_column_if_missing(
            "guild_settings",
            "ai_mode",
            "TEXT DEFAULT 'normal'"
        )

        self._add_column_if_missing(
            "guild_settings",
            "reply_type",
            "TEXT DEFAULT 'mention'"
        )

        self._add_column_if_missing(
            "guild_settings",
            "permission_preset",
            "TEXT DEFAULT 'default'"
        )

        self._add_column_if_missing(
            "guild_settings",
            "updated_at",
            "TEXT"
        )

        # ----------------------------------------------------
        # AI CONFIG
        # ----------------------------------------------------

        self._add_column_if_missing(
            "ai_config",
            "enabled",
            "INTEGER DEFAULT 1"
        )

        self._add_column_if_missing(
            "ai_config",
            "channel_id",
            "INTEGER"
        )

        self._add_column_if_missing(
            "ai_config",
            "mode",
            "TEXT DEFAULT 'normal'"
        )

        self._add_column_if_missing(
            "ai_config",
            "reply_type",
            "TEXT DEFAULT 'mention'"
        )

        self._add_column_if_missing(
            "ai_config",
            "character_name",
            "TEXT"
        )

        self._add_column_if_missing(
            "ai_config",
            "permission_preset",
            "TEXT DEFAULT 'default'"
        )

        self._add_column_if_missing(
            "ai_config",
            "provider",
            "TEXT DEFAULT 'google'"
        )

        self._add_column_if_missing(
            "ai_config",
            "model",
            "TEXT DEFAULT 'gemini-3.5-flash-lite'"
        )

        self._add_column_if_missing(
            "ai_config",
            "allow_management",
            "INTEGER DEFAULT 1"
        )

        self._add_column_if_missing(
            "ai_config",
            "allow_channel_management",
            "INTEGER DEFAULT 1"
        )

        self._add_column_if_missing(
            "ai_config",
            "allow_role_management",
            "INTEGER DEFAULT 1"
        )

        self._add_column_if_missing(
            "ai_config",
            "updated_at",
            "TEXT"
        )

        # ----------------------------------------------------
        # DM SETTINGS
        # ----------------------------------------------------

        self._add_column_if_missing(
            "ai_dm_settings",
            "enabled",
            "INTEGER DEFAULT 0"
        )

        self._add_column_if_missing(
            "ai_dm_settings",
            "active_character",
            "TEXT"
        )

        self._add_column_if_missing(
            "ai_dm_settings",
            "reply_mode",
            "TEXT DEFAULT 'always'"
        )

        self._add_column_if_missing(
            "ai_dm_settings",
            "mode",
            "TEXT DEFAULT 'normal'"
        )

        self._add_column_if_missing(
            "ai_dm_settings",
            "history_limit",
            "INTEGER DEFAULT 20"
        )

        self._add_column_if_missing(
            "ai_dm_settings",
            "response_length",
            "INTEGER DEFAULT 1200"
        )

        self._add_column_if_missing(
            "ai_dm_settings",
            "updated_at",
            "TEXT"
        )

        # ----------------------------------------------------
        # ADVANCED
        # ----------------------------------------------------

        self._add_column_if_missing(
            "ai_advanced_settings",
            "memory_enabled",
            "INTEGER DEFAULT 1"
        )

        self._add_column_if_missing(
            "ai_advanced_settings",
            "history_limit",
            "INTEGER DEFAULT 20"
        )

        self._add_column_if_missing(
            "ai_advanced_settings",
            "response_length",
            "INTEGER DEFAULT 1200"
        )

        self._add_column_if_missing(
            "ai_advanced_settings",
            "timeout",
            "INTEGER DEFAULT 35"
        )

        self._add_column_if_missing(
            "ai_advanced_settings",
            "security_enabled",
            "INTEGER DEFAULT 1"
        )

        self._add_column_if_missing(
            "ai_advanced_settings",
            "bot_chat_enabled",
            "INTEGER DEFAULT 1"
        )

        self._add_column_if_missing(
            "ai_advanced_settings",
            "bot_chat_max_chain",
            "INTEGER DEFAULT 6"
        )

        self._add_column_if_missing(
            "ai_advanced_settings",
            "bot_chat_cooldown",
            "REAL DEFAULT 2.0"
        )

        self._add_column_if_missing(
            "ai_advanced_settings",
            "allow_members",
            "TEXT DEFAULT '[]'"
        )

        self._add_column_if_missing(
            "ai_advanced_settings",
            "deny_members",
            "TEXT DEFAULT '[]'"
        )

        self._add_column_if_missing(
            "ai_advanced_settings",
            "sensitive_keywords",
            "TEXT DEFAULT '[]'"
        )

        self._add_column_if_missing(
            "ai_advanced_settings",
            "updated_at",
            "TEXT"
        )

        self.conn.commit()

    # ========================================================
    # DATABASE REPAIR
    # ========================================================

    def _repair_database(
        self
    ):

        now = utc_now()

        self.conn.execute(
            """
            UPDATE characters
            SET created_at = ?
            WHERE created_at IS NULL
               OR created_at = ''
            """,
            (now,)
        )

        self.conn.execute(
            """
            UPDATE characters
            SET provider = 'google'
            WHERE provider IS NULL
               OR provider = ''
            """
        )

        self.conn.execute(
            """
            UPDATE characters
            SET model = ?
            WHERE model IS NULL
               OR model = ''
            """,
            (CURRENT_GOOGLE_MODEL,)
        )

        self.conn.execute(
            """
            UPDATE characters
            SET character_type = 'normal'
            WHERE character_type IS NULL
               OR character_type = ''
            """
        )

        self.conn.execute(
            """
            UPDATE guild_settings
            SET active_provider = 'google'
            WHERE active_provider IS NULL
               OR active_provider = ''
            """
        )

        self.conn.execute(
            """
            UPDATE guild_settings
            SET active_model = ?
            WHERE active_model IS NULL
               OR active_model = ''
            """,
            (CURRENT_GOOGLE_MODEL,)
        )

        self.conn.execute(
            """
            UPDATE guild_settings
            SET ai_enabled = 1
            WHERE ai_enabled IS NULL
            """
        )

        self.conn.execute(
            """
            UPDATE guild_settings
            SET ai_mode = 'normal'
            WHERE ai_mode IS NULL
               OR ai_mode = ''
            """
        )

        self.conn.execute(
            """
            UPDATE guild_settings
            SET reply_type = 'mention'
            WHERE reply_type IS NULL
               OR reply_type = ''
            """
        )

        self.conn.execute(
            """
            UPDATE ai_config
            SET provider = 'google'
            WHERE provider IS NULL
               OR provider = ''
            """
        )

        self.conn.execute(
            """
            UPDATE ai_config
            SET model = ?
            WHERE model IS NULL
               OR model = ''
            """,
            (CURRENT_GOOGLE_MODEL,)
        )

        self.conn.execute(
            """
            UPDATE ai_config
            SET mode = 'normal'
            WHERE mode IS NULL
               OR mode = ''
            """
        )

        self.conn.execute(
            """
            UPDATE ai_config
            SET reply_type = 'mention'
            WHERE reply_type IS NULL
               OR reply_type = ''
            """
        )

        self.conn.execute(
            """
            UPDATE ai_dm_settings
            SET enabled = 0
            WHERE enabled IS NULL
            """
        )

        self.conn.execute(
            """
            UPDATE ai_dm_settings
            SET reply_mode = 'always'
            WHERE reply_mode IS NULL
               OR reply_mode = ''
            """
        )

        self.conn.execute(
            """
            UPDATE ai_dm_settings
            SET mode = 'normal'
            WHERE mode IS NULL
               OR mode = ''
            """
        )

        self.conn.execute(
            """
            UPDATE ai_dm_settings
            SET history_limit = 20
            WHERE history_limit IS NULL
            """
        )

        self.conn.execute(
            """
            UPDATE ai_dm_settings
            SET response_length = 1200
            WHERE response_length IS NULL
            """
        )

        self.conn.execute(
            """
            UPDATE ai_advanced_settings
            SET memory_enabled = 1
            WHERE memory_enabled IS NULL
            """
        )

        self.conn.execute(
            """
            UPDATE ai_advanced_settings
            SET history_limit = 20
            WHERE history_limit IS NULL
            """
        )

        self.conn.execute(
            """
            UPDATE ai_advanced_settings
            SET response_length = 1200
            WHERE response_length IS NULL
            """
        )

        self.conn.execute(
            """
            UPDATE ai_advanced_settings
            SET timeout = 35
            WHERE timeout IS NULL
            """
        )

        self.conn.execute(
            """
            UPDATE ai_advanced_settings
            SET security_enabled = 1
            WHERE security_enabled IS NULL
            """
        )

        self.conn.execute(
            """
            UPDATE ai_advanced_settings
            SET bot_chat_enabled = 1
            WHERE bot_chat_enabled IS NULL
            """
        )

        self.conn.execute(
            """
            UPDATE ai_advanced_settings
            SET bot_chat_max_chain = 6
            WHERE bot_chat_max_chain IS NULL
            """
        )

        self.conn.execute(
            """
            UPDATE ai_advanced_settings
            SET bot_chat_cooldown = 2.0
            WHERE bot_chat_cooldown IS NULL
            """
        )

        self.conn.execute(
            """
            UPDATE ai_advanced_settings
            SET allow_members = '[]'
            WHERE allow_members IS NULL
               OR allow_members = ''
            """
        )

        self.conn.execute(
            """
            UPDATE ai_advanced_settings
            SET deny_members = '[]'
            WHERE deny_members IS NULL
               OR deny_members = ''
            """
        )

        self.conn.execute(
            """
            UPDATE ai_advanced_settings
            SET sensitive_keywords = ?
            WHERE sensitive_keywords IS NULL
               OR sensitive_keywords = ''
            """,
            (
                json.dumps(
                    DEFAULT_ADVANCED_SETTINGS[
                        "sensitive_keywords"
                    ],
                    ensure_ascii=False
                ),
            )
        )

        self.conn.commit()

    # ========================================================
    # CHARACTER METHODS
    # ========================================================

    def create_character(
        self,
        guild_id: int,
        name: str,
        description: str = "",
        personality: str = "",
        system_prompt: str = "",
        character_type: str = "normal",
        custom_instructions: str = "",
        speaking_style: str = "",
        created_by: int = 0,
        provider: str = "google",
        model: str = CURRENT_GOOGLE_MODEL,
    ):

        name = (
            name or ""
        ).strip()

        if not name:

            raise ValueError(
                "Character name cannot be empty."
            )

        character_type = (
            character_type
            or "normal"
        ).strip()

        provider = (
            provider
            or "google"
        ).strip().lower()

        model = (
            model
            or CURRENT_GOOGLE_MODEL
        ).strip()

        now = utc_now()

        cursor = self.conn.execute(
            """
            INSERT INTO characters (
                guild_id,
                name,
                description,
                personality,
                system_prompt,
                character_type,
                custom_instructions,
                speaking_style,
                provider,
                model,
                created_by,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                name,
                description or "",
                personality or "",
                system_prompt or "",
                character_type,
                custom_instructions or "",
                speaking_style or "",
                provider,
                model,
                created_by or 0,
                now
            )
        )

        self.conn.commit()

        return cursor.lastrowid

    def get_character(
        self,
        guild_id: int,
        name: str
    ):

        if not name:
            return None

        return self.conn.execute(
            """
            SELECT *
            FROM characters
            WHERE guild_id = ?
              AND name = ?
            LIMIT 1
            """,
            (
                guild_id,
                name
            )
        ).fetchone()

    def get_character_by_id(
        self,
        character_id: int
    ):

        return self.conn.execute(
            """
            SELECT *
            FROM characters
            WHERE id = ?
            LIMIT 1
            """,
            (character_id,)
        ).fetchone()

    def get_characters(
        self,
        guild_id: int
    ):

        return self.conn.execute(
            """
            SELECT *
            FROM characters
            WHERE guild_id = ?
            ORDER BY
                CASE
                    WHEN created_by = 0 THEN 0
                    ELSE 1
                END,
                name COLLATE NOCASE ASC
            """,
            (guild_id,)
        ).fetchall()

    def list_characters(
        self,
        guild_id: int
    ):

        return self.get_characters(
            guild_id
        )

    def get_user_characters(
        self,
        guild_id: int,
        user_id: int
    ):

        return self.conn.execute(
            """
            SELECT *
            FROM characters
            WHERE guild_id = ?
              AND created_by = ?
            ORDER BY name COLLATE NOCASE ASC
            """,
            (
                guild_id,
                user_id
            )
        ).fetchall()

    def update_character(
        self,
        guild_id: int,
        name: str,
        **kwargs
    ):

        allowed = {
            "description",
            "personality",
            "system_prompt",
            "character_type",
            "custom_instructions",
            "speaking_style",
            "provider",
            "model",
        }

        updates = []
        values = []

        for key, value in kwargs.items():

            if key not in allowed:
                continue

            if key == "provider":

                value = (
                    value
                    or "google"
                ).strip().lower()

            elif key == "model":

                value = (
                    value
                    or CURRENT_GOOGLE_MODEL
                ).strip()

            elif key == "character_type":

                value = (
                    value
                    or "normal"
                ).strip()

            updates.append(
                f"{key} = ?"
            )

            values.append(
                value or ""
            )

        if not updates:
            return False

        values.extend([
            guild_id,
            name
        ])

        cursor = self.conn.execute(
            f"""
            UPDATE characters
            SET {", ".join(updates)}
            WHERE guild_id = ?
              AND name = ?
            """,
            values
        )

        self.conn.commit()

        return cursor.rowcount > 0

    def delete_character(
        self,
        guild_id: int,
        character_name: str
    ):

        character = self.get_character(
            guild_id,
            character_name
        )

        if not character:
            return False

        data = row_to_dict(
            character
        ) or {}

        owner_id = data.get(
            "created_by",
            0
        )

        if owner_id == 0:
            return False

        self.conn.execute(
            """
            DELETE FROM characters
            WHERE guild_id = ?
              AND name = ?
            """,
            (
                guild_id,
                character_name
            )
        )

        self.conn.execute(
            """
            DELETE FROM user_character_settings
            WHERE guild_id = ?
              AND character_name = ?
            """,
            (
                guild_id,
                character_name
            )
        )

        self.conn.commit()

        return True

    def character_exists(
        self,
        guild_id: int,
        name: str
    ):

        row = self.conn.execute(
            """
            SELECT id
            FROM characters
            WHERE guild_id = ?
              AND name = ?
            LIMIT 1
            """,
            (
                guild_id,
                name
            )
        ).fetchone()

        return row is not None

    def get_character_owner(
        self,
        guild_id: int,
        name: str
    ):

        row = self.conn.execute(
            """
            SELECT created_by
            FROM characters
            WHERE guild_id = ?
              AND name = ?
            LIMIT 1
            """,
            (
                guild_id,
                name
            )
        ).fetchone()

        if not row:
            return None

        return row["created_by"]

    # ========================================================
    # SERVER ACTIVE CHARACTER
    # ========================================================

    def set_active_character(
        self,
        guild_id: int,
        character
    ):

        if isinstance(
            character,
            sqlite3.Row
        ):

            character = row_to_dict(
                character
            )

        if isinstance(
            character,
            dict
        ):

            character = character.get(
                "name"
            )

        character = (
            character or ""
        ).strip()

        if not character:
            return False

        if not self.get_character(
            guild_id,
            character
        ):
            return False

        now = utc_now()

        self.conn.execute(
            """
            INSERT INTO guild_settings (
                guild_id,
                active_character,
                updated_at
            )
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id)
            DO UPDATE SET
                active_character = excluded.active_character,
                updated_at = excluded.updated_at
            """,
            (
                guild_id,
                character,
                now
            )
        )

        self.conn.execute(
            """
            INSERT INTO ai_config (
                guild_id,
                character_name,
                updated_at
            )
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id)
            DO UPDATE SET
                character_name = excluded.character_name,
                updated_at = excluded.updated_at
            """,
            (
                guild_id,
                character,
                now
            )
        )

        self.conn.commit()

        return True

    def get_active_character(
        self,
        guild_id: int
    ):

        config = self.get_ai_config(
            guild_id
        )

        name = (
            config.get(
                "character_name"
            )
            if config
            else None
        )

        if not name:

            name = (
                self._get_guild_active_character_name(
                    guild_id
                )
            )

        if name:

            character = self.get_character(
                guild_id,
                name
            )

            if character:
                return character

        character = self.get_character(
            guild_id,
            DEFAULT_SERVER_CHARACTER
        )

        if character:
            return character

        try:

            self.create_character(
                guild_id=guild_id,
                name=DEFAULT_SERVER_CHARACTER,
                description="مساعد السيرفر الافتراضي",
                personality="مساعد ذكي ومتوازن",
                character_type="normal",
                created_by=0,
                provider="google",
                model=CURRENT_GOOGLE_MODEL,
            )

        except sqlite3.IntegrityError:
            pass

        return self.get_character(
            guild_id,
            DEFAULT_SERVER_CHARACTER
        )

    def _get_guild_active_character_name(
        self,
        guild_id: int
    ):

        row = self.conn.execute(
            """
            SELECT active_character
            FROM guild_settings
            WHERE guild_id = ?
            LIMIT 1
            """,
            (guild_id,)
        ).fetchone()

        if not row:
            return None

        return row[
            "active_character"
        ]

    # ========================================================
    # USER ACTIVE CHARACTER - SERVER
    # ========================================================

    def set_user_active_character(
        self,
        guild_id: int,
        user_id: int,
        character_name: str
    ):

        character_name = (
            character_name or ""
        ).strip()

        if not character_name:
            return False

        character = self.get_character(
            guild_id,
            character_name
        )

        if not character:
            return False

        data = row_to_dict(
            character
        ) or {}

        owner_id = data.get(
            "created_by",
            0
        )

        if owner_id not in {
            0,
            user_id
        }:

            return False

        now = utc_now()

        self.conn.execute(
            """
            INSERT INTO user_character_settings (
                guild_id,
                user_id,
                character_name,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id)
            DO UPDATE SET
                character_name = excluded.character_name,
                updated_at = excluded.updated_at
            """,
            (
                guild_id,
                user_id,
                character_name,
                now
            )
        )

        self.conn.commit()

        return True

    def get_user_active_character_name(
        self,
        guild_id: int,
        user_id: int
    ):

        row = self.conn.execute(
            """
            SELECT character_name
            FROM user_character_settings
            WHERE guild_id = ?
              AND user_id = ?
            LIMIT 1
            """,
            (
                guild_id,
                user_id
            )
        ).fetchone()

        if not row:
            return None

        name = row[
            "character_name"
        ]

        if not name:
            return None

        return name

    def get_user_active_character(
        self,
        guild_id: int,
        user_id: int
    ):

        name = self.get_user_active_character_name(
            guild_id,
            user_id
        )

        if not name:
            return None

        character = self.get_character(
            guild_id,
            name
        )

        if not character:

            self.clear_user_active_character(
                guild_id,
                user_id
            )

            return None

        return character

    def clear_user_active_character(
        self,
        guild_id: int,
        user_id: int
    ):

        self.conn.execute(
            """
            DELETE FROM user_character_settings
            WHERE guild_id = ?
              AND user_id = ?
            """,
            (
                guild_id,
                user_id
            )
        )

        self.conn.commit()

        return True

    # ========================================================
    # AI CONFIG
    # ========================================================

    def get_ai_config(
        self,
        guild_id: int
    ):

        row = self.conn.execute(
            """
            SELECT *
            FROM ai_config
            WHERE guild_id = ?
            LIMIT 1
            """,
            (guild_id,)
        ).fetchone()

        if not row:

            result = {
                "guild_id": guild_id,
                "enabled": 1,
                "channel_id": None,
                "mode": "normal",
                "reply_type": "mention",
                "character_name": None,
                "permission_preset": "default",
                "provider": "google",
                "model": CURRENT_GOOGLE_MODEL,
                "allow_management": 1,
                "allow_channel_management": 1,
                "allow_role_management": 1,
            }

        else:

            result = row_to_dict(
                row
            )

        result["enabled"] = normalize_bool(
            result.get(
                "enabled"
            ),
            True
        )

        result["provider"] = (
            result.get(
                "provider"
            )
            or "google"
        )

        result["model"] = (
            result.get(
                "model"
            )
            or CURRENT_GOOGLE_MODEL
        )

        result["mode"] = (
            result.get(
                "mode"
            )
            or "normal"
        )

        result["reply_type"] = (
            result.get(
                "reply_type"
            )
            or "mention"
        )

        result["ai_enabled"] = (
            result["enabled"]
        )

        result["ai_channel_id"] = (
            result.get(
                "channel_id"
            )
        )

        result["active_character"] = (
            result.get(
                "character_name"
            )
        )

        result["active_provider"] = (
            result.get(
                "provider"
            )
        )

        result["active_model"] = (
            result.get(
                "model"
            )
        )

        result["ai_mode"] = (
            result.get(
                "mode"
            )
        )

        result["character"] = (
            result.get(
                "character_name"
            )
        )

        return result

    def save_ai_config(
        self,
        guild_id: int,
        **kwargs
    ):

        aliases = {
            "ai_enabled": "enabled",
            "ai_channel_id": "channel_id",
            "active_character": "character_name",
            "active_provider": "provider",
            "active_model": "model",
            "ai_mode": "mode",
            "character": "character_name",
        }

        normalized = {}

        for key, value in kwargs.items():

            key = aliases.get(
                key,
                key
            )

            normalized[key] = value

        allowed = {
            "enabled",
            "channel_id",
            "mode",
            "reply_type",
            "character_name",
            "permission_preset",
            "provider",
            "model",
            "allow_management",
            "allow_channel_management",
            "allow_role_management",
        }

        normalized = {
            key: value
            for key, value in normalized.items()
            if key in allowed
        }

        current = self.get_ai_config(
            guild_id
        )

        for key in allowed:

            if key not in normalized:

                normalized[key] = (
                    current.get(
                        key
                    )
                )

        normalized["enabled"] = int(
            normalize_bool(
                normalized["enabled"],
                True
            )
        )

        normalized["provider"] = (
            str(
                normalized["provider"]
                or "google"
            )
            .strip()
            .lower()
        )

        normalized["model"] = (
            str(
                normalized["model"]
                or CURRENT_GOOGLE_MODEL
            )
            .strip()
        )

        normalized["mode"] = (
            str(
                normalized["mode"]
                or "normal"
            )
            .strip()
        )

        normalized["reply_type"] = (
            str(
                normalized["reply_type"]
                or "mention"
            )
            .strip()
        )

        normalized["permission_preset"] = (
            str(
                normalized["permission_preset"]
                or "default"
            )
            .strip()
        )

        normalized["allow_management"] = int(
            normalize_bool(
                normalized["allow_management"],
                True
            )
        )

        normalized["allow_channel_management"] = int(
            normalize_bool(
                normalized[
                    "allow_channel_management"
                ],
                True
            )
        )

        normalized["allow_role_management"] = int(
            normalize_bool(
                normalized[
                    "allow_role_management"
                ],
                True
            )
        )

        now = utc_now()

        self.conn.execute(
            """
            INSERT INTO ai_config (
                guild_id,
                enabled,
                channel_id,
                mode,
                reply_type,
                character_name,
                permission_preset,
                provider,
                model,
                allow_management,
                allow_channel_management,
                allow_role_management,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id)
            DO UPDATE SET
                enabled = excluded.enabled,
                channel_id = excluded.channel_id,
                mode = excluded.mode,
                reply_type = excluded.reply_type,
                character_name = excluded.character_name,
                permission_preset = excluded.permission_preset,
                provider = excluded.provider,
                model = excluded.model,
                allow_management = excluded.allow_management,
                allow_channel_management = excluded.allow_channel_management,
                allow_role_management = excluded.allow_role_management,
                updated_at = excluded.updated_at
            """,
            (
                guild_id,
                normalized["enabled"],
                normalized["channel_id"],
                normalized["mode"],
                normalized["reply_type"],
                normalized["character_name"],
                normalized["permission_preset"],
                normalized["provider"],
                normalized["model"],
                normalized["allow_management"],
                normalized["allow_channel_management"],
                normalized["allow_role_management"],
                now,
            )
        )

        # ----------------------------------------------------
        # SYNC GUILD SETTINGS
        # ----------------------------------------------------

        self.conn.execute(
            """
            INSERT INTO guild_settings (
                guild_id,
                active_character,
                active_provider,
                active_model,
                ai_enabled,
                ai_channel_id,
                ai_mode,
                reply_type,
                permission_preset,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id)
            DO UPDATE SET
                active_character = excluded.active_character,
                active_provider = excluded.active_provider,
                active_model = excluded.active_model,
                ai_enabled = excluded.ai_enabled,
                ai_channel_id = excluded.ai_channel_id,
                ai_mode = excluded.ai_mode,
                reply_type = excluded.reply_type,
                permission_preset = excluded.permission_preset,
                updated_at = excluded.updated_at
            """,
            (
                guild_id,
                normalized["character_name"],
                normalized["provider"],
                normalized["model"],
                normalized["enabled"],
                normalized["channel_id"],
                normalized["mode"],
                normalized["reply_type"],
                normalized["permission_preset"],
                now,
            )
        )

        self.conn.commit()

        return True

    # ========================================================
    # COMPATIBILITY
    # ========================================================

    def get_guild_config(
        self,
        guild_id: int
    ):

        return self.get_ai_config(
            guild_id
        )

    def update_guild_config(
        self,
        guild_id: int,
        **kwargs
    ):

        return self.save_ai_config(
            guild_id,
            **kwargs
        )

    # ========================================================
    # ADVANCED SETTINGS
    # ========================================================

    def _default_advanced_settings(
        self
    ):

        return {
            key: (
                value.copy()
                if isinstance(
                    value,
                    list
                )
                else value
            )
            for key, value in
            DEFAULT_ADVANCED_SETTINGS.items()
        }

    def get_ai_advanced_settings(
        self,
        guild_id: int
    ):

        row = self.conn.execute(
            """
            SELECT *
            FROM ai_advanced_settings
            WHERE guild_id = ?
            LIMIT 1
            """,
            (guild_id,)
        ).fetchone()

        if not row:

            return self._default_advanced_settings()

        data = row_to_dict(
            row
        ) or {}

        result = (
            self._default_advanced_settings()
        )

        for key in [
            "memory_enabled",
            "history_limit",
            "response_length",
            "timeout",
            "security_enabled",
            "bot_chat_enabled",
            "bot_chat_max_chain",
            "bot_chat_cooldown",
        ]:

            if (
                key in data
                and data[key] is not None
            ):

                result[key] = data[key]

        for key in [
            "allow_members",
            "deny_members",
            "sensitive_keywords",
        ]:

            value = data.get(
                key
            )

            if isinstance(
                value,
                str
            ):

                parsed = safe_json_loads(
                    value,
                    None
                )

                if isinstance(
                    parsed,
                    list
                ):

                    value = parsed

                else:

                    value = [
                        x.strip()
                        for x in value.split(",")
                        if x.strip()
                    ]

            if not isinstance(
                value,
                list
            ):

                value = result[
                    key
                ].copy()

            result[key] = value

        result["memory_enabled"] = (
            normalize_bool(
                result["memory_enabled"],
                True
            )
        )

        result["security_enabled"] = (
            normalize_bool(
                result["security_enabled"],
                True
            )
        )

        result["bot_chat_enabled"] = (
            normalize_bool(
                result["bot_chat_enabled"],
                True
            )
        )

        try:

            result["history_limit"] = max(
                0,
                min(
                    100,
                    int(
                        result["history_limit"]
                    )
                )
            )

        except Exception:

            result["history_limit"] = 20

        try:

            result["response_length"] = max(
                100,
                min(
                    4000,
                    int(
                        result["response_length"]
                    )
                )
            )

        except Exception:

            result["response_length"] = 1200

        try:

            result["timeout"] = max(
                10,
                min(
                    180,
                    int(
                        result["timeout"]
                    )
                )
            )

        except Exception:

            result["timeout"] = 35

        try:

            result["bot_chat_max_chain"] = max(
                1,
                min(
                    50,
                    int(
                        result[
                            "bot_chat_max_chain"
                        ]
                    )
                )
            )

        except Exception:

            result["bot_chat_max_chain"] = 6

        try:

            result["bot_chat_cooldown"] = max(
                0.0,
                min(
                    60.0,
                    float(
                        result[
                            "bot_chat_cooldown"
                        ]
                    )
                )
            )

        except Exception:

            result["bot_chat_cooldown"] = 2.0

        return result

    def save_ai_advanced_settings(
        self,
        guild_id: int,
        *args,
        **kwargs
    ):

        settings = {}

        if args:

            if (
                len(args) == 1
                and isinstance(
                    args[0],
                    dict
                )
            ):

                settings.update(
                    args[0]
                )

            else:

                raise TypeError(
                    "Expected a settings dictionary."
                )

        settings.update(
            kwargs
        )

        current = (
            self.get_ai_advanced_settings(
                guild_id
            )
        )

        current.update(
            settings
        )

        current["memory_enabled"] = (
            normalize_bool(
                current["memory_enabled"],
                True
            )
        )

        current["security_enabled"] = (
            normalize_bool(
                current["security_enabled"],
                True
            )
        )

        current["bot_chat_enabled"] = (
            normalize_bool(
                current["bot_chat_enabled"],
                True
            )
        )

        try:

            current["history_limit"] = max(
                0,
                min(
                    100,
                    int(
                        current["history_limit"]
                    )
                )
            )

        except Exception:

            current["history_limit"] = 20

        try:

            current["response_length"] = max(
                100,
                min(
                    4000,
                    int(
                        current["response_length"]
                    )
                )
            )

        except Exception:

            current["response_length"] = 1200

        try:

            current["timeout"] = max(
                10,
                min(
                    180,
                    int(
                        current["timeout"]
                    )
                )
            )

        except Exception:

            current["timeout"] = 35

        try:

            current["bot_chat_max_chain"] = max(
                1,
                min(
                    50,
                    int(
                        current[
                            "bot_chat_max_chain"
                        ]
                    )
                )
            )

        except Exception:

            current["bot_chat_max_chain"] = 6

        try:

            current["bot_chat_cooldown"] = max(
                0.0,
                min(
                    60.0,
                    float(
                        current[
                            "bot_chat_cooldown"
                        ]
                    )
                )
            )

        except Exception:

            current["bot_chat_cooldown"] = 2.0

        allow_members = normalize_list(
            current.get(
                "allow_members"
            )
        )

        deny_members = normalize_list(
            current.get(
                "deny_members"
            )
        )

        sensitive_keywords = normalize_list(
            current.get(
                "sensitive_keywords"
            )
        )

        now = utc_now()

        self.conn.execute(
            """
            INSERT INTO ai_advanced_settings (
                guild_id,
                memory_enabled,
                history_limit,
                response_length,
                timeout,
                security_enabled,
                bot_chat_enabled,
                bot_chat_max_chain,
                bot_chat_cooldown,
                allow_members,
                deny_members,
                sensitive_keywords,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id)
            DO UPDATE SET
                memory_enabled = excluded.memory_enabled,
                history_limit = excluded.history_limit,
                response_length = excluded.response_length,
                timeout = excluded.timeout,
                security_enabled = excluded.security_enabled,
                bot_chat_enabled = excluded.bot_chat_enabled,
                bot_chat_max_chain = excluded.bot_chat_max_chain,
                bot_chat_cooldown = excluded.bot_chat_cooldown,
                allow_members = excluded.allow_members,
                deny_members = excluded.deny_members,
                sensitive_keywords = excluded.sensitive_keywords,
                updated_at = excluded.updated_at
            """,
            (
                guild_id,
                int(
                    current["memory_enabled"]
                ),
                current["history_limit"],
                current["response_length"],
                current["timeout"],
                int(
                    current["security_enabled"]
                ),
                int(
                    current["bot_chat_enabled"]
                ),
                current[
                    "bot_chat_max_chain"
                ],
                current[
                    "bot_chat_cooldown"
                ],
                json.dumps(
                    allow_members,
                    ensure_ascii=False
                ),
                json.dumps(
                    deny_members,
                    ensure_ascii=False
                ),
                json.dumps(
                    sensitive_keywords,
                    ensure_ascii=False
                ),
                now,
            )
        )

        self.conn.commit()

        return True

    def reset_ai_advanced_settings(
        self,
        guild_id: int
    ):

        defaults = (
            self._default_advanced_settings()
        )

        return self.save_ai_advanced_settings(
            guild_id,
            defaults
        )

    # ========================================================
    # MEMORY
    # ========================================================

    def add_message(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        character_name: Optional[str],
        role: str,
        content: str
    ):

        if not content:
            return False

        self.conn.execute(
            """
            INSERT INTO messages (
                guild_id,
                channel_id,
                user_id,
                character_name,
                role,
                content,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                channel_id,
                user_id,
                character_name,
                role,
                content,
                utc_now()
            )
        )

        self.conn.commit()

        return True

    def save_message(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        character_name: Optional[str] = None,
        role: str = "user",
        content: str = ""
    ):

        return self.add_message(
            guild_id,
            channel_id,
            user_id,
            character_name,
            role,
            content
        )

    def get_history(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        limit: int = 20
    ):

        try:

            limit = max(
                0,
                int(limit)
            )

        except Exception:

            limit = 20

        if limit <= 0:
            return []

        rows = self.conn.execute(
            """
            SELECT *
            FROM messages
            WHERE guild_id = ?
              AND channel_id = ?
              AND user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                guild_id,
                channel_id,
                user_id,
                limit
            )
        ).fetchall()

        return list(
            reversed(rows)
        )

    def get_dm_history(
        self,
        user_id: int,
        limit: int = 20
    ):

        try:

            limit = max(
                0,
                int(limit)
            )

        except Exception:

            limit = 20

        if limit <= 0:
            return []

        rows = self.conn.execute(
            """
            SELECT *
            FROM messages
            WHERE guild_id = 0
              AND user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                user_id,
                limit
            )
        ).fetchall()

        return list(
            reversed(rows)
        )

    def clear_history(
        self,
        guild_id: int,
        channel_id: Optional[int] = None,
        user_id: Optional[int] = None
    ):

        if (
            channel_id is None
            and user_id is None
        ):

            cursor = self.conn.execute(
                """
                DELETE FROM messages
                WHERE guild_id = ?
                """,
                (guild_id,)
            )

        elif user_id is None:

            cursor = self.conn.execute(
                """
                DELETE FROM messages
                WHERE guild_id = ?
                  AND channel_id = ?
                """,
                (
                    guild_id,
                    channel_id
                )
            )

        elif channel_id is None:

            cursor = self.conn.execute(
                """
                DELETE FROM messages
                WHERE guild_id = ?
                  AND user_id = ?
                """,
                (
                    guild_id,
                    user_id
                )
            )

        else:

            cursor = self.conn.execute(
                """
                DELETE FROM messages
                WHERE guild_id = ?
                  AND channel_id = ?
                  AND user_id = ?
                """,
                (
                    guild_id,
                    channel_id,
                    user_id
                )
            )

        self.conn.commit()

        return cursor.rowcount

    def clear_dm_memory(
        self,
        user_id: int
    ):

        cursor = self.conn.execute(
            """
            DELETE FROM messages
            WHERE guild_id = 0
              AND user_id = ?
            """,
            (user_id,)
        )

        self.conn.commit()

        return cursor.rowcount

    def clear_memory(
        self,
        guild_id: int
    ):

        return self.clear_history(
            guild_id
        )

    # ========================================================
    # DM SETTINGS
    # ========================================================

    def set_dm_enabled(
        self,
        user_id: int,
        enabled: bool
    ):

        return self.update_dm_settings(
            user_id,
            enabled=int(
                normalize_bool(
                    enabled,
                    False
                )
            )
        )

    def get_dm_enabled(
        self,
        user_id: int
    ):

        settings = self.get_dm_settings(
            user_id
        )

        return settings[
            "enabled"
        ]

    def get_dm_settings(
        self,
        user_id: int
    ):

        row = self.conn.execute(
            """
            SELECT *
            FROM ai_dm_settings
            WHERE user_id = ?
            LIMIT 1
            """,
            (user_id,)
        ).fetchone()

        if not row:

            self.conn.execute(
                """
                INSERT INTO ai_dm_settings (
                    user_id,
                    enabled,
                    active_character,
                    reply_mode,
                    mode,
                    history_limit,
                    response_length,
                    updated_at
                )
                VALUES (?, 0, NULL, 'always', 'normal', 20, 1200, ?)
                """,
                (
                    user_id,
                    utc_now()
                )
            )

            self.conn.commit()

            row = self.conn.execute(
                """
                SELECT *
                FROM ai_dm_settings
                WHERE user_id = ?
                LIMIT 1
                """,
                (user_id,)
            ).fetchone()

        data = (
            row_to_dict(row)
            or {}
        )

        try:

            history_limit = max(
                0,
                min(
                    100,
                    int(
                        data.get(
                            "history_limit",
                            20
                        )
                    )
                )
            )

        except Exception:

            history_limit = 20

        try:

            response_length = max(
                100,
                min(
                    4000,
                    int(
                        data.get(
                            "response_length",
                            1200
                        )
                    )
                )
            )

        except Exception:

            response_length = 1200

        reply_mode = (
            data.get(
                "reply_mode"
            )
            or "always"
        ).strip().lower()

        if reply_mode not in {
            "always",
            "called",
            "off",
        }:

            reply_mode = "always"

        mode = (
            data.get(
                "mode"
            )
            or "normal"
        ).strip().lower()

        if not mode:
            mode = "normal"

        return {
            "user_id": user_id,
            "enabled": normalize_bool(
                data.get(
                    "enabled"
                ),
                False
            ),
            "active_character": data.get(
                "active_character"
            ),
            "reply_mode": reply_mode,
            "mode": mode,
            "history_limit": history_limit,
            "response_length": response_length,
        }

    def update_dm_settings(
        self,
        user_id: int,
        **kwargs
    ):

        current = self.get_dm_settings(
            user_id
        )

        allowed = {
            "enabled",
            "active_character",
            "reply_mode",
            "mode",
            "history_limit",
            "response_length",
        }

        for key, value in kwargs.items():

            if key not in allowed:
                continue

            current[key] = value

        current["enabled"] = int(
            normalize_bool(
                current.get(
                    "enabled"
                ),
                False
            )
        )

        reply_mode = (
            str(
                current.get(
                    "reply_mode",
                    "always"
                )
            )
            .strip()
            .lower()
        )

        if reply_mode not in {
            "always",
            "called",
            "off",
        }:

            reply_mode = "always"

        current["reply_mode"] = reply_mode

        current["mode"] = (
            str(
                current.get(
                    "mode",
                    "normal"
                )
                or "normal"
            )
            .strip()
            .lower()
        )

        try:

            current["history_limit"] = max(
                0,
                min(
                    100,
                    int(
                        current.get(
                            "history_limit",
                            20
                        )
                    )
                )
            )

        except Exception:

            current["history_limit"] = 20

        try:

            current["response_length"] = max(
                100,
                min(
                    4000,
                    int(
                        current.get(
                            "response_length",
                            1200
                        )
                    )
                )
            )

        except Exception:

            current["response_length"] = 1200

        self.conn.execute(
            """
            INSERT INTO ai_dm_settings (
                user_id,
                enabled,
                active_character,
                reply_mode,
                mode,
                history_limit,
                response_length,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                enabled = excluded.enabled,
                active_character = excluded.active_character,
                reply_mode = excluded.reply_mode,
                mode = excluded.mode,
                history_limit = excluded.history_limit,
                response_length = excluded.response_length,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                current["enabled"],
                current["active_character"],
                current["reply_mode"],
                current["mode"],
                current["history_limit"],
                current["response_length"],
                utc_now()
            )
        )

        self.conn.commit()

        return True

    # ========================================================
    # DM CHARACTERS
    # ========================================================

    def create_dm_character(
        self,
        user_id: int,
        name: str,
        description: str = "",
        personality: str = "",
        system_prompt: str = "",
        character_type: str = "normal",
        custom_instructions: str = "",
        speaking_style: str = "",
        provider: str = "google",
        model: str = CURRENT_GOOGLE_MODEL,
    ):

        name = (
            name or ""
        ).strip()

        if not name:

            raise ValueError(
                "DM character name cannot be empty."
            )

        character_type = (
            character_type
            or "normal"
        ).strip()

        provider = (
            provider
            or "google"
        ).strip().lower()

        model = (
            model
            or CURRENT_GOOGLE_MODEL
        ).strip()

        try:

            cursor = self.conn.execute(
                """
                INSERT INTO dm_characters (
                    user_id,
                    name,
                    description,
                    personality,
                    system_prompt,
                    character_type,
                    custom_instructions,
                    speaking_style,
                    provider,
                    model,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    name,
                    description or "",
                    personality or "",
                    system_prompt or "",
                    character_type,
                    custom_instructions or "",
                    speaking_style or "",
                    provider,
                    model,
                    utc_now()
                )
            )

            self.conn.commit()

            return cursor.lastrowid

        except sqlite3.IntegrityError:

            return False

    def get_dm_character(
        self,
        user_id: int,
        name: str
    ):

        if not name:
            return None

        return self.conn.execute(
            """
            SELECT *
            FROM dm_characters
            WHERE user_id = ?
              AND name = ?
            LIMIT 1
            """,
            (
                user_id,
                name
            )
        ).fetchone()

    def get_dm_characters(
        self,
        user_id: int
    ):

        return self.conn.execute(
            """
            SELECT *
            FROM dm_characters
            WHERE user_id = ?
            ORDER BY name COLLATE NOCASE ASC
            """,
            (user_id,)
        ).fetchall()

    def get_active_dm_character(
        self,
        user_id: int
    ):

        settings = self.get_dm_settings(
            user_id
        )

        name = settings.get(
            "active_character"
        )

        if not name:
            return None

        character = self.get_dm_character(
            user_id,
            name
        )

        if not character:

            self.update_dm_settings(
                user_id,
                active_character=None
            )

            return None

        return character

    def set_active_dm_character(
        self,
        user_id: int,
        character_name: str
    ):

        character_name = (
            character_name or ""
        ).strip()

        if not character_name:
            return False

        character = self.get_dm_character(
            user_id,
            character_name
        )

        if not character:
            return False

        return self.update_dm_settings(
            user_id,
            active_character=character_name
        )

    def update_dm_character(
        self,
        user_id: int,
        name: str,
        **kwargs
    ):

        allowed = {
            "description",
            "personality",
            "system_prompt",
            "character_type",
            "custom_instructions",
            "speaking_style",
            "provider",
            "model",
        }

        updates = []
        values = []

        for key, value in kwargs.items():

            if key not in allowed:
                continue

            if key == "provider":

                value = (
                    value
                    or "google"
                ).strip().lower()

            elif key == "model":

                value = (
                    value
                    or CURRENT_GOOGLE_MODEL
                ).strip()

            elif key == "character_type":

                value = (
                    value
                    or "normal"
                ).strip()

            updates.append(
                f"{key} = ?"
            )

            values.append(
                value or ""
            )

        if not updates:
            return False

        values.extend([
            user_id,
            name
        ])

        cursor = self.conn.execute(
            f"""
            UPDATE dm_characters
            SET {", ".join(updates)}
            WHERE user_id = ?
              AND name = ?
            """,
            values
        )

        self.conn.commit()

        return cursor.rowcount > 0

    def delete_dm_character(
        self,
        user_id: int,
        name: str
    ):

        character = self.get_dm_character(
            user_id,
            name
        )

        if not character:
            return False

        settings = self.get_dm_settings(
            user_id
        )

        cursor = self.conn.execute(
            """
            DELETE FROM dm_characters
            WHERE user_id = ?
              AND name = ?
            """,
            (
                user_id,
                name
            )
        )

        if cursor.rowcount <= 0:
            return False

        if settings.get(
            "active_character"
        ) == name:

            self.conn.execute(
                """
                UPDATE ai_dm_settings
                SET active_character = NULL,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (
                    utc_now(),
                    user_id
                )
            )

        self.conn.commit()

        return True

    def dm_character_exists(
        self,
        user_id: int,
        name: str
    ):

        row = self.conn.execute(
            """
            SELECT id
            FROM dm_characters
            WHERE user_id = ?
              AND name = ?
            LIMIT 1
            """,
            (
                user_id,
                name
            )
        ).fetchone()

        return row is not None

    # ========================================================
    # CLOSE
    # ========================================================

    def close(
        self
    ):

        try:
            self.conn.close()

        except Exception:
            pass
