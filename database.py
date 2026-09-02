import sqlite3
import threading


class Database:

    CURRENT_GOOGLE_MODEL = "gemini-3.6-flash"

    def __init__(self, db_path="myai.db"):
        self.db_path = db_path
        self.lock = threading.RLock()

        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False
        )

        self.conn.row_factory = sqlite3.Row

        self._create_tables()
        self._migrate_old_models()

    # ==========================================================
    # DATABASE CORE
    # ==========================================================

    def _execute(
        self,
        query,
        params=(),
        fetchone=False,
        fetchall=False,
        commit=False
    ):
        with self.lock:

            cursor = self.conn.cursor()

            try:

                cursor.execute(
                    query,
                    params
                )

                if commit:
                    self.conn.commit()

                if fetchone:
                    return cursor.fetchone()

                if fetchall:
                    return cursor.fetchall()

                return cursor

            except Exception:

                if commit:
                    self.conn.rollback()

                raise

    # ==========================================================
    # TABLES
    # ==========================================================

    def _create_tables(self):

        with self.lock:

            cursor = self.conn.cursor()

            # --------------------------------------------------
            # CHARACTERS
            # --------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS characters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    personality TEXT NOT NULL,
                    provider TEXT DEFAULT 'google',
                    model TEXT DEFAULT 'gemini-3.6-flash',
                    created_by INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(guild_id, name)
                )
            """)

            # --------------------------------------------------
            # MESSAGE HISTORY
            # --------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    character_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # --------------------------------------------------
            # SERVER SETTINGS
            # --------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    active_character TEXT,
                    active_provider TEXT DEFAULT 'google',
                    active_model TEXT DEFAULT 'gemini-3.6-flash',
                    ai_enabled INTEGER DEFAULT 0,
                    ai_channel_id INTEGER,
                    ai_mode TEXT DEFAULT 'normal',
                    reply_type TEXT DEFAULT 'mention',
                    permission_preset TEXT DEFAULT 'chat',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # --------------------------------------------------
            # AI CONFIG
            # --------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ai_config (
                    guild_id INTEGER PRIMARY KEY,
                    enabled INTEGER DEFAULT 0,
                    channel_id INTEGER,
                    mode TEXT DEFAULT 'normal',
                    reply_type TEXT DEFAULT 'mention',
                    character_name TEXT,
                    permission_preset TEXT DEFAULT 'chat',
                    provider TEXT DEFAULT 'google',
                    model TEXT DEFAULT 'gemini-3.6-flash',
                    allow_management INTEGER DEFAULT 0,
                    allow_channel_management INTEGER DEFAULT 0,
                    allow_role_management INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # --------------------------------------------------
            # INDEXES
            # --------------------------------------------------

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_messages_guild_channel
                ON messages(guild_id, channel_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_messages_character
                ON messages(guild_id, character_name)
            """)

            self.conn.commit()

    # ==========================================================
    # OLD MODEL MIGRATION
    # ==========================================================

    def _migrate_old_models(self):

        with self.lock:

            cursor = self.conn.cursor()

            # الشخصيات
            cursor.execute("""
                UPDATE characters
                SET model = ?
                WHERE provider = 'google'
                AND model = 'gemini-2.5-flash'
            """, (
                self.CURRENT_GOOGLE_MODEL,
            ))

            # إعدادات السيرفر
            cursor.execute("""
                UPDATE guild_settings
                SET active_model = ?
                WHERE active_provider = 'google'
                AND active_model = 'gemini-2.5-flash'
            """, (
                self.CURRENT_GOOGLE_MODEL,
            ))

            # إعدادات AI
            cursor.execute("""
                UPDATE ai_config
                SET model = ?
                WHERE provider = 'google'
                AND model = 'gemini-2.5-flash'
            """, (
                self.CURRENT_GOOGLE_MODEL,
            ))

            self.conn.commit()

    # ==========================================================
    # ENSURE GUILD
    # ==========================================================

    def ensure_guild(self, guild_id):

        row = self._execute(
            """
            SELECT guild_id
            FROM guild_settings
            WHERE guild_id = ?
            """,
            (guild_id,),
            fetchone=True
        )

        if row:
            return

        self._execute(
            """
            INSERT INTO guild_settings (
                guild_id,
                active_provider,
                active_model
            )
            VALUES (?, 'google', ?)
            """,
            (
                guild_id,
                self.CURRENT_GOOGLE_MODEL
            ),
            commit=True
        )

    # ==========================================================
    # CHARACTERS
    # ==========================================================

    def create_character(
        self,
        guild_id,
        name,
        personality,
        provider="google",
        model=None,
        created_by=0
    ):

        name = str(name).strip()
        personality = str(personality).strip()

        provider = (
            provider or "google"
        ).lower()

        if provider == "google":

            model = (
                model
                or self.CURRENT_GOOGLE_MODEL
            )

            if model == "gemini-2.5-flash":
                model = self.CURRENT_GOOGLE_MODEL

        else:

            model = model or ""

        if not name:
            raise ValueError(
                "اسم الشخصية لا يمكن أن يكون فارغًا."
            )

        if len(name) > 50:
            raise ValueError(
                "اسم الشخصية طويل جدًا."
            )

        if not personality:
            personality = "شخصية ودودة ومفيدة."

        if len(personality) > 2000:
            raise ValueError(
                "وصف الشخصية طويل جدًا."
            )

        try:

            self._execute(
                """
                INSERT INTO characters (
                    guild_id,
                    name,
                    personality,
                    provider,
                    model,
                    created_by
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    name,
                    personality,
                    provider,
                    model,
                    created_by
                ),
                commit=True
            )

        except sqlite3.IntegrityError:

            raise ValueError(
                f"الشخصية `{name}` موجودة بالفعل."
            )

        return self.get_character(
            guild_id,
            name
        )

    def get_character(
        self,
        guild_id,
        name
    ):

        row = self._execute(
            """
            SELECT *
            FROM characters
            WHERE guild_id = ?
            AND name = ?
            """,
            (
                guild_id,
                name
            ),
            fetchone=True
        )

        return row

    def get_characters(
        self,
        guild_id
    ):

        return self._execute(
            """
            SELECT *
            FROM characters
            WHERE guild_id = ?
            ORDER BY created_at ASC
            """,
            (guild_id,),
            fetchall=True
        )

    def update_character(
        self,
        guild_id,
        name,
        personality=None,
        provider=None,
        model=None
    ):

        character = self.get_character(
            guild_id,
            name
        )

        if not character:
            raise ValueError(
                "الشخصية غير موجودة."
            )

        current = dict(character)

        new_personality = (
            personality
            if personality is not None
            else current["personality"]
        )

        new_provider = (
            provider
            if provider is not None
            else current["provider"]
        )

        new_model = (
            model
            if model is not None
            else current["model"]
        )

        if new_provider == "google":

            if (
                not new_model
                or new_model == "gemini-2.5-flash"
            ):
                new_model = self.CURRENT_GOOGLE_MODEL

        self._execute(
            """
            UPDATE characters
            SET personality = ?,
                provider = ?,
                model = ?
            WHERE guild_id = ?
            AND name = ?
            """,
            (
                new_personality,
                new_provider,
                new_model,
                guild_id,
                name
            ),
            commit=True
        )

        return self.get_character(
            guild_id,
            name
        )

    def delete_character(
        self,
        guild_id,
        name
    ):

        self._execute(
            """
            DELETE FROM characters
            WHERE guild_id = ?
            AND name = ?
            """,
            (
                guild_id,
                name
            ),
            commit=True
        )

        self._execute(
            """
            UPDATE guild_settings
            SET active_character = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE guild_id = ?
            AND active_character = ?
            """,
            (
                guild_id,
                name
            ),
            commit=True
        )

        self._execute(
            """
            UPDATE ai_config
            SET character_name = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE guild_id = ?
            AND character_name = ?
            """,
            (
                guild_id,
                name
            ),
            commit=True
        )

    # ==========================================================
    # AI CONFIG
    # ==========================================================

    def get_ai_config(
        self,
        guild_id
    ):

        row = self._execute(
            """
            SELECT *
            FROM ai_config
            WHERE guild_id = ?
            """,
            (guild_id,),
            fetchone=True
        )

        if not row:

            self._execute(
                """
                INSERT INTO ai_config (
                    guild_id,
                    provider,
                    model
                )
                VALUES (?, 'google', ?)
                """,
                (
                    guild_id,
                    self.CURRENT_GOOGLE_MODEL
                ),
                commit=True
            )

            row = self._execute(
                """
                SELECT *
                FROM ai_config
                WHERE guild_id = ?
                """,
                (guild_id,),
                fetchone=True
            )

        data = dict(row)

        # حماية إضافية من الموديل القديم
        if (
            data["provider"] == "google"
            and data["model"] == "gemini-2.5-flash"
        ):

            self._execute(
                """
                UPDATE ai_config
                SET model = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
                """,
                (
                    self.CURRENT_GOOGLE_MODEL,
                    guild_id
                ),
                commit=True
            )

            data["model"] = self.CURRENT_GOOGLE_MODEL

        return data

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

        current = self.get_ai_config(
            guild_id
        )

        def value(new, old):
            return old if new is None else new

        enabled = value(
            enabled,
            current["enabled"]
        )

        channel_id = value(
            channel_id,
            current["channel_id"]
        )

        mode = value(
            mode,
            current["mode"]
        )

        reply_type = value(
            reply_type,
            current["reply_type"]
        )

        character_name = value(
            character_name,
            current["character_name"]
        )

        permission_preset = value(
            permission_preset,
            current["permission_preset"]
        )

        provider = value(
            provider,
            current["provider"]
        )

        model = value(
            model,
            current["model"]
        )

        allow_management = value(
            allow_management,
            current["allow_management"]
        )

        allow_channel_management = value(
            allow_channel_management,
            current["allow_channel_management"]
        )

        allow_role_management = value(
            allow_role_management,
            current["allow_role_management"]
        )

        provider = (
            provider or "google"
        ).lower()

        if provider == "google":

            if (
                not model
                or model == "gemini-2.5-flash"
            ):
                model = self.CURRENT_GOOGLE_MODEL

        self._execute(
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
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                CURRENT_TIMESTAMP
            )
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
                allow_channel_management =
                    excluded.allow_channel_management,
                allow_role_management =
                    excluded.allow_role_management,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                guild_id,
                int(bool(enabled)),
                channel_id,
                mode,
                reply_type,
                character_name,
                permission_preset,
                provider,
                model,
                int(bool(allow_management)),
                int(bool(allow_channel_management)),
                int(bool(allow_role_management))
            ),
            commit=True
        )

        self.ensure_guild(
            guild_id
        )

        self._execute(
            """
            UPDATE guild_settings
            SET active_character = ?,
                active_provider = ?,
                active_model = ?,
                ai_enabled = ?,
                ai_channel_id = ?,
                ai_mode = ?,
                reply_type = ?,
                permission_preset = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE guild_id = ?
            """,
            (
                character_name,
                provider,
                model,
                int(bool(enabled)),
                channel_id,
                mode,
                reply_type,
                permission_preset,
                guild_id
            ),
            commit=True
        )

        return self.get_ai_config(
            guild_id
        )

    # ==========================================================
    # QUICK SETTINGS
    # ==========================================================

    def set_ai_enabled(
        self,
        guild_id,
        enabled
    ):
        return self.save_ai_config(
            guild_id,
            enabled=enabled
        )

    def set_ai_channel(
        self,
        guild_id,
        channel_id
    ):
        return self.save_ai_config(
            guild_id,
            channel_id=channel_id
        )

    def set_ai_mode(
        self,
        guild_id,
        mode
    ):
        return self.save_ai_config(
            guild_id,
            mode=mode
        )

    def set_reply_type(
        self,
        guild_id,
        reply_type
    ):
        return self.save_ai_config(
            guild_id,
            reply_type=reply_type
        )

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
                "الشخصية غير موجودة."
            )

        return self.save_ai_config(
            guild_id,
            character_name=character_name
        )

    # ==========================================================
    # MESSAGE HISTORY
    # ==========================================================

    def add_message(
        self,
        guild_id,
        channel_id,
        user_id,
        character_name,
        role,
        content
    ):

        content = str(content).strip()

        if not content:
            return

        self._execute(
            """
            INSERT INTO messages (
                guild_id,
                channel_id,
                user_id,
                character_name,
                role,
                content
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                channel_id,
                user_id,
                character_name,
                role,
                content
            ),
            commit=True
        )

    def get_history(
        self,
        guild_id,
        channel_id,
        character_name,
        limit=20
    ):

        try:
            limit = int(limit)
        except Exception:
            limit = 20

        limit = max(
            1,
            min(limit, 100)
        )

        rows = self._execute(
            f"""
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
            WHERE guild_id = ?
            AND channel_id = ?
            AND character_name = ?
            ORDER BY id DESC
            LIMIT {limit}
            """,
            (
                guild_id,
                channel_id,
                character_name
            ),
            fetchall=True
        )

        return list(
            reversed(rows)
        )

    def clear_history(
        self,
        guild_id,
        channel_id=None,
        character_name=None
    ):

        if channel_id is not None:

            if character_name is not None:

                self._execute(
                    """
                    DELETE FROM messages
                    WHERE guild_id = ?
                    AND channel_id = ?
                    AND character_name = ?
                    """,
                    (
                        guild_id,
                        channel_id,
                        character_name
                    ),
                    commit=True
                )

            else:

                self._execute(
                    """
                    DELETE FROM messages
                    WHERE guild_id = ?
                    AND channel_id = ?
                    """,
                    (
                        guild_id,
                        channel_id
                    ),
                    commit=True
                )

        elif character_name is not None:

            self._execute(
                """
                DELETE FROM messages
                WHERE guild_id = ?
                AND character_name = ?
                """,
                (
                    guild_id,
                    character_name
                ),
                commit=True
            )

        else:

            self._execute(
                """
                DELETE FROM messages
                WHERE guild_id = ?
                """,
                (guild_id,),
                commit=True
            )

    # ==========================================================
    # SETTINGS
    # ==========================================================

    def get_settings(
        self,
        guild_id
    ):

        self.ensure_guild(
            guild_id
        )

        row = self._execute(
            """
            SELECT *
            FROM guild_settings
            WHERE guild_id = ?
            """,
            (guild_id,),
            fetchone=True
        )

        return dict(row) if row else {}

    # ==========================================================
    # STATS
    # ==========================================================

    def get_stats(
        self,
        guild_id
    ):

        messages = self._execute(
            """
            SELECT COUNT(*) AS count
            FROM messages
            WHERE guild_id = ?
            """,
            (guild_id,),
            fetchone=True
        )

        characters = self._execute(
            """
            SELECT COUNT(*) AS count
            FROM characters
            WHERE guild_id = ?
            """,
            (guild_id,),
            fetchone=True
        )

        return {
            "messages":
                messages["count"]
                if messages else 0,

            "characters":
                characters["count"]
                if characters else 0
        }

    # ==========================================================
    # DELETE GUILD
    # ==========================================================

    def delete_guild(
        self,
        guild_id
    ):

        self._execute(
            """
            DELETE FROM messages
            WHERE guild_id = ?
            """,
            (guild_id,),
            commit=True
        )

        self._execute(
            """
            DELETE FROM characters
            WHERE guild_id = ?
            """,
            (guild_id,),
            commit=True
        )

        self._execute(
            """
            DELETE FROM guild_settings
            WHERE guild_id = ?
            """,
            (guild_id,),
            commit=True
        )

        self._execute(
            """
            DELETE FROM ai_config
            WHERE guild_id = ?
            """,
            (guild_id,),
            commit=True
        )

    # ==========================================================
    # CLOSE
    # ==========================================================

    def close(self):

        with self.lock:

            if self.conn:

                self.conn.commit()
                self.conn.close()
                self.conn = None
