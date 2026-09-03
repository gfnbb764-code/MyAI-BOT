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
    os.getenv(
        "DB_PATH",
        "myai.db",
    ),
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
    return datetime.now(
        timezone.utc
    ).isoformat()


def normalize_bool(
    value,
    default=False,
):
    if value is None:
        return int(default)

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int):
        return 1 if value else 0

    if isinstance(value, str):
        value = value.strip().lower()

        if value in (
            "1",
            "true",
            "yes",
            "on",
            "enabled",
        ):
            return 1

        if value in (
            "0",
            "false",
            "no",
            "off",
            "disabled",
        ):
            return 0

    return int(default)


def safe_json_loads(
    value,
    default,
):
    if value is None:
        return default

    if isinstance(
        value,
        (list, dict),
    ):
        return value

    try:
        result = json.loads(value)

        if result is None:
            return default

        return result

    except Exception:
        return default


def normalize_list(value):
    if value is None:
        return []

    if isinstance(
        value,
        (list, tuple, set),
    ):
        return list(value)

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return []

        parsed = safe_json_loads(
            value,
            None,
        )

        if isinstance(
            parsed,
            list,
        ):
            return parsed

        return [
            item.strip()
            for item in value.split(",")
            if item.strip()
        ]

    return [value]


def row_to_dict(row):
    if row is None:
        return None

    if isinstance(row, dict):
        return dict(row)

    try:
        return dict(row)
    except Exception:
        return None


# ============================================================
# DATABASE
# ============================================================

class Database:

    def __init__(
        self,
        path: Optional[str] = None,
    ):
        self.path = path or DB_PATH

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
    # CONNECTION
    # ========================================================

    def cursor(self):
        return self.conn.cursor()

    def commit(self):
        self.conn.commit()

    # ========================================================
    # TABLE CREATION
    # ========================================================

    def _create_tables(self):

        # ----------------------------------------------------
        # CHARACTERS
        # ----------------------------------------------------

        self.conn.execute(
            """
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
                created_at TEXT
            )
            """
        )

        # ----------------------------------------------------
        # MESSAGES
        # ----------------------------------------------------

        self.conn.execute(
            """
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
            """
        )

        # ----------------------------------------------------
        # GUILD SETTINGS
        # ----------------------------------------------------

        self.conn.execute(
            """
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
            """
        )

        # ----------------------------------------------------
        # AI CONFIG
        # ----------------------------------------------------

        self.conn.execute(
            """
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
            """
        )

        # ----------------------------------------------------
        # DM SETTINGS
        # ----------------------------------------------------

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_dm_settings (
                user_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                updated_at TEXT
            )
            """
        )

        # ----------------------------------------------------
        # ADVANCED AI SETTINGS
        # ----------------------------------------------------

        self.conn.execute(
            """
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
            """
        )

        # ----------------------------------------------------
        # INDEXES
        # ----------------------------------------------------

        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_characters_guild
            ON characters(guild_id)
            """
        )

        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_messages_guild_channel
            ON messages(guild_id, channel_id)
            """
        )

        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_messages_user
            ON messages(guild_id, user_id)
            """
        )

        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_messages_created
            ON messages(created_at)
            """
        )

        self.conn.commit()

    # ========================================================
    # MIGRATIONS
    # ========================================================

    def _table_columns(
        self,
        table_name: str,
    ):
        rows = self.conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()

        return {
            row["name"]
            for row in rows
        }

    def _add_column_if_missing(
        self,
        table_name: str,
        column_name: str,
        definition: str,
    ):
        columns = self._table_columns(
            table_name
        )

        if column_name not in columns:
            self.conn.execute(
                f"""
                ALTER TABLE {table_name}
                ADD COLUMN {column_name}
                {definition}
                """
            )

    def _migrate_tables(self):

        # ----------------------------------------------------
        # CHARACTERS
        # ----------------------------------------------------

        character_columns = {
            "description": "TEXT DEFAULT ''",
            "personality": "TEXT DEFAULT ''",
            "system_prompt": "TEXT DEFAULT ''",
            "character_type": "TEXT DEFAULT 'normal'",
            "custom_instructions": "TEXT DEFAULT ''",
            "speaking_style": "TEXT DEFAULT ''",
            "provider": "TEXT DEFAULT 'google'",
            "model": "TEXT DEFAULT 'gemini-3.5-flash-lite'",
            "created_by": "INTEGER DEFAULT 0",
            "created_at": "TEXT",
        }

        for column, definition in character_columns.items():
            self._add_column_if_missing(
                "characters",
                column,
                definition,
            )

        # ----------------------------------------------------
        # MESSAGES
        # ----------------------------------------------------

        self._add_column_if_missing(
            "messages",
            "character_name",
            "TEXT",
        )

        self._add_column_if_missing(
            "messages",
            "created_at",
            "TEXT",
        )

        # ----------------------------------------------------
        # GUILD SETTINGS
        # ----------------------------------------------------

        guild_columns = {
            "active_character": "TEXT",
            "active_provider": "TEXT DEFAULT 'google'",
            "active_model": "TEXT DEFAULT 'gemini-3.5-flash-lite'",
            "ai_enabled": "INTEGER DEFAULT 1",
            "ai_channel_id": "INTEGER",
            "ai_mode": "TEXT DEFAULT 'normal'",
            "reply_type": "TEXT DEFAULT 'mention'",
            "permission_preset": "TEXT DEFAULT 'default'",
            "updated_at": "TEXT",
        }

        for column, definition in guild_columns.items():
            self._add_column_if_missing(
                "guild_settings",
                column,
                definition,
            )

        # ----------------------------------------------------
        # AI CONFIG
        # ----------------------------------------------------

        ai_config_columns = {
            "enabled": "INTEGER DEFAULT 1",
            "channel_id": "INTEGER",
            "mode": "TEXT DEFAULT 'normal'",
            "reply_type": "TEXT DEFAULT 'mention'",
            "character_name": "TEXT",
            "permission_preset": "TEXT DEFAULT 'default'",
            "provider": "TEXT DEFAULT 'google'",
            "model": "TEXT DEFAULT 'gemini-3.5-flash-lite'",
            "allow_management": "INTEGER DEFAULT 1",
            "allow_channel_management": "INTEGER DEFAULT 1",
            "allow_role_management": "INTEGER DEFAULT 1",
            "updated_at": "TEXT",
        }

        for column, definition in ai_config_columns.items():
            self._add_column_if_missing(
                "ai_config",
                column,
                definition,
            )

        # ----------------------------------------------------
        # ADVANCED SETTINGS
        # ----------------------------------------------------

        advanced_columns = {
            "memory_enabled": "INTEGER DEFAULT 1",
            "history_limit": "INTEGER DEFAULT 20",
            "response_length": "INTEGER DEFAULT 1200",
            "timeout": "INTEGER DEFAULT 35",
            "security_enabled": "INTEGER DEFAULT 1",
            "bot_chat_enabled": "INTEGER DEFAULT 1",
            "bot_chat_max_chain": "INTEGER DEFAULT 6",
            "bot_chat_cooldown": "REAL DEFAULT 2.0",
            "allow_members": "TEXT DEFAULT '[]'",
            "deny_members": "TEXT DEFAULT '[]'",
            "sensitive_keywords": "TEXT DEFAULT '[]'",
            "updated_at": "TEXT",
        }

        for column, definition in advanced_columns.items():
            self._add_column_if_missing(
                "ai_advanced_settings",
                column,
                definition,
            )

        self.conn.commit()

    # ========================================================
    # DATABASE REPAIR
    # ========================================================

    def _repair_database(self):

        now = utc_now()

        self.conn.execute(
            """
            UPDATE characters
            SET created_at = ?
            WHERE created_at IS NULL
            """,
            (now,),
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
            (CURRENT_GOOGLE_MODEL,),
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
            (CURRENT_GOOGLE_MODEL,),
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
            (CURRENT_GOOGLE_MODEL,),
        )

        self.conn.commit()

    # ========================================================
    # CHARACTERS
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
        provider: str = "google",
        model: str = CURRENT_GOOGLE_MODEL,
        created_by: int = 0,
    ):

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
                description,
                personality,
                system_prompt,
                character_type,
                custom_instructions,
                speaking_style,
                provider,
                model,
                created_by,
                now,
            ),
        )

        self.conn.commit()

        return cursor.lastrowid

    def get_character(
        self,
        guild_id: int,
        name: str,
    ):
        return self.conn.execute(
            """
            SELECT *
            FROM characters
            WHERE guild_id = ?
              AND LOWER(name) = LOWER(?)
            LIMIT 1
            """,
            (
                guild_id,
                name,
            ),
        ).fetchone()

    def get_character_by_id(
        self,
        character_id: int,
    ):
        return self.conn.execute(
            """
            SELECT *
            FROM characters
            WHERE id = ?
            LIMIT 1
            """,
            (character_id,),
        ).fetchone()

    def get_characters(
        self,
        guild_id: int,
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
            (guild_id,),
        ).fetchall()

    def list_characters(
        self,
        guild_id: int,
    ):
        return self.get_characters(
            guild_id
        )

    def get_user_characters(
        self,
        guild_id: int,
        user_id: int,
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
                user_id,
            ),
        ).fetchall()

    def update_character(
        self,
        guild_id: int,
        name: str,
        **kwargs,
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

        updates = {
            key: value
            for key, value in kwargs.items()
            if key in allowed
        }

        if not updates:
            return False

        set_parts = []
        values = []

        for key, value in updates.items():
            set_parts.append(
                f"{key} = ?"
            )
            values.append(value)

        values.extend([
            guild_id,
            name,
        ])

        cursor = self.conn.execute(
            f"""
            UPDATE characters
            SET {", ".join(set_parts)}
            WHERE guild_id = ?
              AND LOWER(name) = LOWER(?)
            """,
            values,
        )

        self.conn.commit()

        return cursor.rowcount > 0

    def delete_character(
        self,
        guild_id: int,
        name: str,
    ):
        character = self.get_character(
            guild_id,
            name,
        )

        if not character:
            return False

        data = row_to_dict(character) or {}

        if int(
            data.get("created_by", 0)
        ) == 0:
            return False

        cursor = self.conn.execute(
            """
            DELETE FROM characters
            WHERE guild_id = ?
              AND LOWER(name) = LOWER(?)
            """,
            (
                guild_id,
                name,
            ),
        )

        self.conn.commit()

        return cursor.rowcount > 0

    # ========================================================
    # CHARACTER OWNERSHIP
    # ========================================================

    def character_exists(
        self,
        guild_id: int,
        name: str,
    ):
        return (
            self.get_character(
                guild_id,
                name,
            )
            is not None
        )

    def get_character_owner(
        self,
        guild_id: int,
        name: str,
    ):
        row = self.conn.execute(
            """
            SELECT created_by
            FROM characters
            WHERE guild_id = ?
              AND LOWER(name) = LOWER(?)
            LIMIT 1
            """,
            (
                guild_id,
                name,
            ),
        ).fetchone()

        if not row:
            return None

        return row["created_by"]

    # ========================================================
    # ACTIVE CHARACTER
    # ========================================================

    def set_active_character(
        self,
        guild_id: int,
        character,
    ):
        if isinstance(
            character,
            dict,
        ):
            name = (
                character.get("name")
                or character.get(
                    "character_name"
                )
            )
        else:
            data = row_to_dict(character)

            if data:
                name = (
                    data.get("name")
                    or data.get(
                        "character_name"
                    )
                )
            else:
                name = str(character)

        if not name:
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
                name,
                now,
            ),
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
                name,
                now,
            ),
        )

        self.conn.commit()

        return True

    def get_active_character(
        self,
        guild_id: int,
    ):
        config = self.get_ai_config(
            guild_id
        )

        name = (
            config.get("character_name")
            or config.get("active_character")
        )

        if name:
            return self.get_character(
                guild_id,
                name,
            )

        existing = self.get_character(
            guild_id,
            DEFAULT_SERVER_CHARACTER,
        )

        if existing:
            return existing

        self.create_character(
            guild_id=guild_id,
            name=DEFAULT_SERVER_CHARACTER,
            description="مساعد الذكاء الاصطناعي الافتراضي للسيرفر",
            personality="مساعد ذكي وودود",
            system_prompt="",
            character_type="normal",
            custom_instructions="",
            speaking_style="طبيعي وواضح",
            provider="google",
            model=CURRENT_GOOGLE_MODEL,
            created_by=0,
        )

        return self.get_character(
            guild_id,
            DEFAULT_SERVER_CHARACTER,
        )

    # ========================================================
    # AI CONFIG
    # ========================================================

    def get_ai_config(
        self,
        guild_id: int,
    ):
        row = self.conn.execute(
            """
            SELECT *
            FROM ai_config
            WHERE guild_id = ?
            LIMIT 1
            """,
            (guild_id,),
        ).fetchone()

        if row:
            result = row_to_dict(row)
        else:
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

        result["ai_enabled"] = result.get(
            "enabled",
            1,
        )

        result["ai_channel_id"] = result.get(
            "channel_id"
        )

        result["active_character"] = result.get(
            "character_name"
        )

        result["active_provider"] = result.get(
            "provider",
            "google",
        )

        result["active_model"] = result.get(
            "model",
            CURRENT_GOOGLE_MODEL,
        )

        result["ai_mode"] = result.get(
            "mode",
            "normal",
        )

        return result

    def save_ai_config(
        self,
        guild_id: int,
        **kwargs,
    ):
        aliases = {
            "ai_enabled": "enabled",
            "ai_channel_id": "channel_id",
            "active_character": "character_name",
            "active_provider": "provider",
            "active_model": "model",
            "ai_mode": "mode",
        }

        normalized = {}

        for key, value in kwargs.items():
            normalized[
                aliases.get(
                    key,
                    key,
                )
            ] = value

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

        updates = {
            key: value
            for key, value in normalized.items()
            if key in allowed
        }

        if not updates:
            return False

        if "enabled" in updates:
            updates["enabled"] = normalize_bool(
                updates["enabled"],
                True,
            )

        for key in (
            "allow_management",
            "allow_channel_management",
            "allow_role_management",
        ):
            if key in updates:
                updates[key] = normalize_bool(
                    updates[key],
                    True,
                )

        if "provider" in updates:
            updates["provider"] = str(
                updates["provider"]
            ).strip().lower()

        if "model" in updates:
            updates["model"] = str(
                updates["model"]
            ).strip()

        if not updates.get("model"):
            updates["model"] = CURRENT_GOOGLE_MODEL

        now = utc_now()

        updates["updated_at"] = now

        existing = self.conn.execute(
            """
            SELECT guild_id
            FROM ai_config
            WHERE guild_id = ?
            LIMIT 1
            """,
            (guild_id,),
        ).fetchone()

        if existing:
            set_parts = []
            values = []

            for key, value in updates.items():
                set_parts.append(
                    f"{key} = ?"
                )
                values.append(value)

            values.append(guild_id)

            self.conn.execute(
                f"""
                UPDATE ai_config
                SET {", ".join(set_parts)}
                WHERE guild_id = ?
                """,
                values,
            )

        else:
            fields = ["guild_id"]
            values = [guild_id]
            placeholders = ["?"]

            for key, value in updates.items():
                fields.append(key)
                values.append(value)
                placeholders.append("?")

            self.conn.execute(
                f"""
                INSERT INTO ai_config (
                    {", ".join(fields)}
                )
                VALUES (
                    {", ".join(placeholders)}
                )
                """,
                values,
            )

        # ----------------------------------------------------
        # Synchronize guild_settings
        # ----------------------------------------------------

        guild_updates = {}

        if "character_name" in updates:
            guild_updates[
                "active_character"
            ] = updates["character_name"]

        if "provider" in updates:
            guild_updates[
                "active_provider"
            ] = updates["provider"]

        if "model" in updates:
            guild_updates[
                "active_model"
            ] = updates["model"]

        if "enabled" in updates:
            guild_updates[
                "ai_enabled"
            ] = updates["enabled"]

        if "channel_id" in updates:
            guild_updates[
                "ai_channel_id"
            ] = updates["channel_id"]

        if "mode" in updates:
            guild_updates[
                "ai_mode"
            ] = updates["mode"]

        if "reply_type" in updates:
            guild_updates[
                "reply_type"
            ] = updates["reply_type"]

        if guild_updates:
            guild_updates["updated_at"] = now

            existing_guild = self.conn.execute(
                """
                SELECT guild_id
                FROM guild_settings
                WHERE guild_id = ?
                LIMIT 1
                """,
                (guild_id,),
            ).fetchone()

            if existing_guild:
                set_parts = []
                values = []

                for key, value in guild_updates.items():
                    set_parts.append(
                        f"{key} = ?"
                    )
                    values.append(value)

                values.append(guild_id)

                self.conn.execute(
                    f"""
                    UPDATE guild_settings
                    SET {", ".join(set_parts)}
                    WHERE guild_id = ?
                    """,
                    values,
                )

            else:
                fields = ["guild_id"]
                values = [guild_id]
                placeholders = ["?"]

                for key, value in guild_updates.items():
                    fields.append(key)
                    values.append(value)
                    placeholders.append("?")

                self.conn.execute(
                    f"""
                    INSERT INTO guild_settings (
                        {", ".join(fields)}
                    )
                    VALUES (
                        {", ".join(placeholders)}
                    )
                    """,
                    values,
                )

        self.conn.commit()

        return True

    # ========================================================
    # GUILD CONFIG COMPATIBILITY
    # ========================================================

    def get_guild_config(
        self,
        guild_id: int,
    ):
        """
        Compatibility wrapper for main.py.
        Uses the unified AI configuration.
        """
        return self.get_ai_config(
            guild_id
        )

    def update_guild_config(
        self,
        guild_id: int,
        **kwargs,
    ):
        """
        Compatibility wrapper for main.py.
        """
        return self.save_ai_config(
            guild_id,
            **kwargs,
        )

    # ========================================================
    # ADVANCED AI SETTINGS
    # ========================================================

    def _default_advanced_settings(self):
        return {
            "memory_enabled": DEFAULT_ADVANCED_SETTINGS[
                "memory_enabled"
            ],
            "history_limit": DEFAULT_ADVANCED_SETTINGS[
                "history_limit"
            ],
            "response_length": DEFAULT_ADVANCED_SETTINGS[
                "response_length"
            ],
            "timeout": DEFAULT_ADVANCED_SETTINGS[
                "timeout"
            ],
            "security_enabled": DEFAULT_ADVANCED_SETTINGS[
                "security_enabled"
            ],
            "bot_chat_enabled": DEFAULT_ADVANCED_SETTINGS[
                "bot_chat_enabled"
            ],
            "bot_chat_max_chain": DEFAULT_ADVANCED_SETTINGS[
                "bot_chat_max_chain"
            ],
            "bot_chat_cooldown": DEFAULT_ADVANCED_SETTINGS[
                "bot_chat_cooldown"
            ],
            "allow_members": list(
                DEFAULT_ADVANCED_SETTINGS[
                    "allow_members"
                ]
            ),
            "deny_members": list(
                DEFAULT_ADVANCED_SETTINGS[
                    "deny_members"
                ]
            ),
            "sensitive_keywords": list(
                DEFAULT_ADVANCED_SETTINGS[
                    "sensitive_keywords"
                ]
            ),
        }

    def get_ai_advanced_settings(
        self,
        guild_id: int,
    ):
        row = self.conn.execute(
            """
            SELECT *
            FROM ai_advanced_settings
            WHERE guild_id = ?
            LIMIT 1
            """,
            (guild_id,),
        ).fetchone()

        defaults = self._default_advanced_settings()

        if not row:
            return defaults

        data = row_to_dict(row) or {}

        result = defaults.copy()

        result["memory_enabled"] = bool(
            normalize_bool(
                data.get("memory_enabled"),
                defaults["memory_enabled"],
            )
        )

        result["history_limit"] = max(
            0,
            min(
                int(
                    data.get(
                        "history_limit",
                        defaults["history_limit"],
                    )
                ),
                100,
            ),
        )

        result["response_length"] = max(
            100,
            min(
                int(
                    data.get(
                        "response_length",
                        defaults["response_length"],
                    )
                ),
                4000,
            ),
        )

        result["timeout"] = max(
            10,
            min(
                int(
                    data.get(
                        "timeout",
                        defaults["timeout"],
                    )
                ),
                180,
            ),
        )

        result["security_enabled"] = bool(
            normalize_bool(
                data.get("security_enabled"),
                defaults["security_enabled"],
            )
        )

        result["bot_chat_enabled"] = bool(
            normalize_bool(
                data.get("bot_chat_enabled"),
                defaults["bot_chat_enabled"],
            )
        )

        result["bot_chat_max_chain"] = max(
            1,
            min(
                int(
                    data.get(
                        "bot_chat_max_chain",
                        defaults["bot_chat_max_chain"],
                    )
                ),
                50,
            ),
        )

        result["bot_chat_cooldown"] = max(
            0.0,
            min(
                float(
                    data.get(
                        "bot_chat_cooldown",
                        defaults["bot_chat_cooldown"],
                    )
                ),
                60.0,
            ),
        )

        result["allow_members"] = [
            int(x)
            for x in normalize_list(
                safe_json_loads(
                    data.get("allow_members"),
                    [],
                )
            )
            if str(x).isdigit()
        ]

        result["deny_members"] = [
            int(x)
            for x in normalize_list(
                safe_json_loads(
                    data.get("deny_members"),
                    [],
                )
            )
            if str(x).isdigit()
        ]

        keywords = safe_json_loads(
            data.get("sensitive_keywords"),
            [],
        )

        if not isinstance(
            keywords,
            list,
        ):
            keywords = normalize_list(
                keywords
            )

        result["sensitive_keywords"] = [
            str(x).strip()
            for x in keywords
            if str(x).strip()
        ]

        return result

    def save_ai_advanced_settings(
        self,
        guild_id: int,
        **kwargs,
    ):
        allowed = {
            "memory_enabled",
            "history_limit",
            "response_length",
            "timeout",
            "security_enabled",
            "bot_chat_enabled",
            "bot_chat_max_chain",
            "bot_chat_cooldown",
            "allow_members",
            "deny_members",
            "sensitive_keywords",
        }

        updates = {
            key: value
            for key, value in kwargs.items()
            if key in allowed
        }

        if not updates:
            return False

        if "memory_enabled" in updates:
            updates["memory_enabled"] = normalize_bool(
                updates["memory_enabled"],
                True,
            )

        if "security_enabled" in updates:
            updates["security_enabled"] = normalize_bool(
                updates["security_enabled"],
                True,
            )

        if "bot_chat_enabled" in updates:
            updates["bot_chat_enabled"] = normalize_bool(
                updates["bot_chat_enabled"],
                True,
            )

        if "history_limit" in updates:
            updates["history_limit"] = max(
                0,
                min(
                    int(
                        updates["history_limit"]
                    ),
                    100,
                ),
            )

        if "response_length" in updates:
            updates["response_length"] = max(
                100,
                min(
                    int(
                        updates["response_length"]
                    ),
                    4000,
                ),
            )

        if "timeout" in updates:
            updates["timeout"] = max(
                10,
                min(
                    int(
                        updates["timeout"]
                    ),
                    180,
                ),
            )

        if "bot_chat_max_chain" in updates:
            updates[
                "bot_chat_max_chain"
            ] = max(
                1,
                min(
                    int(
                        updates[
                            "bot_chat_max_chain"
                        ]
                    ),
                    50,
                ),
            )

        if "bot_chat_cooldown" in updates:
            updates[
                "bot_chat_cooldown"
            ] = max(
                0.0,
                min(
                    float(
                        updates[
                            "bot_chat_cooldown"
                        ]
                    ),
                    60.0,
                ),
            )

        for key in (
            "allow_members",
            "deny_members",
        ):
            if key in updates:
                values = normalize_list(
                    updates[key]
                )

                clean = []

                for value in values:
                    try:
                        clean.append(
                            int(value)
                        )
                    except Exception:
                        pass

                updates[key] = clean

        if "sensitive_keywords" in updates:
            updates[
                "sensitive_keywords"
            ] = [
                str(x).strip()
                for x in normalize_list(
                    updates[
                        "sensitive_keywords"
                    ]
                )
                if str(x).strip()
            ]

        for key in (
            "allow_members",
            "deny_members",
            "sensitive_keywords",
        ):
            if key in updates:
                updates[key] = json.dumps(
                    updates[key],
                    ensure_ascii=False,
                )

        updates["updated_at"] = utc_now()

        existing = self.conn.execute(
            """
            SELECT guild_id
            FROM ai_advanced_settings
            WHERE guild_id = ?
            LIMIT 1
            """,
            (guild_id,),
        ).fetchone()

        if existing:
            set_parts = []
            values = []

            for key, value in updates.items():
                set_parts.append(
                    f"{key} = ?"
                )
                values.append(value)

            values.append(guild_id)

            self.conn.execute(
                f"""
                UPDATE ai_advanced_settings
                SET {", ".join(set_parts)}
                WHERE guild_id = ?
                """,
                values,
            )

        else:
            fields = ["guild_id"]
            values = [guild_id]
            placeholders = ["?"]

            for key, value in updates.items():
                fields.append(key)
                values.append(value)
                placeholders.append("?")

            self.conn.execute(
                f"""
                INSERT INTO ai_advanced_settings (
                    {", ".join(fields)}
                )
                VALUES (
                    {", ".join(placeholders)}
                )
                """,
                values,
            )

        self.conn.commit()

        return True

    def reset_ai_advanced_settings(
        self,
        guild_id: int,
    ):
        defaults = (
            self._default_advanced_settings()
        )

        return self.save_ai_advanced_settings(
            guild_id,
            **defaults,
        )

    # ========================================================
    # MESSAGES / MEMORY
    # ========================================================

    def add_message(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        character_name: str,
        role: str,
        content: str,
    ):
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
                utc_now(),
            ),
        )

        self.conn.commit()

    def save_message(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        character_name: str,
        role: str,
        content: str,
    ):
        """
        Compatibility wrapper for main.py.
        """
        return self.add_message(
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            character_name=character_name,
            role=role,
            content=content,
        )

    def get_history(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        limit: int = 20,
    ):
        try:
            limit = int(limit)
        except Exception:
            limit = 20

        limit = max(
            0,
            min(
                limit,
                100,
            ),
        )

        if limit == 0:
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
                limit,
            ),
        ).fetchall()

        return list(
            reversed(rows)
        )

    def clear_history(
        self,
        guild_id: int,
        channel_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ):
        conditions = [
            "guild_id = ?"
        ]

        values = [
            guild_id
        ]

        if channel_id is not None:
            conditions.append(
                "channel_id = ?"
            )
            values.append(
                channel_id
            )

        if user_id is not None:
            conditions.append(
                "user_id = ?"
            )
            values.append(
                user_id
            )

        self.conn.execute(
            f"""
            DELETE FROM messages
            WHERE {" AND ".join(conditions)}
            """,
            values,
        )

        self.conn.commit()

    def clear_memory(
        self,
        guild_id: int,
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
        enabled: bool,
    ):
        now = utc_now()

        self.conn.execute(
            """
            INSERT INTO ai_dm_settings (
                user_id,
                enabled,
                updated_at
            )
            VALUES (?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                normalize_bool(
                    enabled,
                    False,
                ),
                now,
            ),
        )

        self.conn.commit()

    def get_dm_enabled(
        self,
        user_id: int,
    ):
        row = self.conn.execute(
            """
            SELECT enabled
            FROM ai_dm_settings
            WHERE user_id = ?
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        if not row:
            return False

        return bool(
            row["enabled"]
        )

    # ========================================================
    # CLOSE
    # ========================================================

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    # ========================================================
    # CONTEXT MANAGER
    # ========================================================

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback_value,
    ):
        self.close()
