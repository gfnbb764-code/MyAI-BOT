# database.py

import os
import sqlite3
import threading
from datetime import datetime, timezone


# ==========================================================
# CONSTANTS
# ==========================================================

CURRENT_GOOGLE_MODEL = os.getenv(
    "GOOGLE_MODEL",
    "gemini-3.5-flash-lite"
)

DM_GUILD_ID = 0

DM_CHARACTER_NAME = "مساعد MyAI"

DEFAULT_CHARACTER_TYPE = "normal"

DEFAULT_CHARACTER_PERSONALITY = (
    "شخصية متوازنة وطبيعية."
)

DEFAULT_SPEAKING_STYLE = (
    "تحدث بشكل طبيعي وواضح ومريح."
)


# ==========================================================
# DATABASE
# ==========================================================

class Database:

    def __init__(self, path="myai.db"):

        self.path = path

        self._lock = threading.RLock()

        self.conn = sqlite3.connect(
            self.path,
            check_same_thread=False,
            timeout=30
        )

        # ==================================================
        # IMPORTANT:
        # main.py uses .get() on database results.
        # Therefore SQLite rows are returned as dictionaries.
        # ==================================================

        self.conn.row_factory = (
            lambda cursor, row: {
                cursor.description[index][0]: value
                for index, value in enumerate(row)
            }
        )

        self.conn.execute(
            "PRAGMA journal_mode=WAL"
        )

        self.conn.execute(
            "PRAGMA synchronous=NORMAL"
        )

        self.conn.execute(
            "PRAGMA foreign_keys=ON"
        )

        self.conn.execute(
            "PRAGMA busy_timeout=30000"
        )

        self._create_tables()

        self._repair_tables()

        self._migrate_old_models()

        self._ensure_dm_character()


    # ======================================================
    # CONNECTION HELPERS
    # ======================================================

    def _commit(self):

        self.conn.commit()


    def _execute(
        self,
        query,
        params=()
    ):

        with self._lock:

            cursor = self.conn.execute(
                query,
                params
            )

            self.conn.commit()

            return cursor


    def _executemany(
        self,
        query,
        params
    ):

        with self._lock:

            cursor = self.conn.executemany(
                query,
                params
            )

            self.conn.commit()

            return cursor


    # ======================================================
    # TABLE CREATION
    # ======================================================

    def _create_tables(self):

        with self._lock:

            # ------------------------------------------------
            # CHARACTERS
            # ------------------------------------------------

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS characters (

                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    guild_id INTEGER NOT NULL,

                    name TEXT NOT NULL,

                    personality TEXT NOT NULL
                        DEFAULT '',

                    character_type TEXT NOT NULL
                        DEFAULT 'normal',

                    custom_instructions TEXT
                        DEFAULT '',

                    speaking_style TEXT
                        DEFAULT '',

                    provider TEXT
                        DEFAULT 'google',

                    model TEXT
                        DEFAULT 'gemini-3.5-flash-lite',

                    created_by INTEGER
                        DEFAULT 0,

                    created_at TEXT
                        DEFAULT CURRENT_TIMESTAMP,

                    UNIQUE (
                        guild_id,
                        name
                    )
                )
                """
            )


            # ------------------------------------------------
            # MESSAGES
            # ------------------------------------------------

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
                        DEFAULT CURRENT_TIMESTAMP
                )
                """
            )


            # ------------------------------------------------
            # GUILD SETTINGS
            # ------------------------------------------------

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_settings (

                    guild_id INTEGER PRIMARY KEY,

                    active_character TEXT,

                    active_provider TEXT
                        DEFAULT 'google',

                    active_model TEXT
                        DEFAULT 'gemini-3.5-flash-lite',

                    ai_enabled INTEGER
                        DEFAULT 0,

                    ai_channel_id INTEGER,

                    ai_mode TEXT
                        DEFAULT 'normal',

                    reply_type TEXT
                        DEFAULT 'mention',

                    permission_preset TEXT
                        DEFAULT 'default',

                    updated_at TEXT
                        DEFAULT CURRENT_TIMESTAMP
                )
                """
            )


            # ------------------------------------------------
            # AI CONFIG
            # ------------------------------------------------

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_config (

                    guild_id INTEGER PRIMARY KEY,

                    enabled INTEGER
                        DEFAULT 0,

                    channel_id INTEGER,

                    mode TEXT
                        DEFAULT 'normal',

                    reply_type TEXT
                        DEFAULT 'mention',

                    character_name TEXT,

                    permission_preset TEXT
                        DEFAULT 'default',

                    provider TEXT
                        DEFAULT 'google',

                    model TEXT
                        DEFAULT 'gemini-3.5-flash-lite',

                    allow_management INTEGER
                        DEFAULT 1,

                    allow_channel_management INTEGER
                        DEFAULT 1,

                    allow_role_management INTEGER
                        DEFAULT 1,

                    updated_at TEXT
                        DEFAULT CURRENT_TIMESTAMP
                )
                """
            )


            # ------------------------------------------------
            # DM SETTINGS
            # ------------------------------------------------

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_dm_settings (

                    user_id INTEGER PRIMARY KEY,

                    enabled INTEGER
                        DEFAULT 0,

                    updated_at TEXT
                        DEFAULT CURRENT_TIMESTAMP
                )
                """
            )


            # ------------------------------------------------
            # INDEXES
            # ------------------------------------------------

            self.conn.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_messages_guild_channel
                ON messages (
                    guild_id,
                    channel_id,
                    id
                )
                """
            )

            self.conn.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_messages_user
                ON messages (
                    guild_id,
                    user_id,
                    id
                )
                """
            )

            self.conn.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_characters_guild
                ON characters (
                    guild_id
                )
                """
            )

            self.conn.commit()


    # ======================================================
    # TABLE REPAIR
    # ======================================================

    def _column_names(
        self,
        table
    ):

        cursor = self.conn.execute(
            f"PRAGMA table_info({table})"
        )

        return {
            row["name"]
            for row in cursor.fetchall()
        }


    def _add_column_if_missing(
        self,
        table,
        column,
        definition
    ):

        columns = self._column_names(
            table
        )

        if column not in columns:

            self.conn.execute(
                f"""
                ALTER TABLE {table}
                ADD COLUMN {column} {definition}
                """
            )


    def _repair_tables(self):

        with self._lock:

            # ------------------------------------------------
            # CHARACTERS
            # ------------------------------------------------

            self._add_column_if_missing(
                "characters",
                "personality",
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


            # ------------------------------------------------
            # MESSAGES
            # ------------------------------------------------

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


            # ------------------------------------------------
            # GUILD SETTINGS
            # ------------------------------------------------

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
                "INTEGER DEFAULT 0"
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


            # ------------------------------------------------
            # AI CONFIG
            # ------------------------------------------------

            self._add_column_if_missing(
                "ai_config",
                "enabled",
                "INTEGER DEFAULT 0"
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


            # ------------------------------------------------
            # DM SETTINGS
            # ------------------------------------------------

            self._add_column_if_missing(
                "ai_dm_settings",
                "enabled",
                "INTEGER DEFAULT 0"
            )

            self._add_column_if_missing(
                "ai_dm_settings",
                "updated_at",
                "TEXT"
            )


            # ------------------------------------------------
            # NORMALIZE CHARACTER VALUES
            # ------------------------------------------------

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
                UPDATE characters
                SET personality = ''
                WHERE personality IS NULL
                """
            )

            self.conn.execute(
                """
                UPDATE characters
                SET custom_instructions = ''
                WHERE custom_instructions IS NULL
                """
            )

            self.conn.execute(
                """
                UPDATE characters
                SET speaking_style = ''
                WHERE speaking_style IS NULL
                """
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
                (
                    CURRENT_GOOGLE_MODEL,
                )
            )

            self.conn.commit()


    # ======================================================
    # MODEL MIGRATION
    # ======================================================

    def _migrate_old_models(self):

        old_models = (
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-3.6-flash",
        )

        with self._lock:

            for old_model in old_models:

                self.conn.execute(
                    """
                    UPDATE characters
                    SET model = ?
                    WHERE model = ?
                    """,
                    (
                        CURRENT_GOOGLE_MODEL,
                        old_model
                    )
                )

                self.conn.execute(
                    """
                    UPDATE ai_config
                    SET model = ?
                    WHERE model = ?
                    """,
                    (
                        CURRENT_GOOGLE_MODEL,
                        old_model
                    )
                )

                self.conn.execute(
                    """
                    UPDATE guild_settings
                    SET active_model = ?
                    WHERE active_model = ?
                    """,
                    (
                        CURRENT_GOOGLE_MODEL,
                        old_model
                    )
                )

            self.conn.commit()


    # ======================================================
    # VALIDATION
    # ======================================================

    def _validate_character_name(
        self,
        name
    ):

        name = str(
            name or ""
        ).strip()

        if not name:

            raise ValueError(
                "اسم الشخصية لا يمكن أن يكون فارغًا."
            )

        if len(name) > 80:

            raise ValueError(
                "اسم الشخصية طويل جدًا. الحد الأقصى 80 حرفًا."
            )

        return name


    def _validate_text(
        self,
        value,
        max_length=4000
    ):

        value = str(
            value or ""
        ).strip()

        if len(value) > max_length:

            raise ValueError(
                f"النص طويل جدًا. الحد الأقصى {max_length} حرف."
            )

        return value


    def _now(self):

        return datetime.now(
            timezone.utc
        ).isoformat()


    # ======================================================
    # DEFAULT DM CHARACTER
    # ======================================================

    def _ensure_dm_character(self):

        existing = self.get_character(
            DM_GUILD_ID,
            DM_CHARACTER_NAME
        )

        if existing:

            return

        try:

            self.create_character(
                guild_id=DM_GUILD_ID,
                name=DM_CHARACTER_NAME,
                personality=(
                    "مساعد ذكاء اصطناعي ودود ومتوازن."
                ),
                character_type="friendly",
                custom_instructions=(
                    "ساعد المستخدم بشكل واضح ومفيد."
                ),
                speaking_style=(
                    "تحدث بطريقة ودية وطبيعية."
                ),
                provider="google",
                model=CURRENT_GOOGLE_MODEL,
                created_by=0
            )

        except sqlite3.IntegrityError:

            pass


    # ======================================================
    # CHARACTER CREATE
    # ======================================================

    def create_character(
        self,
        guild_id,
        name,
        personality="",
        character_type=DEFAULT_CHARACTER_TYPE,
        custom_instructions="",
        speaking_style="",
        provider="google",
        model=None,
        created_by=0
    ):

        if guild_id is None:

            raise ValueError(
                "guild_id غير صالح."
            )

        name = self._validate_character_name(
            name
        )

        personality = self._validate_text(
            personality,
            4000
        )

        custom_instructions = self._validate_text(
            custom_instructions,
            4000
        )

        speaking_style = self._validate_text(
            speaking_style,
            2000
        )

        character_type = str(
            character_type
            or DEFAULT_CHARACTER_TYPE
        ).strip()

        provider = str(
            provider
            or "google"
        ).strip().lower()

        model = str(
            model
            or CURRENT_GOOGLE_MODEL
        ).strip()

        created_at = self._now()

        with self._lock:

            existing = self.conn.execute(
                """
                SELECT *
                FROM characters
                WHERE guild_id = ?
                  AND name = ?
                LIMIT 1
                """,
                (
                    int(guild_id),
                    name
                )
            ).fetchone()

            if existing:

                raise ValueError(
                    f"الشخصية **{name}** موجودة بالفعل."
                )

            cursor = self.conn.execute(
                """
                INSERT INTO characters (

                    guild_id,
                    name,
                    personality,
                    character_type,
                    custom_instructions,
                    speaking_style,
                    provider,
                    model,
                    created_by,
                    created_at

                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(guild_id),
                    name,
                    personality,
                    character_type,
                    custom_instructions,
                    speaking_style,
                    provider,
                    model,
                    int(created_by or 0),
                    created_at
                )
            )

            self.conn.commit()

            character_id = cursor.lastrowid

        return self.get_character_by_id(
            character_id
        )


    # ======================================================
    # GET CHARACTER
    # ======================================================

    def get_character(
        self,
        guild_id,
        name
    ):

        if guild_id is None or not name:

            return None

        with self._lock:

            row = self.conn.execute(
                """
                SELECT *
                FROM characters
                WHERE guild_id = ?
                  AND name = ?
                LIMIT 1
                """,
                (
                    int(guild_id),
                    str(name).strip()
                )
            ).fetchone()

        return row


    def get_character_by_id(
        self,
        character_id
    ):

        if character_id is None:

            return None

        with self._lock:

            return self.conn.execute(
                """
                SELECT *
                FROM characters
                WHERE id = ?
                LIMIT 1
                """,
                (
                    int(character_id),
                )
            ).fetchone()


    # ======================================================
    # GET CHARACTERS
    # ======================================================

    def get_characters(
        self,
        guild_id
    ):

        if guild_id is None:

            return []

        with self._lock:

            return self.conn.execute(
                """
                SELECT *
                FROM characters
                WHERE guild_id = ?
                ORDER BY id ASC
                """,
                (
                    int(guild_id),
                )
            ).fetchall()


    def list_characters(
        self,
        guild_id
    ):

        return self.get_characters(
            guild_id
        )


    # ======================================================
    # UPDATE CHARACTER
    # ======================================================

    def update_character(
        self,
        guild_id,
        name,
        character_type=None,
        custom_instructions=None,
        speaking_style=None,
        personality=None,
        provider=None,
        model=None,
        editor_id=None
    ):

        character = self.get_character(
            guild_id,
            name
        )

        if not character:

            raise ValueError(
                "الشخصية غير موجودة."
            )


        # --------------------------------------------------
        # SYSTEM CHARACTER PROTECTION
        # --------------------------------------------------

        if (
            int(guild_id) == DM_GUILD_ID
            and name == DM_CHARACTER_NAME
        ):

            raise PermissionError(
                "لا يمكن تعديل شخصية MyAI الأساسية."
            )


        # --------------------------------------------------
        # OWNER SECURITY
        # --------------------------------------------------

        owner_id = character.get(
            "created_by"
        )

        try:

            owner_id = int(
                owner_id or 0
            )

        except Exception:

            owner_id = 0


        try:

            editor_id = int(
                editor_id
                if editor_id is not None
                else 0
            )

        except Exception:

            editor_id = 0


        if owner_id != editor_id:

            raise PermissionError(
                "لا يمكنك تعديل شخصية شخص آخر."
            )


        # --------------------------------------------------
        # BUILD UPDATE
        # --------------------------------------------------

        updates = []

        values = []


        if character_type is not None:

            updates.append(
                "character_type = ?"
            )

            values.append(
                str(
                    character_type
                ).strip()
            )


        if custom_instructions is not None:

            updates.append(
                "custom_instructions = ?"
            )

            values.append(
                self._validate_text(
                    custom_instructions,
                    4000
                )
            )


        if speaking_style is not None:

            updates.append(
                "speaking_style = ?"
            )

            values.append(
                self._validate_text(
                    speaking_style,
                    2000
                )
            )


        if personality is not None:

            updates.append(
                "personality = ?"
            )

            values.append(
                self._validate_text(
                    personality,
                    4000
                )
            )


        if provider is not None:

            updates.append(
                "provider = ?"
            )

            values.append(
                str(
                    provider
                ).strip().lower()
            )


        if model is not None:

            updates.append(
                "model = ?"
            )

            values.append(
                str(
                    model
                ).strip()
            )


        if not updates:

            return character


        values.extend(
            [
                int(guild_id),
                str(name).strip()
            ]
        )


        with self._lock:

            self.conn.execute(
                f"""
                UPDATE characters
                SET {", ".join(updates)}
                WHERE guild_id = ?
                  AND name = ?
                """,
                values
            )

            self.conn.commit()


        return self.get_character(
            guild_id,
            name
        )


    # ======================================================
    # DELETE CHARACTER
    # ======================================================

    def delete_character(
        self,
        guild_id,
        name,
        requester_id=None
    ):

        character = self.get_character(
            guild_id,
            name
        )

        if not character:

            raise ValueError(
                "الشخصية غير موجودة."
            )


        # --------------------------------------------------
        # SYSTEM CHARACTER PROTECTION
        # --------------------------------------------------

        if (
            int(guild_id) == DM_GUILD_ID
            and name == DM_CHARACTER_NAME
        ):

            raise PermissionError(
                "لا يمكن حذف شخصية MyAI الأساسية."
            )


        # --------------------------------------------------
        # OWNER SECURITY
        # --------------------------------------------------

        owner_id = character.get(
            "created_by"
        )

        try:

            owner_id = int(
                owner_id or 0
            )

        except Exception:

            owner_id = 0


        try:

            requester_id = int(
                requester_id
                if requester_id is not None
                else 0
            )

        except Exception:

            requester_id = 0


        if owner_id != requester_id:

            raise PermissionError(
                "لا يمكنك حذف شخصية شخص آخر."
            )


        with self._lock:

            self.conn.execute(
                """
                DELETE FROM characters
                WHERE guild_id = ?
                  AND name = ?
                """,
                (
                    int(guild_id),
                    str(name).strip()
                )
            )


            # ------------------------------------------------
            # CLEAR ACTIVE CHARACTER
            # ------------------------------------------------

            self.conn.execute(
                """
                UPDATE guild_settings
                SET active_character = NULL,
                    updated_at = ?
                WHERE guild_id = ?
                  AND active_character = ?
                """,
                (
                    self._now(),
                    int(guild_id),
                    str(name).strip()
                )
            )


            self.conn.execute(
                """
                UPDATE ai_config
                SET character_name = NULL,
                    updated_at = ?
                WHERE guild_id = ?
                  AND character_name = ?
                """,
                (
                    self._now(),
                    int(guild_id),
                    str(name).strip()
                )
            )

            self.conn.commit()


        return True


    # ======================================================
    # AI CONFIG
    # ======================================================

    def get_ai_config(
        self,
        guild_id
    ):

        if guild_id is None:

            return self._default_ai_config()


        with self._lock:

            row = self.conn.execute(
                """
                SELECT *
                FROM ai_config
                WHERE guild_id = ?
                LIMIT 1
                """,
                (
                    int(guild_id),
                )
            ).fetchone()


        if row is None:

            self.save_ai_config(
                guild_id
            )

            with self._lock:

                row = self.conn.execute(
                    """
                    SELECT *
                    FROM ai_config
                    WHERE guild_id = ?
                    LIMIT 1
                    """,
                    (
                        int(guild_id),
                    )
                ).fetchone()


        return row


    def _default_ai_config(self):

        return {
            "guild_id": 0,
            "enabled": 0,
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
            "updated_at": self._now()
        }


    # ======================================================
    # GUILD CONFIG ALIAS
    # ======================================================

    def get_guild_config(
        self,
        guild_id
    ):

        return self.get_ai_config(
            guild_id
        )


    # ======================================================
    # SAVE AI CONFIG
    # ======================================================

    def save_ai_config(
        self,
        guild_id,
        enabled=None,
        channel_id=None,
        mode=None,
        reply_type=None,
        character_name=None,
        permission_preset=None,
        provider=None,
        model=None,
        allow_management=None,
        allow_channel_management=None,
        allow_role_management=None
    ):

        if guild_id is None:

            raise ValueError(
                "guild_id غير صالح."
            )

        guild_id = int(
            guild_id
        )


        # --------------------------------------------------
        # IMPORTANT:
        # Do NOT call get_ai_config() here if the row doesn't
        # exist because get_ai_config() itself creates it.
        # --------------------------------------------------

        with self._lock:

            existing = self.conn.execute(
                """
                SELECT *
                FROM ai_config
                WHERE guild_id = ?
                LIMIT 1
                """,
                (
                    guild_id,
                )
            ).fetchone()


        if existing is None:

            existing = self._default_ai_config()


        # --------------------------------------------------
        # Preserve existing values
        # --------------------------------------------------

        final_enabled = (
            int(bool(enabled))
            if enabled is not None
            else int(
                existing.get(
                    "enabled",
                    0
                )
            )
        )


        final_channel_id = (
            int(channel_id)
            if channel_id is not None
            else existing.get(
                "channel_id"
            )
        )


        final_mode = (
            str(mode)
            if mode is not None
            else existing.get(
                "mode",
                "normal"
            )
        )


        final_reply_type = (
            str(reply_type)
            if reply_type is not None
            else existing.get(
                "reply_type",
                "mention"
            )
        )


        final_character = (
            str(character_name)
            if character_name is not None
            else existing.get(
                "character_name"
            )
        )


        final_permission = (
            str(permission_preset)
            if permission_preset is not None
            else existing.get(
                "permission_preset",
                "default"
            )
        )


        final_provider = (
            str(provider).lower()
            if provider is not None
            else existing.get(
                "provider",
                "google"
            )
        )


        final_model = (
            str(model)
            if model is not None
            else existing.get(
                "model",
                CURRENT_GOOGLE_MODEL
            )
        )


        final_management = (
            int(bool(allow_management))
            if allow_management is not None
            else int(
                existing.get(
                    "allow_management",
                    1
                )
            )
        )


        final_channel_management = (
            int(bool(allow_channel_management))
            if allow_channel_management is not None
            else int(
                existing.get(
                    "allow_channel_management",
                    1
                )
            )
        )


        final_role_management = (
            int(bool(allow_role_management))
            if allow_role_management is not None
            else int(
                existing.get(
                    "allow_role_management",
                    1
                )
            )
        )


        now = self._now()


        with self._lock:

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

                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?
                )

                ON CONFLICT(guild_id)
                DO UPDATE SET

                    enabled =
                        excluded.enabled,

                    channel_id =
                        excluded.channel_id,

                    mode =
                        excluded.mode,

                    reply_type =
                        excluded.reply_type,

                    character_name =
                        excluded.character_name,

                    permission_preset =
                        excluded.permission_preset,

                    provider =
                        excluded.provider,

                    model =
                        excluded.model,

                    allow_management =
                        excluded.allow_management,

                    allow_channel_management =
                        excluded.allow_channel_management,

                    allow_role_management =
                        excluded.allow_role_management,

                    updated_at =
                        excluded.updated_at
                """,
                (
                    guild_id,
                    final_enabled,
                    final_channel_id,
                    final_mode,
                    final_reply_type,
                    final_character,
                    final_permission,
                    final_provider,
                    final_model,
                    final_management,
                    final_channel_management,
                    final_role_management,
                    now
                )
            )

            self.conn.commit()


        self._sync_guild_settings(
            guild_id
        )


        return self.get_ai_config(
            guild_id
        )


    # ======================================================
    # UPDATE GUILD CONFIG
    # ======================================================

    def update_guild_config(
        self,
        guild_id,
        **kwargs
    ):

        return self.save_ai_config(
            guild_id,
            **kwargs
        )


    # ======================================================
    # GUILD SETTINGS SYNC
    # ======================================================

    def _sync_guild_settings(
        self,
        guild_id
    ):

        with self._lock:

            config = self.conn.execute(
                """
                SELECT *
                FROM ai_config
                WHERE guild_id = ?
                LIMIT 1
                """,
                (
                    int(guild_id),
                )
            ).fetchone()


        if not config:

            return


        with self._lock:

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

                    active_character =
                        excluded.active_character,

                    active_provider =
                        excluded.active_provider,

                    active_model =
                        excluded.active_model,

                    ai_enabled =
                        excluded.ai_enabled,

                    ai_channel_id =
                        excluded.ai_channel_id,

                    ai_mode =
                        excluded.ai_mode,

                    reply_type =
                        excluded.reply_type,

                    permission_preset =
                        excluded.permission_preset,

                    updated_at =
                        excluded.updated_at
                """,
                (
                    int(guild_id),
                    config.get(
                        "character_name"
                    ),
                    config.get(
                        "provider",
                        "google"
                    ),
                    config.get(
                        "model",
                        CURRENT_GOOGLE_MODEL
                    ),
                    config.get(
                        "enabled",
                        0
                    ),
                    config.get(
                        "channel_id"
                    ),
                    config.get(
                        "mode",
                        "normal"
                    ),
                    config.get(
                        "reply_type",
                        "mention"
                    ),
                    config.get(
                        "permission_preset",
                        "default"
                    ),
                    self._now()
                )
            )

            self.conn.commit()


    # ======================================================
    # GET GUILD SETTINGS
    # ======================================================

    def get_guild_settings(
        self,
        guild_id
    ):

        if guild_id is None:

            return None

        with self._lock:

            return self.conn.execute(
                """
                SELECT *
                FROM guild_settings
                WHERE guild_id = ?
                LIMIT 1
                """,
                (
                    int(guild_id),
                )
            ).fetchone()


    # ======================================================
    # ACTIVE CHARACTER
    # ======================================================

    def set_active_character(
        self,
        guild_id,
        character_name
    ):

        character = self.get_character(
            guild_id,
            character_name
        )

        if not character:

            raise ValueError(
                f"الشخصية **{character_name}** غير موجودة."
            )


        now = self._now()

        provider = character.get(
            "provider",
            "google"
        )

        model = character.get(
            "model",
            CURRENT_GOOGLE_MODEL
        )


        with self._lock:

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

                VALUES (
                    ?, 0, NULL, 'normal', 'mention',
                    ?, 'default', ?, ?, 1, 1, 1, ?
                )

                ON CONFLICT(guild_id)
                DO UPDATE SET

                    character_name =
                        excluded.character_name,

                    provider =
                        excluded.provider,

                    model =
                        excluded.model,

                    updated_at =
                        excluded.updated_at
                """,
                (
                    int(guild_id),
                    character_name,
                    provider,
                    model,
                    now
                )
            )


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

                VALUES (
                    ?, ?, ?, ?, 0, NULL,
                    'normal', 'mention',
                    'default', ?
                )

                ON CONFLICT(guild_id)
                DO UPDATE SET

                    active_character =
                        excluded.active_character,

                    active_provider =
                        excluded.active_provider,

                    active_model =
                        excluded.active_model,

                    updated_at =
                        excluded.updated_at
                """,
                (
                    int(guild_id),
                    character_name,
                    provider,
                    model,
                    now
                )
            )

            self.conn.commit()


        return self.get_ai_config(
            guild_id
        )


    def get_active_character(
        self,
        guild_id
    ):

        config = self.get_ai_config(
            guild_id
        )

        if not config:

            return None

        character_name = config.get(
            "character_name"
        )

        if not character_name:

            return None

        return self.get_character(
            guild_id,
            character_name
        )


    # ======================================================
    # MESSAGE MEMORY
    # ======================================================

    def add_message(
        self,
        guild_id,
        channel_id,
        user_id,
        role,
        content,
        character_name=None
    ):

        content = str(
            content or ""
        ).strip()

        if not content:

            return None


        with self._lock:

            cursor = self.conn.execute(
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
                    int(guild_id),
                    int(channel_id),
                    int(user_id),
                    character_name,
                    str(role),
                    content,
                    self._now()
                )
            )

            self.conn.commit()

            return cursor.lastrowid


    def get_history(
        self,
        guild_id,
        channel_id=None,
        user_id=None,
        character_name=None,
        limit=20
    ):

        try:

            limit = max(
                1,
                min(
                    int(limit),
                    100
                )
            )

        except Exception:

            limit = 20


        conditions = [
            "guild_id = ?"
        ]

        params = [
            int(guild_id)
        ]


        if channel_id is not None:

            conditions.append(
                "channel_id = ?"
            )

            params.append(
                int(channel_id)
            )


        if user_id is not None:

            conditions.append(
                "user_id = ?"
            )

            params.append(
                int(user_id)
            )


        if character_name:

            conditions.append(
                "character_name = ?"
            )

            params.append(
                str(character_name)
            )


        query = f"""
            SELECT *
            FROM messages
            WHERE {" AND ".join(conditions)}
            ORDER BY id DESC
            LIMIT ?
        """

        params.append(
            limit
        )


        with self._lock:

            rows = self.conn.execute(
                query,
                tuple(params)
            ).fetchall()


        # Oldest -> newest
        rows.reverse()

        return rows


    # ======================================================
    # CLEAR HISTORY
    # ======================================================

    def clear_history(
        self,
        guild_id,
        channel_id=None
    ):

        with self._lock:

            if channel_id is None:

                cursor = self.conn.execute(
                    """
                    DELETE FROM messages
                    WHERE guild_id = ?
                    """,
                    (
                        int(guild_id),
                    )
                )

            else:

                cursor = self.conn.execute(
                    """
                    DELETE FROM messages
                    WHERE guild_id = ?
                      AND channel_id = ?
                    """,
                    (
                        int(guild_id),
                        int(channel_id)
                    )
                )

            self.conn.commit()

            return cursor.rowcount


    def clear_memory(
        self,
        guild_id,
        channel_id=None
    ):

        return self.clear_history(
            guild_id,
            channel_id
        )


    # ======================================================
    # DM SETTINGS
    # ======================================================

    def get_dm_enabled(
        self,
        user_id
    ):

        if user_id is None:

            return False


        with self._lock:

            row = self.conn.execute(
                """
                SELECT enabled
                FROM ai_dm_settings
                WHERE user_id = ?
                LIMIT 1
                """,
                (
                    int(user_id),
                )
            ).fetchone()


        if not row:

            return False


        return bool(
            row.get(
                "enabled",
                0
            )
        )


    def set_dm_enabled(
        self,
        user_id,
        enabled
    ):

        if user_id is None:

            raise ValueError(
                "user_id غير صالح."
            )


        with self._lock:

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

                    enabled =
                        excluded.enabled,

                    updated_at =
                        excluded.updated_at
                """,
                (
                    int(user_id),
                    int(bool(enabled)),
                    self._now()
                )
            )

            self.conn.commit()


        return bool(enabled)


    # ======================================================
    # CLOSE
    # ======================================================

    def close(self):

        with self._lock:

            try:

                self.conn.commit()

            except Exception:
                pass


            try:

                self.conn.close()

            except Exception:
                pass


    # ======================================================
    # CONTEXT MANAGER
    # ======================================================

    def __enter__(self):

        return self


    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback_value
    ):

        self.close()
         
