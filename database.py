import sqlite3
from datetime import datetime
from threading import Lock


DATABASE_NAME = "myai.db"


class Database:

    def __init__(self):
        self.lock = Lock()

        self.connection = sqlite3.connect(
            DATABASE_NAME,
            check_same_thread=False
        )

        self.connection.row_factory = sqlite3.Row

        self.create_tables()

    # =========================================================
    # أدوات داخلية
    # =========================================================

    def now(self):
        return datetime.utcnow().isoformat()

    # =========================================================
    # إنشاء الجداول
    # =========================================================

    def create_tables(self):

        with self.lock:

            cursor = self.connection.cursor()

            # -------------------------------------------------
            # الشخصيات
            # -------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS characters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    guild_id TEXT NOT NULL,

                    name TEXT NOT NULL,

                    description TEXT NOT NULL,

                    personality TEXT NOT NULL,

                    system_prompt TEXT NOT NULL,

                    provider TEXT DEFAULT 'openai',

                    model TEXT DEFAULT '',

                    created_at TEXT NOT NULL,

                    UNIQUE(guild_id, name)
                )
            """)

            # -------------------------------------------------
            # الرسائل
            # -------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    guild_id TEXT NOT NULL,

                    channel_id TEXT NOT NULL,

                    user_id TEXT NOT NULL,

                    character_name TEXT NOT NULL,

                    role TEXT NOT NULL,

                    content TEXT NOT NULL,

                    created_at TEXT NOT NULL
                )
            """)

            # -------------------------------------------------
            # إعدادات السيرفر
            # -------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id TEXT PRIMARY KEY,

                    active_character TEXT DEFAULT 'MyAI',

                    active_provider TEXT DEFAULT 'openai',

                    active_model TEXT DEFAULT '',

                    auto_chat INTEGER DEFAULT 0
                )
            """)

            self.connection.commit()

    # =========================================================
    # الشخصيات
    # =========================================================

    def create_character(
        self,
        guild_id,
        name,
        description,
        personality,
        system_prompt,
        provider="openai",
        model=""
    ):

        with self.lock:

            cursor = self.connection.cursor()

            try:

                cursor.execute("""
                    INSERT INTO characters (
                        guild_id,
                        name,
                        description,
                        personality,
                        system_prompt,
                        provider,
                        model,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(guild_id),
                    name,
                    description,
                    personality,
                    system_prompt,
                    provider,
                    model,
                    self.now()
                ))

                self.connection.commit()

                return True

            except sqlite3.IntegrityError:

                return False

    def get_character(
        self,
        guild_id,
        name
    ):

        with self.lock:

            cursor = self.connection.cursor()

            cursor.execute("""
                SELECT *
                FROM characters
                WHERE guild_id = ?
                AND LOWER(name) = LOWER(?)
                LIMIT 1
            """, (
                str(guild_id),
                name
            ))

            return cursor.fetchone()

    def get_characters(
        self,
        guild_id
    ):

        with self.lock:

            cursor = self.connection.cursor()

            cursor.execute("""
                SELECT *
                FROM characters
                WHERE guild_id = ?
                ORDER BY id ASC
            """, (
                str(guild_id),
            ))

            return cursor.fetchall()

    def delete_character(
        self,
        guild_id,
        name
    ):

        with self.lock:

            cursor = self.connection.cursor()

            cursor.execute("""
                DELETE FROM characters
                WHERE guild_id = ?
                AND LOWER(name) = LOWER(?)
            """, (
                str(guild_id),
                name
            ))

            self.connection.commit()

            return cursor.rowcount > 0

    # =========================================================
    # الرسائل
    # =========================================================

    def add_message(
        self,
        guild_id,
        channel_id,
        user_id,
        character_name,
        role,
        content
    ):

        with self.lock:

            cursor = self.connection.cursor()

            cursor.execute("""
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
            """, (
                str(guild_id),
                str(channel_id),
                str(user_id),
                character_name,
                role,
                content,
                self.now()
            ))

            self.connection.commit()

    def get_history(
        self,
        guild_id,
        channel_id,
        character_name,
        limit=20
    ):

        with self.lock:

            cursor = self.connection.cursor()

            cursor.execute("""
                SELECT role, content
                FROM messages
                WHERE guild_id = ?
                AND channel_id = ?
                AND character_name = ?
                ORDER BY id DESC
                LIMIT ?
            """, (
                str(guild_id),
                str(channel_id),
                character_name,
                limit
            ))

            rows = cursor.fetchall()

            rows.reverse()

            return [
                {
                    "role": row["role"],
                    "content": row["content"]
                }
                for row in rows
            ]

    def clear_history(
        self,
        guild_id,
        channel_id,
        character_name
    ):

        with self.lock:

            cursor = self.connection.cursor()

            cursor.execute("""
                DELETE FROM messages
                WHERE guild_id = ?
                AND channel_id = ?
                AND character_name = ?
            """, (
                str(guild_id),
                str(channel_id),
                character_name
            ))

            self.connection.commit()

    # =========================================================
    # إعدادات السيرفر
    # =========================================================

    def ensure_guild(
        self,
        guild_id
    ):

        with self.lock:

            cursor = self.connection.cursor()

            cursor.execute("""
                INSERT OR IGNORE INTO guild_settings (
                    guild_id
                )
                VALUES (?)
            """, (
                str(guild_id),
            ))

            self.connection.commit()

    def get_settings(
        self,
        guild_id
    ):

        self.ensure_guild(guild_id)

        with self.lock:

            cursor = self.connection.cursor()

            cursor.execute("""
                SELECT *
                FROM guild_settings
                WHERE guild_id = ?
            """, (
                str(guild_id),
            ))

            return cursor.fetchone()

    def set_active_character(
        self,
        guild_id,
        character
    ):

        self.ensure_guild(guild_id)

        with self.lock:

            cursor = self.connection.cursor()

            cursor.execute("""
                UPDATE guild_settings

                SET active_character = ?

                WHERE guild_id = ?
            """, (
                character,
                str(guild_id)
            ))

            self.connection.commit()

    def set_provider(
        self,
        guild_id,
        provider,
        model=""
    ):

        self.ensure_guild(guild_id)

        with self.lock:

            cursor = self.connection.cursor()

            cursor.execute("""
                UPDATE guild_settings

                SET active_provider = ?,
                    active_model = ?

                WHERE guild_id = ?
            """, (
                provider,
                model,
                str(guild_id)
            ))

            self.connection.commit()

    def set_auto_chat(
        self,
        guild_id,
        enabled
    ):

        self.ensure_guild(guild_id)

        with self.lock:

            cursor = self.connection.cursor()

            cursor.execute("""
                UPDATE guild_settings

                SET auto_chat = ?

                WHERE guild_id = ?
            """, (
                1 if enabled else 0,
                str(guild_id)
            ))

            self.connection.commit()

    # =========================================================
    # إغلاق قاعدة البيانات
    # =========================================================

    def close(self):

        with self.lock:

            self.connection.close()
