import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class Database:
    """
    SQLite database layer for MyAI BOT.

    Compatible with:
    - main.py
    - ai_engine.py
    - existing myai.db databases
    - character system
    - AI configuration
    - chat history / memory
    - DM settings
    """

    CURRENT_GOOGLE_MODEL = "gemini-3.5-flash-lite"

    DM_GUILD_ID = 0
    DM_CHARACTER_NAME = "مساعد MyAI"

    DEFAULT_SERVER_CHARACTER = "مساعد السيرفر جيميناي"

    DEFAULT_PERSONALITY = (
        "مساعد ذكاء اصطناعي ودود وذكي يساعد أعضاء السيرفر "
        "ويجيب بوضوح واحترام."
    )

    DEFAULT_DESCRIPTION = (
        "شخصية الذكاء الاصطناعي الافتراضية للسيرفر."
    )

    DEFAULT_SPEAKING_STYLE = (
        "طبيعي، واضح، ودود، ومختصر عند الحاجة."
    )

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = (
            db_path
            or os.getenv("DATABASE_PATH")
            or os.getenv("DB_PATH")
            or "myai.db"
        )

        self._lock = threading.RLock()

        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=10,
        )

        # مهم جدًا:
        # main.py يستخدم config.get(...)
        # لذلك لا نستخدم sqlite3.Row هنا.
        self.conn.row_factory = self._dict_factory

        self._configure_sqlite()
        self._create_tables()
        self._repair_characters_table()
        self._repair_messages_table()
        self._repair_settings_tables()
        self._create_dm_tables()
        self._migrate_old_models()
        self._ensure_dm_character()

    # ============================================================
    # BASIC HELPERS
    # ============================================================

    @staticmethod
    def _dict_factory(cursor, row):
        """
        Return normal dictionaries instead of sqlite3.Row.

        This fixes:
            AttributeError: 'sqlite3.Row' object has no attribute 'get'
        """
        columns = [column[0] for column in cursor.description]
        return {
            columns[index]: value
            for index, value in enumerate(row)
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_bool(value) -> bool:
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            return value.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
                "enabled",
            }

        return bool(value)

    @staticmethod
    def _validate_character_name(name: str) -> str:
        if name is None:
            raise ValueError("اسم الشخصية مطلوب.")

        name = str(name).strip()

        if not name:
            raise ValueError("اسم الشخصية لا يمكن أن يكون فارغًا.")

        if len(name) > 100:
            raise ValueError(
                "اسم الشخصية طويل جدًا. الحد الأقصى 100 حرف."
            )

        return name

    @staticmethod
    def _validate_text(
        value: Optional[str],
        field_name: str,
        max_length: int,
        allow_empty: bool = True,
    ) -> Optional[str]:

        if value is None:
            return None

        value = str(value).strip()

        if not allow_empty and not value:
            raise ValueError(
                f"{field_name} لا يمكن أن يكون فارغًا."
            )

        if len(value) > max_length:
            raise ValueError(
                f"{field_name} طويل جدًا. الحد الأقصى {max_length} حرف."
            )

        return value

    def _configure_sqlite(self):
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA synchronous=NORMAL;")
            self.conn.execute("PRAGMA foreign_keys=ON;")
            self.conn.execute("PRAGMA busy_timeout=5000;")
            self.conn.commit()

    def _table_columns(self, table_name: str) -> set:
        with self._lock:
            rows = self.conn.execute(
                f"PRAGMA table_info({table_name})"
            ).fetchall()

        return {
            row["name"]
            for row in rows
        }

    def _ensure_column(
        self,
        table_name: str,
        column_name: str,
        definition: str,
    ):
        columns = self._table_columns(table_name)

        if column_name in columns:
            return

        with self._lock:
            self.conn.execute(
                f"ALTER TABLE {table_name} "
                f"ADD COLUMN {column_name} {definition}"
            )
            self.conn.commit()

    # ============================================================
    # TABLE CREATION
    # ============================================================

    def _create_tables(self):
        with self._lock:

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS characters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    personality TEXT NOT NULL DEFAULT '',
                    character_type TEXT NOT NULL DEFAULT 'normal',
                    custom_instructions TEXT NOT NULL DEFAULT '',
                    speaking_style TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT 'google',
                    model TEXT NOT NULL DEFAULT 'gemini-3.5-flash-lite',
                    created_by INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER,
                    user_id INTEGER,
                    character_name TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    active_character TEXT,
                    active_provider TEXT DEFAULT 'google',
                    active_model TEXT DEFAULT 'gemini-3.5-flash-lite',
                    ai_enabled INTEGER DEFAULT 0,
                    ai_channel_id INTEGER,
                    ai_mode TEXT DEFAULT 'normal',
                    reply_type TEXT DEFAULT 'mention',
                    permission_preset TEXT DEFAULT 'top3',
                    updated_at TEXT
                )
                """
            )

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_config (
                    guild_id INTEGER PRIMARY KEY,
                    enabled INTEGER DEFAULT 0,
                    channel_id INTEGER,
                    mode TEXT DEFAULT 'normal',
                    reply_type TEXT DEFAULT 'mention',
                    character_name TEXT DEFAULT 'مساعد السيرفر جيميناي',
                    permission_preset TEXT DEFAULT 'top3',
                    provider TEXT DEFAULT 'google',
                    model TEXT DEFAULT 'gemini-3.5-flash-lite',
                    allow_management INTEGER DEFAULT 1,
                    allow_channel_management INTEGER DEFAULT 1,
                    allow_role_management INTEGER DEFAULT 1,
                    updated_at TEXT
                )
                """
            )

            self.conn.commit()

            self.conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_characters_guild_name
                ON characters(guild_id, name)
                """
            )

            self.conn.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_messages_lookup
                ON messages(
                    guild_id,
                    channel_id,
                    user_id,
                    character_name,
                    id
                )
                """
            )

            self.conn.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_messages_guild
                ON messages(guild_id, id)
                """
            )

            self.conn.commit()

    # ============================================================
    # DATABASE REPAIR / MIGRATION
    # ============================================================

    def _repair_characters_table(self):
        """
        Repairs old character databases without deleting data.
        """

        required_columns = {
            "description": "TEXT NOT NULL DEFAULT ''",
            "personality": "TEXT NOT NULL DEFAULT ''",
            "character_type": "TEXT NOT NULL DEFAULT 'normal'",
            "custom_instructions": "TEXT NOT NULL DEFAULT ''",
            "speaking_style": "TEXT NOT NULL DEFAULT ''",
            "provider": "TEXT NOT NULL DEFAULT 'google'",
            "model": "TEXT NOT NULL DEFAULT 'gemini-3.5-flash-lite'",
            "created_by": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "TEXT",
        }

        for column, definition in required_columns.items():
            try:
                self._ensure_column(
                    "characters",
                    column,
                    definition,
                )
            except sqlite3.OperationalError:
                pass

        with self._lock:
            self.conn.execute(
                """
                UPDATE characters
                SET description = ''
                WHERE description IS NULL
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
                SET character_type = 'normal'
                WHERE character_type IS NULL
                   OR character_type = ''
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
                (self.CURRENT_GOOGLE_MODEL,),
            )

            self.conn.execute(
                """
                UPDATE characters
                SET created_at = ?
                WHERE created_at IS NULL
                   OR created_at = ''
                """,
                (self._now(),),
            )

            self.conn.commit()

    def _repair_messages_table(self):
        """
        Repairs old messages table.
        """

        required_columns = {
            "guild_id": "INTEGER",
            "channel_id": "INTEGER",
            "user_id": "INTEGER",
            "character_name": "TEXT",
            "role": "TEXT NOT NULL DEFAULT 'user'",
            "content": "TEXT NOT NULL DEFAULT ''",
            "created_at": "TEXT",
        }

        for column, definition in required_columns.items():
            try:
                self._ensure_column(
                    "messages",
                    column,
                    definition,
                )
            except sqlite3.OperationalError:
                pass

        with self._lock:
            self.conn.execute(
                """
                UPDATE messages
                SET role = 'user'
                WHERE role IS NULL
                   OR role = ''
                """
            )

            self.conn.execute(
                """
                UPDATE messages
                SET content = ''
                WHERE content IS NULL
                """
            )

            self.conn.execute(
                """
                UPDATE messages
                SET created_at = ?
                WHERE created_at IS NULL
                   OR created_at = ''
                """,
                (self._now(),),
            )

            self.conn.commit()

    def _repair_settings_tables(self):
        """
        Repairs guild_settings and ai_config.
        """

        guild_columns = {
            "active_character": "TEXT",
            "active_provider": "TEXT DEFAULT 'google'",
            "active_model": "TEXT DEFAULT 'gemini-3.5-flash-lite'",
            "ai_enabled": "INTEGER DEFAULT 0",
            "ai_channel_id": "INTEGER",
            "ai_mode": "TEXT DEFAULT 'normal'",
            "reply_type": "TEXT DEFAULT 'mention'",
            "permission_preset": "TEXT DEFAULT 'top3'",
            "updated_at": "TEXT",
        }

        for column, definition in guild_columns.items():
            try:
                self._ensure_column(
                    "guild_settings",
                    column,
                    definition,
                )
            except sqlite3.OperationalError:
                pass

        ai_columns = {
            "enabled": "INTEGER DEFAULT 0",
            "channel_id": "INTEGER",
            "mode": "TEXT DEFAULT 'normal'",
            "reply_type": "TEXT DEFAULT 'mention'",
            "character_name": (
                "TEXT DEFAULT 'مساعد السيرفر جيميناي'"
            ),
            "permission_preset": "TEXT DEFAULT 'top3'",
            "provider": "TEXT DEFAULT 'google'",
            "model": (
                "TEXT DEFAULT 'gemini-3.5-flash-lite'"
            ),
            "allow_management": "INTEGER DEFAULT 1",
            "allow_channel_management": "INTEGER DEFAULT 1",
            "allow_role_management": "INTEGER DEFAULT 1",
            "updated_at": "TEXT",
        }

        for column, definition in ai_columns.items():
            try:
                self._ensure_column(
                    "ai_config",
                    column,
                    definition,
                )
            except sqlite3.OperationalError:
                pass

        with self._lock:
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
                (self.CURRENT_GOOGLE_MODEL,),
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
                UPDATE guild_settings
                SET permission_preset = 'top3'
                WHERE permission_preset IS NULL
                   OR permission_preset = ''
                """
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
                UPDATE ai_config
                SET character_name = ?
                WHERE character_name IS NULL
                   OR character_name = ''
                """,
                (self.DEFAULT_SERVER_CHARACTER,),
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
                (self.CURRENT_GOOGLE_MODEL,),
            )

            self.conn.execute(
                """
                UPDATE ai_config
                SET permission_preset = 'top3'
                WHERE permission_preset IS NULL
                   OR permission_preset = ''
                """
            )

            self.conn.execute(
                """
                UPDATE ai_config
                SET allow_management = 1
                WHERE allow_management IS NULL
                """
            )

            self.conn.execute(
                """
                UPDATE ai_config
                SET allow_channel_management = 1
                WHERE allow_channel_management IS NULL
                """
            )

            self.conn.execute(
                """
                UPDATE ai_config
                SET allow_role_management = 1
                WHERE allow_role_management IS NULL
                """
            )

            self.conn.commit()

    def _create_dm_tables(self):
        with self._lock:

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_dm_settings (
                    user_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT
                )
                """
            )

            self.conn.commit()

    def _migrate_old_models(self):
        """
        Replace old Gemini model names with the current model.
        """

        old_models = (
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-3.6-flash",
        )

        with self._lock:

            placeholders = ",".join(
                "?" for _ in old_models
            )

            self.conn.execute(
                f"""
                UPDATE characters
                SET model = ?
                WHERE model IN ({placeholders})
                """,
                (
                    self.CURRENT_GOOGLE_MODEL,
                    *old_models,
                ),
            )

            self.conn.execute(
                f"""
                UPDATE ai_config
                SET model = ?
                WHERE model IN ({placeholders})
                """,
                (
                    self.CURRENT_GOOGLE_MODEL,
                    *old_models,
                ),
            )

            self.conn.execute(
                f"""
                UPDATE guild_settings
                SET active_model = ?
                WHERE active_model IN ({placeholders})
                """,
                (
                    self.CURRENT_GOOGLE_MODEL,
                    *old_models,
                ),
            )

            self.conn.commit()

    # ============================================================
    # DEFAULT CHARACTERS
    # ============================================================

    def _insert_system_character(
        self,
        guild_id: int,
        name: str,
        description: str,
        personality: str,
    ):
        now = self._now()

        with self._lock:
            existing = self.conn.execute(
                """
                SELECT id
                FROM characters
                WHERE guild_id = ?
                  AND name = ?
                LIMIT 1
                """,
                (guild_id, name),
            ).fetchone()

            if existing:
                return

            self.conn.execute(
                """
                INSERT INTO characters (
                    guild_id,
                    name,
                    description,
                    personality,
                    character_type,
                    custom_instructions,
                    speaking_style,
                    provider,
                    model,
                    created_by,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    name,
                    description,
                    personality,
                    "normal",
                    "",
                    self.DEFAULT_SPEAKING_STYLE,
                    "google",
                    self.CURRENT_GOOGLE_MODEL,
                    0,
                    now,
                ),
            )

            self.conn.commit()

    def _ensure_dm_character(self):
        """
        Creates the DM system character only if it does not exist.

        No duplicate warning is generated.
        """

        self._insert_system_character(
            guild_id=self.DM_GUILD_ID,
            name=self.DM_CHARACTER_NAME,
            description="المساعد الافتراضي للمحادثات الخاصة.",
            personality=(
                "أنت مساعد MyAI في الخاص. "
                "كن ودودًا ومفيدًا وواضحًا."
            ),
        )

    def _ensure_server_character(self, guild_id: int):
        if guild_id == self.DM_GUILD_ID:
            return

        self._insert_system_character(
            guild_id=guild_id,
            name=self.DEFAULT_SERVER_CHARACTER,
            description=self.DEFAULT_DESCRIPTION,
            personality=self.DEFAULT_PERSONALITY,
        )

    # ============================================================
    # CHARACTER CREATION
    # ============================================================

    def create_character(
        self,
        guild_id,
        name,
        personality="",
        character_type="normal",
        custom_instructions="",
        speaking_style="",
        provider="google",
        model=None,
        created_by=0,
        description=None,
    ) -> Dict[str, Any]:

        guild_id = self._safe_int(guild_id)
        created_by = self._safe_int(created_by)

        name = self._validate_character_name(name)

        personality = self._validate_text(
            personality,
            "الشخصية",
            4000,
        ) or ""

        character_type = (
            str(character_type or "normal").strip()
            or "normal"
        )

        custom_instructions = self._validate_text(
            custom_instructions,
            "التعليمات",
            4000,
        ) or ""

        speaking_style = self._validate_text(
            speaking_style,
            "أسلوب الكلام",
            2000,
        ) or ""

        description = self._validate_text(
            description,
            "الوصف",
            2000,
        )

        if description is None:
            description = ""

        provider = (
            str(provider or "google")
            .strip()
            .lower()
            or "google"
        )

        model = (
            str(model or self.CURRENT_GOOGLE_MODEL)
            .strip()
            or self.CURRENT_GOOGLE_MODEL
        )

        now = self._now()

        with self._lock:

            existing = self.conn.execute(
                """
                SELECT id
                FROM characters
                WHERE guild_id = ?
                  AND name = ?
                LIMIT 1
                """,
                (guild_id, name),
            ).fetchone()

            if existing:
                raise ValueError(
                    f"الشخصية **{name}** موجودة بالفعل."
                )

            try:
                cursor = self.conn.execute(
                    """
                    INSERT INTO characters (
                        guild_id,
                        name,
                        description,
                        personality,
                        character_type,
                        custom_instructions,
                        speaking_style,
                        provider,
                        model,
                        created_by,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        name,
                        description,
                        personality,
                        character_type,
                        custom_instructions,
                        speaking_style,
                        provider,
                        model,
                        created_by,
                        now,
                    ),
                )

                character_id = cursor.lastrowid
                self.conn.commit()

            except sqlite3.IntegrityError as exc:
                self.conn.rollback()

                if "description" in str(exc).lower():
                    raise ValueError(
                        "فشل إنشاء الشخصية بسبب توافق قاعدة البيانات "
                        "مع عمود description."
                    ) from exc

                raise ValueError(
                    f"تعذر إنشاء الشخصية: {exc}"
                ) from exc

            row = self.conn.execute(
                """
                SELECT *
                FROM characters
                WHERE id = ?
                """,
                (character_id,),
            ).fetchone()

        return dict(row) if row else {}

    # ============================================================
    # CHARACTER READ
    # ============================================================

    def get_character(
        self,
        guild_id,
        name,
    ) -> Optional[Dict[str, Any]]:

        guild_id = self._safe_int(guild_id)

        if name is None:
            return None

        name = str(name).strip()

        with self._lock:
            row = self.conn.execute(
                """
                SELECT *
                FROM characters
                WHERE guild_id = ?
                  AND name = ?
                LIMIT 1
                """,
                (guild_id, name),
            ).fetchone()

        return dict(row) if row else None

    def get_character_by_id(
        self,
        character_id,
    ) -> Optional[Dict[str, Any]]:

        character_id = self._safe_int(character_id)

        with self._lock:
            row = self.conn.execute(
                """
                SELECT *
                FROM characters
                WHERE id = ?
                LIMIT 1
                """,
                (character_id,),
            ).fetchone()

        return dict(row) if row else None

    def get_characters(
        self,
        guild_id,
    ) -> List[Dict[str, Any]]:

        guild_id = self._safe_int(guild_id)

        with self._lock:
            rows = self.conn.execute(
                """
                SELECT *
                FROM characters
                WHERE guild_id = ?
                ORDER BY id ASC
                """,
                (guild_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    def list_characters(
        self,
        guild_id,
    ) -> List[Dict[str, Any]]:
        return self.get_characters(guild_id)

    # ============================================================
    # CHARACTER UPDATE
    # ============================================================

    def update_character(
        self,
        guild_id,
        name,
        character_type=None,
        custom_instructions=None,
        speaking_style=None,
        editor_id=None,
        description=None,
        personality=None,
        provider=None,
        model=None,
    ) -> Dict[str, Any]:

        guild_id = self._safe_int(guild_id)

        character = self.get_character(
            guild_id,
            name,
        )

        if not character:
            raise ValueError(
                f"الشخصية **{name}** غير موجودة."
            )

        owner_id = self._safe_int(
            character.get("created_by"),
            0,
        )

        requester_id = self._safe_int(
            editor_id,
            0,
        )

        # System characters cannot be edited.
        if guild_id == self.DM_GUILD_ID:
            raise PermissionError(
                "لا يمكن تعديل شخصية النظام."
            )

        if owner_id == 0:
            raise PermissionError(
                "لا يمكن تعديل شخصية النظام."
            )

        if requester_id != owner_id:
            raise PermissionError(
                "فقط مالك الشخصية يستطيع تعديلها."
            )

        updates = []
        values = []

        if character_type is not None:
            updates.append("character_type = ?")
            values.append(
                str(character_type).strip()
                or "normal"
            )

        if custom_instructions is not None:
            updates.append("custom_instructions = ?")
            values.append(
                self._validate_text(
                    custom_instructions,
                    "التعليمات",
                    4000,
                ) or ""
            )

        if speaking_style is not None:
            updates.append("speaking_style = ?")
            values.append(
                self._validate_text(
                    speaking_style,
                    "أسلوب الكلام",
                    2000,
                ) or ""
            )

        if description is not None:
            updates.append("description = ?")
            values.append(
                self._validate_text(
                    description,
                    "الوصف",
                    2000,
                ) or ""
            )

        if personality is not None:
            updates.append("personality = ?")
            values.append(
                self._validate_text(
                    personality,
                    "الشخصية",
                    4000,
                ) or ""
            )

        if provider is not None:
            updates.append("provider = ?")
            values.append(
                str(provider).strip().lower()
            )

        if model is not None:
            updates.append("model = ?")
            values.append(
                str(model).strip()
            )

        if not updates:
            return character

        values.extend([
            guild_id,
            name,
        ])

        with self._lock:
            self.conn.execute(
                f"""
                UPDATE characters
                SET {", ".join(updates)}
                WHERE guild_id = ?
                  AND name = ?
                """,
                values,
            )

            self.conn.commit()

        return self.get_character(
            guild_id,
            name,
        ) or {}

    # ============================================================
    # CHARACTER DELETE
    # ============================================================

    def delete_character(
        self,
        guild_id,
        name,
        requester_id=None,
    ) -> bool:

        guild_id = self._safe_int(guild_id)

        character = self.get_character(
            guild_id,
            name,
        )

        if not character:
            raise ValueError(
                f"الشخصية **{name}** غير موجودة."
            )

        owner_id = self._safe_int(
            character.get("created_by"),
            0,
        )

        requester_id = self._safe_int(
            requester_id,
            0,
        )

        if guild_id == self.DM_GUILD_ID:
            raise PermissionError(
                "لا يمكن حذف شخصية النظام."
            )

        if owner_id == 0:
            raise PermissionError(
                "لا يمكن حذف شخصية النظام."
            )

        if requester_id != owner_id:
            raise PermissionError(
                "فقط مالك الشخصية يستطيع حذفها."
            )

        with self._lock:

            self.conn.execute(
                """
                DELETE FROM messages
                WHERE guild_id = ?
                  AND character_name = ?
                """,
                (guild_id, name),
            )

            self.conn.execute(
                """
                DELETE FROM characters
                WHERE guild_id = ?
                  AND name = ?
                """,
                (guild_id, name),
            )

            # If this was the active character,
            # return to the default character.
            self.conn.execute(
                """
                UPDATE ai_config
                SET character_name = ?,
                    updated_at = ?
                WHERE guild_id = ?
                  AND character_name = ?
                """,
                (
                    self.DEFAULT_SERVER_CHARACTER,
                    self._now(),
                    guild_id,
                    name,
                ),
            )

            self.conn.execute(
                """
                UPDATE guild_settings
                SET active_character = ?,
                    updated_at = ?
                WHERE guild_id = ?
                  AND active_character = ?
                """,
                (
                    self.DEFAULT_SERVER_CHARACTER,
                    self._now(),
                    guild_id,
                    name,
                ),
            )

            self.conn.commit()

        self._ensure_server_character(guild_id)

        return True

    # ============================================================
    # ACTIVE CHARACTER
    # ============================================================

    def set_active_character(
        self,
        guild_id,
        character,
    ) -> Dict[str, Any]:

        guild_id = self._safe_int(guild_id)

        if isinstance(character, dict):
            character_name = character.get("name")
        else:
            character_name = str(character).strip()

        if not character_name:
            raise ValueError(
                "اسم الشخصية مطلوب."
            )

        found = self.get_character(
            guild_id,
            character_name,
        )

        if not found:
            raise ValueError(
                f"الشخصية **{character_name}** غير موجودة."
            )

        now = self._now()

        with self._lock:

            self._ensure_ai_config_row_locked(
                guild_id
            )

            self._ensure_guild_settings_row_locked(
                guild_id
            )

            self.conn.execute(
                """
                UPDATE ai_config
                SET character_name = ?,
                    updated_at = ?
                WHERE guild_id = ?
                """,
                (
                    character_name,
                    now,
                    guild_id,
                ),
            )

            self.conn.execute(
                """
                UPDATE guild_settings
                SET active_character = ?,
                    updated_at = ?
                WHERE guild_id = ?
                """,
                (
                    character_name,
                    now,
                    guild_id,
                ),
            )

            self.conn.commit()

        return found

    def get_active_character(
        self,
        guild_id,
    ) -> Optional[Dict[str, Any]]:

        guild_id = self._safe_int(guild_id)

        if guild_id == self.DM_GUILD_ID:
            return self.get_character(
                self.DM_GUILD_ID,
                self.DM_CHARACTER_NAME,
            )

        config = self.get_ai_config(guild_id)

        character_name = config.get(
            "character_name"
        )

        character = self.get_character(
            guild_id,
            character_name,
        )

        if character:
            return character

        self._ensure_server_character(guild_id)

        return self.get_character(
            guild_id,
            self.DEFAULT_SERVER_CHARACTER,
        )

    # ============================================================
    # CONFIG INTERNAL HELPERS
    # ============================================================

    def _ensure_ai_config_row_locked(
        self,
        guild_id: int,
    ):
        row = self.conn.execute(
            """
            SELECT guild_id
            FROM ai_config
            WHERE guild_id = ?
            LIMIT 1
            """,
            (guild_id,),
        ).fetchone()

        if row:
            return

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
            """,
            (
                guild_id,
                0,
                None,
                "normal",
                "mention",
                self.DEFAULT_SERVER_CHARACTER,
                "top3",
                "google",
                self.CURRENT_GOOGLE_MODEL,
                1,
                1,
                1,
                self._now(),
            ),
        )

    def _ensure_guild_settings_row_locked(
        self,
        guild_id: int,
    ):
        row = self.conn.execute(
            """
            SELECT guild_id
            FROM guild_settings
            WHERE guild_id = ?
            LIMIT 1
            """,
            (guild_id,),
        ).fetchone()

        if row:
            return

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
            """,
            (
                guild_id,
                self.DEFAULT_SERVER_CHARACTER,
                "google",
                self.CURRENT_GOOGLE_MODEL,
                0,
                None,
                "normal",
                "mention",
                "top3",
                self._now(),
            ),
        )

    # ============================================================
    # AI CONFIG
    # ============================================================

    def get_ai_config(
        self,
        guild_id,
    ) -> Dict[str, Any]:

        guild_id = self._safe_int(guild_id)

        if guild_id == self.DM_GUILD_ID:
            return {
                "guild_id": self.DM_GUILD_ID,
                "enabled": 1,
                "channel_id": None,
                "mode": "normal",
                "reply_type": "direct",
                "character_name": self.DM_CHARACTER_NAME,
                "permission_preset": "top3",
                "provider": "google",
                "model": self.CURRENT_GOOGLE_MODEL,
                "allow_management": 1,
                "allow_channel_management": 1,
                "allow_role_management": 1,
                "updated_at": self._now(),
            }

        self._ensure_server_character(guild_id)

        with self._lock:

            self._ensure_ai_config_row_locked(
                guild_id
            )

            self._ensure_guild_settings_row_locked(
                guild_id
            )

            self.conn.commit()

            row = self.conn.execute(
                """
                SELECT *
                FROM ai_config
                WHERE guild_id = ?
                LIMIT 1
                """,
                (guild_id,),
            ).fetchone()

        if not row:
            return {
                "guild_id": guild_id,
                "enabled": 0,
                "channel_id": None,
                "mode": "normal",
                "reply_type": "mention",
                "character_name": self.DEFAULT_SERVER_CHARACTER,
                "permission_preset": "top3",
                "provider": "google",
                "model": self.CURRENT_GOOGLE_MODEL,
                "allow_management": 1,
                "allow_channel_management": 1,
                "allow_role_management": 1,
                "updated_at": self._now(),
            }

        config = dict(row)

        # Compatibility aliases.
        config["ai_enabled"] = config.get(
            "enabled",
            0,
        )

        config["ai_channel_id"] = config.get(
            "channel_id"
        )

        config["active_character"] = config.get(
            "character_name"
        )

        config["active_provider"] = config.get(
            "provider"
        )

        config["active_model"] = config.get(
            "model"
        )

        config["ai_mode"] = config.get(
            "mode"
        )

        return config

    def get_guild_config(
        self,
        guild_id,
    ) -> Dict[str, Any]:
        """
        Compatibility alias.
        """
        return self.get_ai_config(guild_id)

    def save_ai_config(
        self,
        guild_id,
        **kwargs,
    ) -> Dict[str, Any]:

        guild_id = self._safe_int(guild_id)

        if guild_id == self.DM_GUILD_ID:
            return self.get_ai_config(
                guild_id
            )

        self._ensure_server_character(guild_id)

        aliases = {
            "ai_enabled": "enabled",
            "ai_channel_id": "channel_id",
            "ai_mode": "mode",
            "active_character": "character_name",
            "active_provider": "provider",
            "active_model": "model",
        }

        normalized = {}

        for key, value in kwargs.items():
            normalized[
                aliases.get(key, key)
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

        normalized = {
            key: value
            for key, value in normalized.items()
            if key in allowed
        }

        if "enabled" in normalized:
            normalized["enabled"] = int(
                self._safe_bool(
                    normalized["enabled"]
                )
            )

        if "channel_id" in normalized:
            value = normalized["channel_id"]

            if value is not None:
                normalized["channel_id"] = self._safe_int(
                    value
                )

        for key in (
            "allow_management",
            "allow_channel_management",
            "allow_role_management",
        ):
            if key in normalized:
                normalized[key] = int(
                    self._safe_bool(
                        normalized[key]
                    )
                )

        if "mode" in normalized:
            normalized["mode"] = (
                str(normalized["mode"] or "normal")
                .strip()
                .lower()
            )

        if "reply_type" in normalized:
            normalized["reply_type"] = (
                str(
                    normalized["reply_type"]
                    or "mention"
                )
                .strip()
                .lower()
            )

        if "provider" in normalized:
            normalized["provider"] = (
                str(
                    normalized["provider"]
                    or "google"
                )
                .strip()
                .lower()
            )

        if "model" in normalized:
            normalized["model"] = (
                str(
                    normalized["model"]
                    or self.CURRENT_GOOGLE_MODEL
                ).strip()
            )

        if "character_name" in normalized:
            character_name = (
                str(
                    normalized["character_name"]
                    or self.DEFAULT_SERVER_CHARACTER
                ).strip()
            )

            if not self.get_character(
                guild_id,
                character_name,
            ):
                raise ValueError(
                    f"الشخصية **{character_name}** غير موجودة."
                )

            normalized["character_name"] = character_name

        now = self._now()

        with self._lock:

            self._ensure_ai_config_row_locked(
                guild_id
            )

            self._ensure_guild_settings_row_locked(
                guild_id
            )

            if normalized:

                assignments = []
                values = []

                for key, value in normalized.items():
                    assignments.append(
                        f"{key} = ?"
                    )
                    values.append(value)

                assignments.append(
                    "updated_at = ?"
                )
                values.append(now)

                values.append(guild_id)

                self.conn.execute(
                    f"""
                    UPDATE ai_config
                    SET {", ".join(assignments)}
                    WHERE guild_id = ?
                    """,
                    values,
                )

            # Keep guild_settings synchronized.
            mapping = {
                "character_name": "active_character",
                "provider": "active_provider",
                "model": "active_model",
                "enabled": "ai_enabled",
                "channel_id": "ai_channel_id",
                "mode": "ai_mode",
                "reply_type": "reply_type",
                "permission_preset": "permission_preset",
            }

            guild_updates = []
            guild_values = []

            for source, target in mapping.items():
                if source in normalized:
                    guild_updates.append(
                        f"{target} = ?"
                    )
                    guild_values.append(
                        normalized[source]
                    )

            guild_updates.append(
                "updated_at = ?"
            )
            guild_values.append(now)

            guild_values.append(guild_id)

            self.conn.execute(
                f"""
                UPDATE guild_settings
                SET {", ".join(guild_updates)}
                WHERE guild_id = ?
                """,
                guild_values,
            )

            self.conn.commit()

        return self.get_ai_config(
            guild_id
        )

    def update_guild_config(
        self,
        guild_id,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Compatibility alias for older main.py versions.
        """
        return self.save_ai_config(
            guild_id,
            **kwargs,
        )

    def get_guild_settings(
        self,
        guild_id,
    ) -> Dict[str, Any]:

        guild_id = self._safe_int(guild_id)

        if guild_id == self.DM_GUILD_ID:
            return {
                "guild_id": guild_id,
                "active_character": self.DM_CHARACTER_NAME,
                "active_provider": "google",
                "active_model": self.CURRENT_GOOGLE_MODEL,
                "ai_enabled": 1,
                "ai_channel_id": None,
                "ai_mode": "normal",
                "reply_type": "direct",
                "permission_preset": "top3",
                "updated_at": self._now(),
            }

        self._ensure_server_character(guild_id)

        with self._lock:

            self._ensure_guild_settings_row_locked(
                guild_id
            )

            self.conn.commit()

            row = self.conn.execute(
                """
                SELECT *
                FROM guild_settings
                WHERE guild_id = ?
                LIMIT 1
                """,
                (guild_id,),
            ).fetchone()

        if not row:
            return {}

        return dict(row)

    # ============================================================
    # MESSAGE MEMORY
    # ============================================================

    def add_message(
        self,
        guild_id,
        channel_id,
        user_id,
        character_name,
        role,
        content,
    ) -> bool:

        guild_id = self._safe_int(guild_id)

        channel_id = (
            self._safe_int(channel_id)
            if channel_id is not None
            else None
        )

        user_id = (
            self._safe_int(user_id)
            if user_id is not None
            else None
        )

        character_name = (
            str(character_name).strip()
            if character_name is not None
            else None
        )

        role = (
            str(role or "user")
            .strip()
            .lower()
        )

        content = str(content or "").strip()

        if not content:
            return False

        with self._lock:
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
                    self._now(),
                ),
            )

            self.conn.commit()

        return True

    def get_history(
        self,
        guild_id,
        channel_id=None,
        user_id=None,
        character_name=None,
        limit=20,
    ) -> List[Dict[str, Any]]:
        """
        Get conversation history.

        Supports the normal expected order:

            guild_id,
            channel_id,
            user_id,
            character_name,
            limit

        Also protects against older code passing:

            guild_id,
            channel_id,
            character_name,
            user_id,
            limit

        This prevents:
            ValueError:
            invalid literal for int():
            'مساعد السيرفر جيميناي'
        """

        guild_id = self._safe_int(guild_id)

        # --------------------------------------------------------
        # Detect old/wrong positional order automatically.
        # --------------------------------------------------------

        if (
            isinstance(user_id, str)
            and not user_id.isdigit()
            and (
                character_name is None
                or str(character_name).isdigit()
            )
        ):
            old_character_name = user_id
            old_user_id = character_name

            user_id = old_user_id
            character_name = old_character_name

        # Another possible order:
        # guild_id, channel_id, character_name, user_id, limit
        if (
            isinstance(user_id, str)
            and not user_id.isdigit()
            and isinstance(character_name, (int, float))
        ):
            old_character_name = user_id
            old_user_id = character_name

            user_id = old_user_id
            character_name = old_character_name

        channel_id_value = None

        if channel_id is not None:
            channel_id_value = self._safe_int(
                channel_id
            )

        user_id_value = None

        if user_id is not None:
            user_id_value = self._safe_int(
                user_id
            )

        character_name_value = None

        if character_name is not None:
            character_name_value = (
                str(character_name).strip()
            )

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 20

        limit = max(
            1,
            min(limit, 100),
        )

        conditions = [
            "guild_id = ?"
        ]

        values = [
            guild_id
        ]

        if channel_id_value is not None:
            conditions.append(
                "channel_id = ?"
            )
            values.append(
                channel_id_value
            )

        if user_id_value is not None:
            conditions.append(
                "user_id = ?"
            )
            values.append(
                user_id_value
            )

        if character_name_value:
            conditions.append(
                "character_name = ?"
            )
            values.append(
                character_name_value
            )

        values.append(limit)

        query = f"""
            SELECT
                id,
                guild_id,
                channel_id,
                user_id,
                character_name,
                role,
                content,
                created_at
            FROM messages
            WHERE {" AND ".join(conditions)}
            ORDER BY id DESC
            LIMIT ?
        """

        with self._lock:
            rows = self.conn.execute(
                query,
                values,
            ).fetchall()

        # AI prompts normally need oldest -> newest.
        rows = list(reversed(rows))

        return [
            dict(row)
            for row in rows
        ]

    def clear_history(
        self,
        guild_id,
        channel_id=None,
        user_id=None,
        character_name=None,
    ) -> int:

        guild_id = self._safe_int(guild_id)

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
                self._safe_int(channel_id)
            )

        if user_id is not None:
            conditions.append(
                "user_id = ?"
            )
            values.append(
                self._safe_int(user_id)
            )

        if character_name is not None:
            conditions.append(
                "character_name = ?"
            )
            values.append(
                str(character_name).strip()
            )

        with self._lock:

            cursor = self.conn.execute(
                f"""
                DELETE FROM messages
                WHERE {" AND ".join(conditions)}
                """,
                values,
            )

            deleted = cursor.rowcount

            self.conn.commit()

        return deleted

    def clear_memory(
        self,
        guild_id,
        *args,
        **kwargs,
    ) -> int:
        return self.clear_history(
            guild_id,
            *args,
            **kwargs,
        )

    # ============================================================
    # DM SETTINGS
    # ============================================================

    def get_dm_enabled(
        self,
        user_id,
    ) -> bool:

        user_id = self._safe_int(
            user_id
        )

        with self._lock:
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
            return True

        return bool(
            self._safe_int(
                row.get("enabled"),
                1,
            )
        )

    def set_dm_enabled(
        self,
        user_id,
        enabled,
    ) -> bool:

        user_id = self._safe_int(
            user_id
        )

        enabled_value = int(
            self._safe_bool(enabled)
        )

        now = self._now()

        with self._lock:

            existing = self.conn.execute(
                """
                SELECT user_id
                FROM ai_dm_settings
                WHERE user_id = ?
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()

            if existing:
                self.conn.execute(
                    """
                    UPDATE ai_dm_settings
                    SET enabled = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        enabled_value,
                        now,
                        user_id,
                    ),
                )
            else:
                self.conn.execute(
                    """
                    INSERT INTO ai_dm_settings (
                        user_id,
                        enabled,
                        updated_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        user_id,
                        enabled_value,
                        now,
                    ),
                )

            self.conn.commit()

        return bool(enabled_value)

    # ============================================================
    # UTILITY METHODS
    # ============================================================

    def character_exists(
        self,
        guild_id,
        name,
    ) -> bool:
        return (
            self.get_character(
                guild_id,
                name,
            )
            is not None
        )

    def get_character_owner(
        self,
        guild_id,
        name,
    ) -> Optional[int]:

        character = self.get_character(
            guild_id,
            name,
        )

        if not character:
            return None

        return self._safe_int(
            character.get("created_by"),
            0,
        )

    # ============================================================
    # CLOSE
    # ============================================================

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

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        self.close()
