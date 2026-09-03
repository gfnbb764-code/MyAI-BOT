import sqlite3
import threading
from datetime import datetime


# ==========================================================
# DATABASE
# ==========================================================

class Database:

    # ======================================================
    # DEFAULT CONFIG
    # ======================================================

    CURRENT_GOOGLE_MODEL = "gemini-3.5-flash-lite"

    DM_GUILD_ID = 0
    DM_CHARACTER_NAME = "مساعد MyAI"

    DEFAULT_CHARACTER_TYPE = "normal"

    # ======================================================
    # INITIALIZATION
    # ======================================================

    def __init__(self, db_path="myai.db"):

        self.db_path = db_path
        self.lock = threading.RLock()

        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False
        )

        self.conn.row_factory = sqlite3.Row

        # --------------------------------------------------
        # SQLite stability
        # --------------------------------------------------

        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
        except Exception as e:
            print(f"⚠️ SQLite WAL warning: {e}")

        try:
            self.conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass

        try:
            self.conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            pass

        # --------------------------------------------------
        # Tables / migrations
        # --------------------------------------------------

        self._create_tables()
        self._repair_characters_table()
        self._repair_messages_table()
        self._repair_settings_tables()
        self._create_dm_tables()
        self._ensure_dm_character()
        self._migrate_old_models()

    # ======================================================
    # BASIC SQL EXECUTOR
    # ======================================================

    def _execute(
        self,
        query,
        params=(),
        *,
        fetchone=False,
        fetchall=False,
        commit=False
    ):

        with self.lock:

            cursor = self.conn.cursor()

            try:

                cursor.execute(query, params)

                if commit:
                    self.conn.commit()

                if fetchone:
                    return cursor.fetchone()

                if fetchall:
                    return cursor.fetchall()

                return None

            finally:
                cursor.close()

    # ======================================================
    # TABLE CREATION
    # ======================================================

    def _create_tables(self):

        with self.lock:

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS characters (

                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    guild_id INTEGER NOT NULL,

                    name TEXT NOT NULL,

                    personality TEXT DEFAULT '',

                    character_type TEXT DEFAULT 'normal',

                    custom_instructions TEXT DEFAULT '',

                    speaking_style TEXT DEFAULT '',

                    provider TEXT DEFAULT 'google',

                    model TEXT DEFAULT '',

                    created_by INTEGER DEFAULT 0,

                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                    UNIQUE(guild_id, name)
                )
                """
            )

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

                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_settings (

                    guild_id INTEGER PRIMARY KEY,

                    active_character TEXT,

                    active_provider TEXT DEFAULT 'google',

                    active_model TEXT DEFAULT '',

                    ai_enabled INTEGER DEFAULT 0,

                    ai_channel_id INTEGER,

                    ai_mode TEXT DEFAULT 'normal',

                    reply_type TEXT DEFAULT 'mention',

                    permission_preset TEXT DEFAULT 'management',

                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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

                    character_name TEXT,

                    permission_preset TEXT DEFAULT 'management',

                    provider TEXT DEFAULT 'google',

                    model TEXT DEFAULT '',

                    allow_management INTEGER DEFAULT 1,

                    allow_channel_management INTEGER DEFAULT 0,

                    allow_role_management INTEGER DEFAULT 0,

                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_dm_settings (

                    user_id INTEGER PRIMARY KEY,

                    enabled INTEGER DEFAULT 0,

                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
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
                idx_messages_character
                ON messages(guild_id, character_name)
                """
            )

            self.conn.commit()

    # ======================================================
    # CHARACTER TABLE MIGRATION
    # ======================================================

    def _repair_characters_table(self):

        with self.lock:

            columns = {
                row["name"]
                for row in self.conn.execute(
                    "PRAGMA table_info(characters)"
                ).fetchall()
            }

            migrations = {

                "created_by": (
                    "ALTER TABLE characters "
                    "ADD COLUMN created_by INTEGER DEFAULT 0"
                ),

                "created_at": (
                    "ALTER TABLE characters "
                    "ADD COLUMN created_at "
                    "TEXT DEFAULT CURRENT_TIMESTAMP"
                ),

                "provider": (
                    "ALTER TABLE characters "
                    "ADD COLUMN provider "
                    "TEXT DEFAULT 'google'"
                ),

                "model": (
                    "ALTER TABLE characters "
                    "ADD COLUMN model TEXT DEFAULT ''"
                ),

                "character_type": (
                    "ALTER TABLE characters "
                    "ADD COLUMN character_type "
                    "TEXT DEFAULT 'normal'"
                ),

                "custom_instructions": (
                    "ALTER TABLE characters "
                    "ADD COLUMN custom_instructions "
                    "TEXT DEFAULT ''"
                ),

                "speaking_style": (
                    "ALTER TABLE characters "
                    "ADD COLUMN speaking_style "
                    "TEXT DEFAULT ''"
                ),
            }

            for column, query in migrations.items():

                if column in columns:
                    continue

                try:

                    self.conn.execute(query)

                    print(
                        f"🛠️ Added characters column: {column}"
                    )

                except Exception as e:

                    print(
                        f"⚠️ Character migration failed "
                        f"for {column}: {e}"
                    )

            # --------------------------------------------------
            # Normalize NULL values
            # --------------------------------------------------

            try:

                self.conn.execute(
                    """
                    UPDATE characters
                    SET character_type = 'normal'
                    WHERE character_type IS NULL
                       OR TRIM(character_type) = ''
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
                    SET personality = ''
                    WHERE personality IS NULL
                    """
                )

                self.conn.execute(
                    """
                    UPDATE characters
                    SET provider = 'google'
                    WHERE provider IS NULL
                       OR TRIM(provider) = ''
                    """
                )

                self.conn.execute(
                    """
                    UPDATE characters
                    SET model = ?
                    WHERE model IS NULL
                       OR TRIM(model) = ''
                    """,
                    (self.CURRENT_GOOGLE_MODEL,)
                )

                self.conn.execute(
                    """
                    UPDATE characters
                    SET created_by = 0
                    WHERE created_by IS NULL
                    """
                )

                self.conn.commit()

            except Exception as e:

                print(
                    f"⚠️ Character normalization warning: {e}"
                )

    # ======================================================
    # MESSAGE TABLE MIGRATION
    # ======================================================

    def _repair_messages_table(self):

        with self.lock:

            columns = {
                row["name"]
                for row in self.conn.execute(
                    "PRAGMA table_info(messages)"
                ).fetchall()
            }

            required = {
                "guild_id",
                "channel_id",
                "user_id",
                "character_name",
                "role",
                "content",
                "created_at",
            }

            if required.issubset(columns):
                return

            print("🛠️ Repairing messages table...")

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages_new (

                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    guild_id INTEGER NOT NULL,

                    channel_id INTEGER NOT NULL,

                    user_id INTEGER NOT NULL,

                    character_name TEXT,

                    role TEXT NOT NULL,

                    content TEXT NOT NULL,

                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            selectable = []

            for column in [
                "guild_id",
                "channel_id",
                "user_id",
                "character_name",
                "role",
                "content",
                "created_at",
            ]:

                if column in columns:

                    selectable.append(column)

                elif column == "guild_id":

                    selectable.append("0 AS guild_id")

                elif column == "channel_id":

                    selectable.append("0 AS channel_id")

                elif column == "user_id":

                    selectable.append("0 AS user_id")

                elif column == "character_name":

                    selectable.append("NULL AS character_name")

                elif column == "role":

                    selectable.append("'user' AS role")

                elif column == "content":

                    selectable.append("'' AS content")

                elif column == "created_at":

                    selectable.append(
                        "CURRENT_TIMESTAMP AS created_at"
                    )

            self.conn.execute(
                """
                INSERT INTO messages_new (
                    guild_id,
                    channel_id,
                    user_id,
                    character_name,
                    role,
                    content,
                    created_at
                )
                SELECT
                    {fields}
                FROM messages
                """.format(
                    fields=", ".join(selectable)
                )
            )

            self.conn.execute("DROP TABLE messages")

            self.conn.execute(
                "ALTER TABLE messages_new RENAME TO messages"
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
                idx_messages_character
                ON messages(guild_id, character_name)
                """
            )

            self.conn.commit()

    # ======================================================
    # SETTINGS TABLE MIGRATION
    # ======================================================

    def _repair_settings_tables(self):

        with self.lock:

            # --------------------------------------------------
            # guild_settings
            # --------------------------------------------------

            guild_columns = {
                row["name"]
                for row in self.conn.execute(
                    "PRAGMA table_info(guild_settings)"
                ).fetchall()
            }

            guild_migrations = {

                "active_character": (
                    "ALTER TABLE guild_settings "
                    "ADD COLUMN active_character TEXT"
                ),

                "active_provider": (
                    "ALTER TABLE guild_settings "
                    "ADD COLUMN active_provider "
                    "TEXT DEFAULT 'google'"
                ),

                "active_model": (
                    "ALTER TABLE guild_settings "
                    "ADD COLUMN active_model "
                    "TEXT DEFAULT ''"
                ),

                "ai_enabled": (
                    "ALTER TABLE guild_settings "
                    "ADD COLUMN ai_enabled INTEGER DEFAULT 0"
                ),

                "ai_channel_id": (
                    "ALTER TABLE guild_settings "
                    "ADD COLUMN ai_channel_id INTEGER"
                ),

                "ai_mode": (
                    "ALTER TABLE guild_settings "
                    "ADD COLUMN ai_mode "
                    "TEXT DEFAULT 'normal'"
                ),

                "reply_type": (
                    "ALTER TABLE guild_settings "
                    "ADD COLUMN reply_type "
                    "TEXT DEFAULT 'mention'"
                ),

                "permission_preset": (
                    "ALTER TABLE guild_settings "
                    "ADD COLUMN permission_preset "
                    "TEXT DEFAULT 'management'"
                ),

                "created_at": (
                    "ALTER TABLE guild_settings "
                    "ADD COLUMN created_at "
                    "TEXT DEFAULT CURRENT_TIMESTAMP"
                ),

                "updated_at": (
                    "ALTER TABLE guild_settings "
                    "ADD COLUMN updated_at "
                    "TEXT DEFAULT CURRENT_TIMESTAMP"
                ),
            }

            for column, query in guild_migrations.items():

                if column in guild_columns:
                    continue

                try:
                    self.conn.execute(query)

                except Exception as e:

                    print(
                        f"⚠️ guild_settings migration "
                        f"{column}: {e}"
                    )

            # --------------------------------------------------
            # ai_config
            # --------------------------------------------------

            ai_columns = {
                row["name"]
                for row in self.conn.execute(
                    "PRAGMA table_info(ai_config)"
                ).fetchall()
            }

            ai_migrations = {

                "enabled": (
                    "ALTER TABLE ai_config "
                    "ADD COLUMN enabled INTEGER DEFAULT 0"
                ),

                "channel_id": (
                    "ALTER TABLE ai_config "
                    "ADD COLUMN channel_id INTEGER"
                ),

                "mode": (
                    "ALTER TABLE ai_config "
                    "ADD COLUMN mode "
                    "TEXT DEFAULT 'normal'"
                ),

                "reply_type": (
                    "ALTER TABLE ai_config "
                    "ADD COLUMN reply_type "
                    "TEXT DEFAULT 'mention'"
                ),

                "character_name": (
                    "ALTER TABLE ai_config "
                    "ADD COLUMN character_name TEXT"
                ),

                "permission_preset": (
                    "ALTER TABLE ai_config "
                    "ADD COLUMN permission_preset "
                    "TEXT DEFAULT 'management'"
                ),

                "provider": (
                    "ALTER TABLE ai_config "
                    "ADD COLUMN provider "
                    "TEXT DEFAULT 'google'"
                ),

                "model": (
                    "ALTER TABLE ai_config "
                    "ADD COLUMN model TEXT DEFAULT ''"
                ),

                "allow_management": (
                    "ALTER TABLE ai_config "
                    "ADD COLUMN allow_management "
                    "INTEGER DEFAULT 1"
                ),

                "allow_channel_management": (
                    "ALTER TABLE ai_config "
                    "ADD COLUMN allow_channel_management "
                    "INTEGER DEFAULT 0"
                ),

                "allow_role_management": (
                    "ALTER TABLE ai_config "
                    "ADD COLUMN allow_role_management "
                    "INTEGER DEFAULT 0"
                ),

                "updated_at": (
                    "ALTER TABLE ai_config "
                    "ADD COLUMN updated_at "
                    "TEXT DEFAULT CURRENT_TIMESTAMP"
                ),
            }

            for column, query in ai_migrations.items():

                if column in ai_columns:
                    continue

                try:
                    self.conn.execute(query)

                except Exception as e:

                    print(
                        f"⚠️ ai_config migration "
                        f"{column}: {e}"
                    )

            self.conn.commit()

    # ======================================================
    # DM TABLES
    # ======================================================

    def _create_dm_tables(self):

        with self.lock:

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_dm_settings (

                    user_id INTEGER PRIMARY KEY,

                    enabled INTEGER DEFAULT 0,

                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            self.conn.commit()

    # ======================================================
    # DEFAULT DM CHARACTER
    # ======================================================

    def _ensure_dm_character(self):

        existing = self.get_character(
            self.DM_GUILD_ID,
            self.DM_CHARACTER_NAME
        )

        if existing:
            return

        try:

            self.create_character(

                guild_id=self.DM_GUILD_ID,

                name=self.DM_CHARACTER_NAME,

                personality=(
                    "مساعد ودود ومفيد ومحترم. "
                    "يجيب بوضوح وطبيعية، "
                    "ولا يدعي تنفيذ أفعال لم ينفذها."
                ),

                character_type="friendly",

                custom_instructions=(
                    "ساعد المستخدم بشكل واضح، "
                    "ولا تدعي الوصول إلى أشياء "
                    "لم يتم الوصول إليها فعليًا."
                ),

                speaking_style=(
                    "ودود، واضح، مختصر عند الحاجة."
                ),

                provider="google",

                model=self.CURRENT_GOOGLE_MODEL,

                created_by=0
            )

        except Exception as e:

            print(
                f"⚠️ DM character creation warning: {e}"
            )

    # ======================================================
    # MODEL MIGRATION
    # ======================================================

    def _migrate_old_models(self):

        old_models = (
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-3.6-flash",
        )

        placeholders = ",".join(
            "?" for _ in old_models
        )

        with self.lock:

            try:

                self.conn.execute(
                    f"""
                    UPDATE characters
                    SET model = ?
                    WHERE model IN ({placeholders})
                    """,
                    (
                        self.CURRENT_GOOGLE_MODEL,
                        *old_models
                    )
                )

                self.conn.execute(
                    f"""
                    UPDATE guild_settings
                    SET active_model = ?
                    WHERE active_model IN ({placeholders})
                    """,
                    (
                        self.CURRENT_GOOGLE_MODEL,
                        *old_models
                    )
                )

                self.conn.execute(
                    f"""
                    UPDATE ai_config
                    SET model = ?
                    WHERE model IN ({placeholders})
                    """,
                    (
                        self.CURRENT_GOOGLE_MODEL,
                        *old_models
                    )
                )

                self.conn.commit()

            except Exception as e:

                print(
                    f"⚠️ Model migration warning: {e}"
                )

    # ======================================================
    # CHARACTER VALIDATION
    # ======================================================

    @staticmethod
    def _validate_character_name(name):

        name = str(name or "").strip()

        if not name:

            raise ValueError(
                "اسم الشخصية لا يمكن أن يكون فارغًا."
            )

        if len(name) > 50:

            raise ValueError(
                "اسم الشخصية يجب ألا يتجاوز 50 حرفًا."
            )

        return name

    @staticmethod
    def _validate_text(
        value,
        field_name,
        max_length
    ):

        value = str(value or "").strip()

        if len(value) > max_length:

            raise ValueError(
                f"{field_name} يجب ألا يتجاوز "
                f"{max_length} حرف."
            )

        return value

    # ======================================================
    # CHARACTER CREATE
    # ======================================================

    def create_character(
        self,
        guild_id,
        name,
        personality="",
        provider="google",
        model=None,
        created_by=0,
        character_type="normal",
        custom_instructions="",
        speaking_style=""
    ):

        name = self._validate_character_name(name)

        personality = self._validate_text(
            personality,
            "وصف الشخصية",
            2000
        )

        character_type = self._validate_text(
            character_type,
            "نوع الشخصية",
            50
        )

        custom_instructions = self._validate_text(
            custom_instructions,
            "التعليمات المخصصة",
            2000
        )

        speaking_style = self._validate_text(
            speaking_style,
            "أسلوب الكلام",
            1000
        )

        provider = str(
            provider or "google"
        ).strip().lower()

        model = str(
            model
            or (
                self.CURRENT_GOOGLE_MODEL
                if provider == "google"
                else ""
            )
        ).strip()

        try:
            created_by = int(created_by or 0)

        except Exception:
            created_by = 0

        with self.lock:

            try:

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
                        created_by,
                        datetime.utcnow().isoformat()
                    )
                )

                self.conn.commit()

                character_id = cursor.lastrowid

            except sqlite3.IntegrityError:

                raise ValueError(
                    f"الشخصية **{name}** موجودة بالفعل."
                )

            return self.conn.execute(
                """
                SELECT *
                FROM characters
                WHERE id = ?
                """,
                (character_id,)
            ).fetchone()

    # ======================================================
    # GET CHARACTER
    # ======================================================

    def get_character(
        self,
        guild_id,
        name
    ):

        if not name:
            return None

        return self._execute(
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
            ),
            fetchone=True
        )

    # ======================================================
    # GET CHARACTER BY ID
    # ======================================================

    def get_character_by_id(
        self,
        guild_id,
        character_id
    ):

        return self._execute(
            """
            SELECT *
            FROM characters
            WHERE guild_id = ?
              AND id = ?
            LIMIT 1
            """,
            (
                int(guild_id),
                int(character_id)
            ),
            fetchone=True
        )

    # ======================================================
    # GET CHARACTERS
    # ======================================================

    def get_characters(self, guild_id):

        return self._execute(
            """
            SELECT *
            FROM characters
            WHERE guild_id = ?
            ORDER BY id ASC
            """,
            (int(guild_id),),
            fetchall=True
        )

    # ======================================================
    # LIST CHARACTERS
    # ======================================================

    def list_characters(self, guild_id):

        return self.get_characters(guild_id)

    # ======================================================
    # UPDATE CHARACTER
    # OWNER ONLY
    # ======================================================

    def update_character(
        self,
        guild_id,
        name,
        personality=None,
        provider=None,
        model=None,
        character_type=None,
        custom_instructions=None,
        speaking_style=None,
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

        if int(guild_id) == self.DM_GUILD_ID:

            raise PermissionError(
                "لا يمكن تعديل شخصية النظام."
            )

        owner_id = int(
            character["created_by"] or 0
        )

        try:
            editor_id = int(editor_id or 0)

        except Exception:
            editor_id = 0

        if owner_id != editor_id:

            raise PermissionError(
                "لا يمكنك تعديل شخصية شخص آخر."
            )

        fields = []
        values = []

        if personality is not None:

            personality = self._validate_text(
                personality,
                "وصف الشخصية",
                2000
            )

            fields.append("personality = ?")
            values.append(personality)

        if provider is not None:

            fields.append("provider = ?")
            values.append(
                str(provider).strip().lower()
            )

        if model is not None:

            fields.append("model = ?")
            values.append(
                str(model).strip()
            )

        if character_type is not None:

            character_type = self._validate_text(
                character_type,
                "نوع الشخصية",
                50
            )

            fields.append("character_type = ?")
            values.append(character_type)

        if custom_instructions is not None:

            custom_instructions = self._validate_text(
                custom_instructions,
                "التعليمات المخصصة",
                2000
            )

            fields.append(
                "custom_instructions = ?"
            )

            values.append(
                custom_instructions
            )

        if speaking_style is not None:

            speaking_style = self._validate_text(
                speaking_style,
                "أسلوب الكلام",
                1000
            )

            fields.append(
                "speaking_style = ?"
            )

            values.append(
                speaking_style
            )

        if not fields:

            raise ValueError(
                "لم يتم إرسال أي تعديل."
            )

        values.extend(
            [
                int(guild_id),
                str(name).strip()
            ]
        )

        with self.lock:

            self.conn.execute(
                f"""
                UPDATE characters
                SET {", ".join(fields)}
                WHERE guild_id = ?
                  AND name = ?
                """,
                tuple(values)
            )

            self.conn.commit()

        return self.get_character(
            guild_id,
            name
        )

    # ======================================================
    # DELETE CHARACTER
    # OWNER ONLY
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

        if int(guild_id) == self.DM_GUILD_ID:

            raise PermissionError(
                "لا يمكن حذف شخصية النظام."
            )

        owner_id = int(
            character["created_by"] or 0
        )

        try:
            requester_id = int(
                requester_id or 0
            )

        except Exception:
            requester_id = 0

        if owner_id != requester_id:

            raise PermissionError(
                "لا يمكنك حذف شخصية شخص آخر."
            )

        with self.lock:

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

            self.conn.execute(
                """
                UPDATE guild_settings
                SET active_character = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
                  AND active_character = ?
                """,
                (
                    int(guild_id),
                    str(name).strip()
                )
            )

            self.conn.execute(
                """
                UPDATE ai_config
                SET character_name = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
                  AND character_name = ?
                """,
                (
                    int(guild_id),
                    str(name).strip()
                )
            )

            self.conn.commit()

        return True

    # ======================================================
    # AI CONFIG
    # ======================================================

    def get_ai_config(self, guild_id):

        row = self._execute(
            """
            SELECT *
            FROM ai_config
            WHERE guild_id = ?
            LIMIT 1
            """,
            (int(guild_id),),
            fetchone=True
        )

        if row:
            return row

        with self.lock:

            self.conn.execute(
                """
                INSERT OR IGNORE INTO ai_config (
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
                    allow_role_management
                )
                VALUES (
                    ?,
                    0,
                    NULL,
                    'normal',
                    'mention',
                    NULL,
                    'management',
                    'google',
                    ?,
                    1,
                    0,
                    0
                )
                """,
                (
                    int(guild_id),
                    self.CURRENT_GOOGLE_MODEL
                )
            )

            self.conn.commit()

        return self._execute(
            """
            SELECT *
            FROM ai_config
            WHERE guild_id = ?
            LIMIT 1
            """,
            (int(guild_id),),
            fetchone=True
        )

    # ======================================================
    # GUILD CONFIG ALIAS
    # ======================================================

    def get_guild_config(self, guild_id):

        return self.get_ai_config(guild_id)

    # ======================================================
    # SAVE AI CONFIG
    # ======================================================

    def save_ai_config(
        self,
        guild_id,
        **kwargs
    ):

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

        updates = []
        values = []

        for key, value in kwargs.items():

            if key not in allowed:
                continue

            if key == "enabled":

                value = 1 if value else 0

            updates.append(
                f"{key} = ?"
            )

            values.append(value)

        if not updates:

            return self.get_ai_config(guild_id)

        updates.append(
            "updated_at = CURRENT_TIMESTAMP"
        )

        values.append(int(guild_id))

        with self.lock:

            self.conn.execute(
                """
                INSERT OR IGNORE INTO ai_config (
                    guild_id,
                    enabled,
                    provider,
                    model
                )
                VALUES (?, 0, 'google', ?)
                """,
                (
                    int(guild_id),
                    self.CURRENT_GOOGLE_MODEL
                )
            )

            self.conn.execute(
                f"""
                UPDATE ai_config
                SET {", ".join(updates)}
                WHERE guild_id = ?
                """,
                tuple(values)
            )

            self.conn.commit()

        return self.get_ai_config(guild_id)

    # ======================================================
    # GUILD SETTINGS
    # ======================================================

    def update_guild_config(
        self,
        guild_id,
        **kwargs
    ):

        mapping = {

            "character_name":
                "active_character",

            "provider":
                "active_provider",

            "model":
                "active_model",

            "enabled":
                "ai_enabled",

            "channel_id":
                "ai_channel_id",

            "mode":
                "ai_mode",

            "reply_type":
                "reply_type",

            "permission_preset":
                "permission_preset",
        }

        updates = []
        values = []

        for key, value in kwargs.items():

            column = mapping.get(key)

            if not column:
                continue

            if key == "enabled":

                value = 1 if value else 0

            updates.append(
                f"{column} = ?"
            )

            values.append(value)

        if not updates:

            return self.get_guild_config(guild_id)

        updates.append(
            "updated_at = CURRENT_TIMESTAMP"
        )

        values.append(int(guild_id))

        with self.lock:

            self.conn.execute(
                """
                INSERT OR IGNORE INTO guild_settings (
                    guild_id
                )
                VALUES (?)
                """,
                (int(guild_id),)
            )

            self.conn.execute(
                f"""
                UPDATE guild_settings
                SET {", ".join(updates)}
                WHERE guild_id = ?
                """,
                tuple(values)
            )

            self.conn.commit()

        return self.get_guild_settings(guild_id)

    # ======================================================
    # GUILD SETTINGS GET
    # ======================================================

    def get_guild_settings(self, guild_id):

        row = self._execute(
            """
            SELECT *
            FROM guild_settings
            WHERE guild_id = ?
            LIMIT 1
            """,
            (int(guild_id),),
            fetchone=True
        )

        if row:
            return row

        with self.lock:

            self.conn.execute(
                """
                INSERT OR IGNORE INTO guild_settings (
                    guild_id,
                    active_provider,
                    active_model
                )
                VALUES (?, 'google', ?)
                """,
                (
                    int(guild_id),
                    self.CURRENT_GOOGLE_MODEL
                )
            )

            self.conn.commit()

        return self._execute(
            """
            SELECT *
            FROM guild_settings
            WHERE guild_id = ?
            LIMIT 1
            """,
            (int(guild_id),),
            fetchone=True
        )

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

        with self.lock:

            self.conn.execute(
                """
                INSERT OR IGNORE INTO ai_config (
                    guild_id,
                    enabled,
                    mode,
                    reply_type,
                    provider,
                    model
                )
                VALUES (
                    ?,
                    0,
                    'normal',
                    'mention',
                    'google',
                    ?
                )
                """,
                (
                    int(guild_id),
                    self.CURRENT_GOOGLE_MODEL
                )
            )

            self.conn.execute(
                """
                UPDATE ai_config
                SET character_name = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
                """,
                (
                    character_name,
                    int(guild_id)
                )
            )

            self.conn.execute(
                """
                INSERT OR IGNORE INTO guild_settings (
                    guild_id,
                    active_provider,
                    active_model
                )
                VALUES (?, 'google', ?)
                """,
                (
                    int(guild_id),
                    self.CURRENT_GOOGLE_MODEL
                )
            )

            self.conn.execute(
                """
                UPDATE guild_settings
                SET active_character = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
                """,
                (
                    character_name,
                    int(guild_id)
                )
            )

            self.conn.commit()

        return {
            "character_name": character_name
        }

    # ======================================================
    # GET ACTIVE CHARACTER
    # ======================================================

    def get_active_character(self, guild_id):

        config = self.get_ai_config(guild_id)

        if not config:
            return None

        character_name = config["character_name"]

        if not character_name:
            return None

        return self.get_character(
            guild_id,
            character_name
        )

    # ======================================================
    # MESSAGE HISTORY
    # ======================================================

    def add_message(
        self,
        guild_id,
        channel_id,
        user_id,
        character_name,
        role,
        content
    ):

        content = str(content or "").strip()

        if not content:
            return None

        with self.lock:

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
                    role,
                    content,
                    datetime.utcnow().isoformat()
                )
            )

            self.conn.commit()

            return cursor.lastrowid

    def get_history(
        self,
        guild_id,
        channel_id,
        character_name,
        limit=20
    ):

        try:

            limit = max(
                1,
                min(int(limit), 100)
            )

        except Exception:

            limit = 20

        rows = self._execute(
            """
            SELECT *
            FROM messages
            WHERE guild_id = ?
              AND channel_id = ?
              AND character_name = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                int(guild_id),
                int(channel_id),
                character_name,
                limit
            ),
            fetchall=True
        )

        return list(reversed(rows or []))

    # ======================================================
    # CLEAR HISTORY
    # ======================================================

    def clear_history(
        self,
        guild_id,
        channel_id=None,
        character_name=None
    ):

        conditions = ["guild_id = ?"]
        values = [int(guild_id)]

        if channel_id is not None:

            conditions.append(
                "channel_id = ?"
            )

            values.append(
                int(channel_id)
            )

        if character_name is not None:

            conditions.append(
                "character_name = ?"
            )

            values.append(
                str(character_name)
            )

        query = f"""
            DELETE FROM messages
            WHERE {" AND ".join(conditions)}
        """

        with self.lock:

            cursor = self.conn.execute(
                query,
                tuple(values)
            )

            self.conn.commit()

            return cursor.rowcount

    # ======================================================
    # AI MEMORY CLEAR ALIAS
    # ======================================================

    def clear_memory(
        self,
        guild_id,
        channel_id=None,
        character_name=None
    ):

        return self.clear_history(
            guild_id,
            channel_id,
            character_name
        )

    # ======================================================
    # DM AI
    # ======================================================

    def get_dm_enabled(self, user_id):

        row = self._execute(
            """
            SELECT enabled
            FROM ai_dm_settings
            WHERE user_id = ?
            LIMIT 1
            """,
            (int(user_id),),
            fetchone=True
        )

        if not row:
            return False

        return bool(row["enabled"])

    def set_dm_enabled(
        self,
        user_id,
        enabled
    ):

        with self.lock:

            self.conn.execute(
                """
                INSERT INTO ai_dm_settings (
                    user_id,
                    enabled,
                    updated_at
                )
                VALUES (?, ?, CURRENT_TIMESTAMP)

                ON CONFLICT(user_id)
                DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    int(user_id),
                    1 if enabled else 0
                )
            )

            self.conn.commit()

        return bool(enabled)

    # ======================================================
    # CLOSE
    # ======================================================

    def close(self):

        with self.lock:

            try:
                self.conn.commit()
            except Exception:
                pass

            try:
                self.conn.close()
            except Exception:
                pass
