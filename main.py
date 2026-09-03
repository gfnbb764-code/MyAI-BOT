import os
import re
import asyncio
import random
import traceback
import time
import json
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

from database import Database
from ai_engine import AIEngine


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")

PRIMARY_AI_PROVIDER = os.getenv(
    "PRIMARY_AI_PROVIDER",
    "google"
).lower()

GOOGLE_MODEL = os.getenv(
    "GOOGLE_MODEL",
    "gemini-3.5-flash-lite"
)

DEFAULT_CHANNEL = None

MAX_ACTIVE_REQUESTS = 3
DEFAULT_AI_TIMEOUT = 35

MIN_TYPING_DELAY = 3.0
MAX_TYPING_DELAY = 5.0


# ============================================================
# AI MODES
# ============================================================

AI_MODES = {
    "normal": {
        "name": "عادي",
        "description": "ردود متوازنة وطبيعية",
    },
    "friendly": {
        "name": "ودود",
        "description": "ردود لطيفة وودية",
    },
    "active": {
        "name": "نشط",
        "description": "تفاعل أكثر وحيوية أعلى",
    },
    "fun": {
        "name": "مرح",
        "description": "ردود مرحة ومليئة بالطاقة",
    },
    "professional": {
        "name": "احترافي",
        "description": "ردود رسمية ومنظمة",
    },
}


# ============================================================
# REPLY TYPES
# ============================================================

REPLY_TYPES = {
    "mention": {
        "name": "منشن البوت",
        "description": "يرد فقط عند منشن البوت",
    },
    "channel": {
        "name": "مباشرة في الروم",
        "description": "يرد على الرسائل داخل الروم المحدد",
    },
    "direct": {
        "name": "مباشر",
        "description": "يرد عندما تكون الرسالة موجهة له مباشرة",
    },
    "auto": {
        "name": "تلقائي",
        "description": "يتفاعل تلقائيًا مع الرسائل",
    },
    "bot_chat": {
        "name": "Bot to Bot",
        "description": "يسمح للمساعد بالتفاعل مع البوتات الأخرى",
    },
}


# ============================================================
# CHARACTER TYPES
# ============================================================

CHARACTER_TYPES = {
    "normal": "عادي",
    "calm": "هادئ",
    "smart": "ذكي",
    "funny": "مضحك",
    "friendly": "ودود",
    "formal": "رسمي",
    "energetic": "حماسي",
    "rude": "فظ",
    "mischievous": "مشاغب",
    "curious": "فضولي",
    "creative": "إبداعي",
    "professional": "احترافي",
}


# ============================================================
# SENSITIVE KEYWORDS
# ============================================================

DEFAULT_SENSITIVE_KEYWORDS = [
    "kill",
    "killing",
    "murder",
    "weapon",
    "weapons",
    "explosive",
    "explosives",
    "bomb",
    "gun",
    "hurt",
    "suicide",
    "اقتل",
    "قتل",
    "سلاح",
    "أسلحة",
    "متفجرات",
    "قنبلة",
    "مسدس",
    "إيذاء",
]


# ============================================================
# BOT CHAT SYSTEM
# ============================================================

BOT_CHAT_CHAINS = {}
BOT_CHAT_LAST_RESPONSE = {}
BOT_CHAT_LOCKS = {}

DEFAULT_MAX_BOT_CHAIN = 6
DEFAULT_BOT_COOLDOWN = 2.0


# ============================================================
# DISCORD
# ============================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True
intents.dm_messages = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)


# ============================================================
# DATABASE / AI
# ============================================================

db = Database()
ai = AIEngine(db)

AI_SEMAPHORE = asyncio.Semaphore(
    MAX_ACTIVE_REQUESTS
)

ACTIVE_REQUESTS = set()


# ============================================================
# GENERAL HELPERS
# ============================================================

def row_to_dict(row):
    """
    تحويل SQLite Row إلى dict.
    """

    if row is None:
        return None

    if isinstance(row, dict):
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


def get_config(guild_id: int):
    """
    جلب إعدادات السيرفر الأساسية.
    """

    try:
        config = db.get_guild_config(
            guild_id
        )
    except Exception:
        try:
            config = db.get_ai_config(
                guild_id
            )
        except Exception:
            config = None

    if not config:
        return {
            "guild_id": guild_id,
            "enabled": True,
            "channel_id": None,
            "mode": "normal",
            "reply_type": "mention",
            "character": None,
            "provider": PRIMARY_AI_PROVIDER,
            "model": GOOGLE_MODEL,
        }

    data = row_to_dict(config)

    return {
        "guild_id": guild_id,

        "enabled": bool(
            data.get(
                "enabled",
                data.get(
                    "ai_enabled",
                    True
                )
            )
        ),

        "channel_id": data.get(
            "channel_id",
            data.get(
                "ai_channel_id"
            )
        ),

        "mode": data.get(
            "mode",
            data.get(
                "ai_mode",
                "normal"
            )
        ) or "normal",

        "reply_type": data.get(
            "reply_type",
            "mention"
        ) or "mention",

        "character": data.get(
            "character",
            data.get(
                "active_character"
            )
        ),

        "provider": data.get(
            "provider",
            data.get(
                "active_provider",
                PRIMARY_AI_PROVIDER
            )
        ) or PRIMARY_AI_PROVIDER,

        "model": data.get(
            "model",
            data.get(
                "active_model",
                GOOGLE_MODEL
            )
        ) or GOOGLE_MODEL,
    }


def update_config(
    guild_id: int,
    **kwargs
):
    """
    تحديث إعدادات السيرفر مع توافق مع نسخ Database المختلفة.
    """

    try:
        return db.update_guild_config(
            guild_id,
            **kwargs
        )
    except Exception:
        try:
            return db.save_ai_config(
                guild_id,
                **kwargs
            )
        except Exception:
            traceback.print_exc()
            return False


def get_advanced(guild_id: int):
    """
    جلب الإعدادات المتقدمة.
    """

    defaults = {
        "memory_enabled": True,
        "history_limit": 20,
        "response_length": 1200,
        "timeout": DEFAULT_AI_TIMEOUT,
        "security_enabled": True,
        "bot_chat_enabled": True,
        "bot_chat_max_chain": DEFAULT_MAX_BOT_CHAIN,
        "bot_chat_cooldown": DEFAULT_BOT_COOLDOWN,
        "allow_members": [],
        "deny_members": [],
        "sensitive_keywords": (
            DEFAULT_SENSITIVE_KEYWORDS.copy()
        ),
    }

    try:
        row = db.get_ai_advanced_settings(
            guild_id
        )
    except Exception:
        return defaults

    if not row:
        return defaults

    data = row_to_dict(row)

    result = defaults.copy()

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
        if key in data and data[key] is not None:
            result[key] = data[key]

    for key in [
        "allow_members",
        "deny_members",
        "sensitive_keywords",
    ]:
        value = data.get(key)

        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                value = [
                    x.strip()
                    for x in value.split(",")
                    if x.strip()
                ]

        if not isinstance(value, list):
            value = defaults[key].copy()

        result[key] = value

    result["memory_enabled"] = bool(
        result["memory_enabled"]
    )

    result["security_enabled"] = bool(
        result["security_enabled"]
    )

    result["bot_chat_enabled"] = bool(
        result["bot_chat_enabled"]
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
        result["timeout"] = DEFAULT_AI_TIMEOUT

    try:
        result["bot_chat_max_chain"] = max(
            1,
            min(
                50,
                int(
                    result["bot_chat_max_chain"]
                )
            )
        )
    except Exception:
        result["bot_chat_max_chain"] = (
            DEFAULT_MAX_BOT_CHAIN
        )

    try:
        result["bot_chat_cooldown"] = max(
            0.0,
            min(
                60.0,
                float(
                    result["bot_chat_cooldown"]
                )
            )
        )
    except Exception:
        result["bot_chat_cooldown"] = (
            DEFAULT_BOT_COOLDOWN
        )

    return result


def save_advanced(
    guild_id: int,
    settings: dict
):
    """
    حفظ الإعدادات المتقدمة.
    """

    try:
        return db.save_ai_advanced_settings(
            guild_id,
            settings
        )
    except TypeError:
        try:
            return db.save_ai_advanced_settings(
                guild_id,
                **settings
            )
        except Exception:
            traceback.print_exc()
            return False

    except Exception:
        traceback.print_exc()
        return False


def reset_advanced(
    guild_id: int
):
    """
    إعادة الإعدادات المتقدمة للوضع الافتراضي.
    """

    try:
        return db.reset_ai_advanced_settings(
            guild_id
        )
    except Exception:
        traceback.print_exc()
        return False


# ============================================================
# CHARACTER HELPERS
# ============================================================

def get_character(
    guild_id: int,
    character_name: Optional[str]
):
    """
    جلب شخصية من السيرفر بالاسم.
    """

    if not character_name:
        return None

    try:
        return db.get_character(
            guild_id,
            character_name
        )
    except TypeError:
        try:
            return db.get_character(
                character_name
            )
        except Exception:
            return None
    except Exception:
        return None


def get_all_characters(
    guild_id: int
):
    """
    جلب جميع شخصيات السيرفر.
    """

    try:
        return db.get_characters(
            guild_id
        )
    except Exception:
        try:
            return db.list_characters(
                guild_id
            )
        except Exception:
            return []


def get_user_characters(
    guild_id: int,
    user_id: int
):
    """
    جلب الشخصيات التي يملكها المستخدم.
    """

    try:
        return db.get_user_characters(
            guild_id,
            user_id
        )
    except Exception:
        return []


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_text(
    text: str
) -> str:
    """
    تنظيف النص للمقارنة.
    """

    if not text:
        return ""

    text = text.lower().strip()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text


def clean_mentions(
    message: discord.Message,
    content: str
) -> str:
    """
    إزالة منشن البوت من النص.
    """

    if not content:
        return ""

    if bot.user:

        content = content.replace(
            f"<@{bot.user.id}>",
            ""
        )

        content = content.replace(
            f"<@!{bot.user.id}>",
            ""
        )

    return content.strip()


def split_message(
    text: str,
    limit: int = 1900
):
    """
    تقسيم الردود الطويلة.
    """

    if not text:
        return []

    if len(text) <= limit:
        return [text]

    chunks = []

    while len(text) > limit:

        split_at = text.rfind(
            "\n",
            0,
            limit
        )

        if split_at <= 0:
            split_at = text.rfind(
                " ",
                0,
                limit
            )

        if split_at <= 0:
            split_at = limit

        chunks.append(
            text[:split_at].strip()
        )

        text = text[
            split_at:
        ].strip()

    if text:
        chunks.append(text)

    return chunks


def normalize_channel_id(
    value
):
    """
    تحويل channel_id إلى int.
    """

    if value is None:
        return None

    try:
        return int(value)
    except Exception:
        return None


def channel_matches(
    message: discord.Message,
    channel_id
) -> bool:
    """
    التحقق من الروم المحدد.
    """

    channel_id = normalize_channel_id(
        channel_id
    )

    if channel_id is None:
        return True

    return (
        message.channel.id == channel_id
    )


# ============================================================
# BOT DIRECTED CHECK
# ============================================================

def is_directed_to_bot(
    message: discord.Message
) -> bool:
    """
    هل الرسالة موجهة للبوت؟
    """

    if not bot.user:
        return False

    if bot.user in message.mentions:
        return True

    content = normalize_text(
        message.content
    )

    bot_name = normalize_text(
        bot.user.name
    )

    if (
        bot_name
        and bot_name in content
    ):
        return True

    return False


# ============================================================
# PERMISSIONS
# ============================================================

def has_broad_management(
    member: discord.Member
) -> bool:
    """
    صلاحيات الإدارة العامة.
    """

    if (
        member.guild.owner_id
        == member.id
    ):
        return True

    permissions = (
        member.guild_permissions
    )

    return any([
        permissions.administrator,
        permissions.manage_guild,
        permissions.manage_channels,
        permissions.manage_roles,
    ])


def get_top_three_roles(
    guild: discord.Guild
):
    """
    أعلى 3 رتب فعلية.
    """

    roles = [
        role
        for role in guild.roles
        if not role.is_default()
        and not role.managed
    ]

    roles.sort(
        key=lambda role: role.position,
        reverse=True
    )

    return roles[:3]


def can_use_ai_dashboard(
    member: discord.Member
) -> bool:
    """
    أصحاب أعلى 3 رتب يستطيعون استخدام لوحة AI.
    """

    top_roles = get_top_three_roles(
        member.guild
    )

    return any(
        role in member.roles
        for role in top_roles
    )


def security_check(
    member: discord.Member
) -> bool:
    """
    فحص صلاحيات الأمان.
    """

    return (
        can_use_ai_dashboard(member)
        or has_broad_management(member)
    )


# ============================================================
# MEMBER FILTER
# ============================================================

def member_allowed(
    user_id: int,
    advanced: dict
) -> bool:

    deny_members = set()

    for value in advanced.get(
        "deny_members",
        []
    ):
        try:
            deny_members.add(
                int(value)
            )
        except Exception:
            pass

    if user_id in deny_members:
        return False

    allow_members = advanced.get(
        "allow_members",
        []
    )

    if allow_members:

        try:
            allow_ids = {
                int(value)
                for value in allow_members
            }
        except Exception:
            allow_ids = set()

        return user_id in allow_ids

    return True


# ============================================================
# SENSITIVE CONTENT
# ============================================================

def contains_sensitive_content(
    content: str,
    advanced: dict
) -> bool:

    if not advanced.get(
        "security_enabled",
        True
    ):
        return False

    text = normalize_text(
        content
    )

    keywords = advanced.get(
        "sensitive_keywords",
        DEFAULT_SENSITIVE_KEYWORDS
    )

    for keyword in keywords:

        keyword = normalize_text(
            str(keyword)
        )

        if (
            keyword
            and keyword in text
        ):
            return True

    return False


# ============================================================
# REQUEST TRACKING
# ============================================================

def get_request_key(
    message: discord.Message
):
    return (
        message.guild.id
        if message.guild
        else 0,
        message.author.id,
        message.channel.id,
    )


# ============================================================
# BOT CHAT PROTECTION
# ============================================================

def get_bot_lock(
    guild_id: int
):
    if guild_id not in BOT_CHAT_LOCKS:
        BOT_CHAT_LOCKS[guild_id] = (
            asyncio.Lock()
        )

    return BOT_CHAT_LOCKS[guild_id]


def get_bot_chain(
    guild_id: int
) -> int:
    return BOT_CHAT_CHAINS.get(
        guild_id,
        0
    )


def reset_bot_chain(
    guild_id: int
):
    BOT_CHAT_CHAINS[guild_id] = 0


def increment_bot_chain(
    guild_id: int
) -> int:

    value = BOT_CHAT_CHAINS.get(
        guild_id,
        0
    )

    value += 1

    BOT_CHAT_CHAINS[guild_id] = value

    return value


def bot_cooldown_active(
    guild_id: int,
    cooldown: float
) -> bool:

    last_response = (
        BOT_CHAT_LAST_RESPONSE.get(
            guild_id
        )
    )

    if last_response is None:
        return False

    return (
        time.monotonic()
        - last_response
    ) < cooldown


def should_process_bot_chat(
    message: discord.Message,
    config: dict,
    advanced: dict
) -> bool:

    if not advanced.get(
        "bot_chat_enabled",
        True
    ):
        return False

    if not message.author.bot:
        return False

    if (
        bot.user
        and message.author.id
        == bot.user.id
    ):
        return False

    if not message.guild:
        return False

    guild_id = message.guild.id

    max_chain = advanced.get(
        "bot_chat_max_chain",
        DEFAULT_MAX_BOT_CHAIN
    )

    if (
        get_bot_chain(guild_id)
        >= max_chain
    ):
        reset_bot_chain(
            guild_id
        )
        return False

    cooldown = advanced.get(
        "bot_chat_cooldown",
        DEFAULT_BOT_COOLDOWN
    )

    if bot_cooldown_active(
        guild_id,
        cooldown
    ):
        return False

    return True


# ============================================================
# SAVE MESSAGE
# ============================================================

def save_database_message(
    message: discord.Message,
    character_name: Optional[str] = None
):
    """
    حفظ الرسالة بطريقة متوافقة مع Database.
    """

    if not message.guild:
        return False

    guild_id = message.guild.id
    channel_id = message.channel.id
    user_id = message.author.id

    role = (
        "assistant"
        if message.author.bot
        else "user"
    )

    content = message.content

    try:
        return db.add_message(
            guild_id,
            channel_id,
            user_id,
            character_name,
            role,
            content
        )

    except TypeError:

        try:
            return db.save_message(
                guild_id=guild_id,
                channel_id=channel_id,
                user_id=user_id,
                character_name=character_name,
                role=role,
                content=content
            )

        except Exception:

            try:
                return db.save_message(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    user_id=user_id,
                    role=role,
                    content=content
                )
            except Exception:
                return False

    except Exception:
        traceback.print_exc()
        return False


# ============================================================
# AI GENERATION
# ============================================================

async def generate_chat_reply(
    message: discord.Message,
    prompt: str
):

    guild = message.guild

    if guild is None:
        return None

    config = get_config(
        guild.id
    )

    advanced = get_advanced(
        guild.id
    )

    character_name = (
        config.get("character")
        or None
    )

    mode = config.get(
        "mode",
        "normal"
    )

    provider = config.get(
        "provider",
        PRIMARY_AI_PROVIDER
    )

    model = config.get(
        "model",
        GOOGLE_MODEL
    )

    prompt = clean_mentions(
        message,
        prompt
    )

    if not prompt:
        prompt = (
            "رد على المستخدم بشكل طبيعي."
        )

    memory_enabled = advanced.get(
        "memory_enabled",
        True
    )

    history_limit = advanced.get(
        "history_limit",
        20
    )

    response_length = advanced.get(
        "response_length",
        1200
    )

    timeout = advanced.get(
        "timeout",
        DEFAULT_AI_TIMEOUT
    )

    request_key = get_request_key(
        message
    )

    if request_key in ACTIVE_REQUESTS:
        return None

    ACTIVE_REQUESTS.add(
        request_key
    )

    try:

        async with AI_SEMAPHORE:

            # ==================================================
            # IMPORTANT:
            # AIEngine الحالي عندك يستخدم:
            #
            # generate(
            #   guild_id,
            #   channel_id,
            #   user_id,
            #   character_name,
            #   user_message,
            #   provider=None,
            #   model=None,
            #   mode="normal"
            # )
            #
            # لذلك لا نرسل:
            # memory_enabled
            # history_limit
            # max_tokens_override
            # character
            # prompt
            # ==================================================

            result = await asyncio.wait_for(
                ai.generate(
                    guild_id=guild.id,
                    channel_id=message.channel.id,
                    user_id=message.author.id,
                    character_name=character_name,
                    user_message=prompt,
                    provider=provider,
                    model=model,
                    mode=mode,
                ),
                timeout=timeout
            )

            return result

    except asyncio.TimeoutError:

        return (
            "⏱️ انتهى وقت معالجة الطلب."
        )

    except Exception:

        traceback.print_exc()

        return (
            "❌ حدث خطأ أثناء توليد الرد."
        )

    finally:

        ACTIVE_REQUESTS.discard(
            request_key
        )


# ============================================================
# DM AI
# ============================================================

async def generate_dm_reply(
    user_id: int,
    prompt: str
):

    try:

        async with AI_SEMAPHORE:

            result = await asyncio.wait_for(
                ai.generate(
                    guild_id=0,
                    channel_id=0,
                    user_id=user_id,
                    character_name=None,
                    user_message=prompt,
                    provider=PRIMARY_AI_PROVIDER,
                    model=GOOGLE_MODEL,
                    mode="normal",
                ),
                timeout=DEFAULT_AI_TIMEOUT
            )

            return result

    except asyncio.TimeoutError:

        return (
            "⏱️ انتهى وقت معالجة الطلب."
        )

    except Exception:

        traceback.print_exc()

        return (
            "❌ حدث خطأ أثناء معالجة رسالتك."
        )


# ============================================================
# SEND AI RESPONSE
# ============================================================

async def send_ai_response(
    message: discord.Message,
    response: str
):

    if not response:
        return

    chunks = split_message(
        response,
        1900
    )

    for chunk in chunks:

        await message.channel.send(
            chunk,
            allowed_mentions=(
                discord.AllowedMentions.none()
            )
        )


# ============================================================
# TYPING RESPONSE
# ============================================================

async def generate_with_typing_message(
    message: discord.Message,
    prompt: str
):

    config = get_config(
        message.guild.id
    )

    character_name = (
        config.get("character")
        or "MyAI"
    )

    placeholder = None

    try:

        placeholder = (
            await message.channel.send(
                f"**{character_name}** يكتب..."
            )
        )

        delay = random.uniform(
            MIN_TYPING_DELAY,
            MAX_TYPING_DELAY
        )

        await asyncio.sleep(
            delay
        )

        response = await generate_chat_reply(
            message,
            prompt
        )

        if not response:

            if placeholder:
                await placeholder.delete()

            return

        chunks = split_message(
            response,
            1900
        )

        if not chunks:

            if placeholder:
                await placeholder.delete()

            return

        await placeholder.edit(
            content=chunks[0]
        )

        for chunk in chunks[1:]:

            await message.channel.send(
                chunk,
                allowed_mentions=(
                    discord.AllowedMentions.none()
                )
            )

    except asyncio.CancelledError:

        if placeholder:

            try:
                await placeholder.delete()
            except Exception:
                pass

        raise

    except Exception:

        traceback.print_exc()

        if placeholder:

            try:
                await placeholder.edit(
                    content=(
                        "❌ حدث خطأ أثناء توليد الرد."
                    )
                )
            except Exception:
                pass


# ============================================================
# CHARACTER DROPDOWN
# ============================================================

def make_character_options(
    characters
):

    options = []

    for character in characters[:25]:

        data = row_to_dict(
            character
        )

        name = data.get(
            "name",
            "بدون اسم"
        )

        char_type = data.get(
            "character_type",
            data.get(
                "type",
                "normal"
            )
        )

        type_name = CHARACTER_TYPES.get(
            char_type,
            char_type
        )

        description = (
            data.get("description")
            or f"شخصية {type_name}"
        )

        options.append(
            discord.SelectOption(
                label=str(name)[:100],
                description=str(
                    description
                )[:100],
                value=str(name)[:100],
            )
        )

    return options


# ============================================================
# CHARACTER INFO VIEW
# ============================================================

class CharacterInfoSelect(
    discord.ui.Select
):

    def __init__(
        self,
        guild_id,
        characters
    ):

        self.guild_id = guild_id

        options = make_character_options(
            characters
        )

        super().__init__(
            placeholder="اختر الشخصية...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        name = self.values[0]

        character = get_character(
            self.guild_id,
            name
        )

        if not character:

            await interaction.response.send_message(
                "❌ الشخصية غير موجودة.",
                ephemeral=True
            )

            return

        data = row_to_dict(
            character
        )

        char_type = data.get(
            "character_type",
            data.get(
                "type",
                "normal"
            )
        )

        owner_id = data.get(
            "created_by",
            data.get(
                "owner_id"
            )
        )

        embed = discord.Embed(
            title=(
                f"🎭 {data.get('name', name)}"
            ),
            description=(
                data.get(
                    "description"
                )
                or "لا يوجد وصف."
            ),
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="النوع",
            value=CHARACTER_TYPES.get(
                char_type,
                char_type
            ),
            inline=True
        )

        embed.add_field(
            name="المالك",
            value=(
                f"<@{owner_id}>"
                if owner_id
                else "غير معروف"
            ),
            inline=True
        )

        embed.add_field(
            name="Provider",
            value=data.get(
                "provider",
                PRIMARY_AI_PROVIDER
            ),
            inline=True
        )

        embed.add_field(
            name="Model",
            value=data.get(
                "model",
                GOOGLE_MODEL
            ),
            inline=True
        )

        personality = data.get(
            "personality"
        )

        if personality:

            embed.add_field(
                name="الشخصية",
                value=str(
                    personality
                )[:1024],
                inline=False
            )

        embed.set_footer(
            text="MyAI • Character Info"
        )

        await interaction.response.edit_message(
            embed=embed,
            view=None
        )


class CharacterInfoView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id,
        characters
    ):

        super().__init__(
            timeout=120
        )

        if characters:

            self.add_item(
                CharacterInfoSelect(
                    guild_id,
                    characters
                )
            )


# ============================================================
# CHARACTER USE VIEW
# ============================================================

class CharacterUseSelect(
    discord.ui.Select
):

    def __init__(
        self,
        guild_id,
        characters
    ):

        self.guild_id = guild_id

        super().__init__(
            placeholder=(
                "اختر الشخصية التي تريد تفعيلها..."
            ),
            min_values=1,
            max_values=1,
            options=make_character_options(
                characters
            )
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:
            return

        member = interaction.user

        if not isinstance(
            member,
            discord.Member
        ):
            return

        if not has_broad_management(
            member
        ):

            await interaction.response.send_message(
                "❌ تحتاج صلاحيات إدارة السيرفر.",
                ephemeral=True
            )

            return

        name = self.values[0]

        try:

            update_config(
                self.guild_id,
                character=name
            )

        except Exception:

            traceback.print_exc()

            await interaction.response.send_message(
                "❌ تعذر تفعيل الشخصية.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            f"✅ تم تفعيل الشخصية **{name}**.",
            ephemeral=True
        )


class CharacterUseView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id,
        characters
    ):

        super().__init__(
            timeout=120
        )

        if characters:

            self.add_item(
                CharacterUseSelect(
                    guild_id,
                    characters
                )
            )


# ============================================================
# CHARACTER EDIT
# ============================================================

class CharacterEditModal(
    discord.ui.Modal,
    title="تعديل الشخصية"
):

    personality = discord.ui.TextInput(
        label="الشخصية",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=2000
    )

    description = discord.ui.TextInput(
        label="الوصف",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000
    )

    speaking_style = discord.ui.TextInput(
        label="أسلوب الكلام",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000
    )

    custom_instructions = discord.ui.TextInput(
        label="التعليمات المخصصة",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=3000
    )

    def __init__(
        self,
        guild_id,
        character
    ):

        super().__init__()

        self.guild_id = guild_id

        self.character = row_to_dict(
            character
        )

        self.personality.default = (
            self.character.get(
                "personality"
            ) or ""
        )

        self.description.default = (
            self.character.get(
                "description"
            ) or ""
        )

        self.speaking_style.default = (
            self.character.get(
                "speaking_style"
            ) or ""
        )

        self.custom_instructions.default = (
            self.character.get(
                "custom_instructions"
            ) or ""
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        name = self.character.get(
            "name"
        )

        owner_id = self.character.get(
            "created_by",
            self.character.get(
                "owner_id"
            )
        )

        if owner_id != interaction.user.id:

            await interaction.response.send_message(
                "❌ هذه الشخصية ليست ملكك.",
                ephemeral=True
            )

            return

        try:

            db.update_character(
                self.guild_id,
                name,
                personality=self.personality.value,
                description=self.description.value,
                speaking_style=self.speaking_style.value,
                custom_instructions=(
                    self.custom_instructions.value
                ),
            )

            await interaction.response.send_message(
                f"✅ تم تعديل الشخصية **{name}**.",
                ephemeral=True
            )

        except TypeError:

            try:

                db.update_character(
                    name,
                    personality=self.personality.value,
                    description=self.description.value,
                    speaking_style=self.speaking_style.value,
                    custom_instructions=(
                        self.custom_instructions.value
                    ),
                )

                await interaction.response.send_message(
                    f"✅ تم تعديل الشخصية **{name}**.",
                    ephemeral=True
                )

            except Exception:

                traceback.print_exc()

                await interaction.response.send_message(
                    "❌ تعذر تعديل الشخصية.",
                    ephemeral=True
                )

        except Exception:

            traceback.print_exc()

            await interaction.response.send_message(
                "❌ تعذر تعديل الشخصية.",
                ephemeral=True
            )


class CharacterEditSelect(
    discord.ui.Select
):

    def __init__(
        self,
        guild_id,
        characters
    ):

        self.guild_id = guild_id

        super().__init__(
            placeholder="اختر شخصيتك...",
            min_values=1,
            max_values=1,
            options=make_character_options(
                characters
            )
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        character = get_character(
            self.guild_id,
            self.values[0]
        )

        if not character:

            await interaction.response.send_message(
                "❌ الشخصية غير موجودة.",
                ephemeral=True
            )

            return

        data = row_to_dict(
            character
        )

        owner_id = data.get(
            "created_by",
            data.get(
                "owner_id"
            )
        )

        if owner_id != interaction.user.id:

            await interaction.response.send_message(
                "❌ يمكنك تعديل الشخصيات التي تملكها فقط.",
                ephemeral=True
            )

            return

        await interaction.response.send_modal(
            CharacterEditModal(
                self.guild_id,
                character
            )
        )


class CharacterEditView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id,
        characters
    ):

        super().__init__(
            timeout=120
        )

        if characters:

            self.add_item(
                CharacterEditSelect(
                    guild_id,
                    characters
                )
            )


# ============================================================
# CHARACTER DELETE
# ============================================================

class CharacterDeleteConfirm(
    discord.ui.View
):

    def __init__(
        self,
        guild_id,
        character_name,
        owner_id
    ):

        super().__init__(
            timeout=60
        )

        self.guild_id = guild_id
        self.character_name = character_name
        self.owner_id = owner_id

    @discord.ui.button(
        label="حذف",
        style=discord.ButtonStyle.danger,
        emoji="🗑️"
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                "❌ فقط مالك الشخصية يستطيع حذفها.",
                ephemeral=True
            )

            return

        try:

            try:

                db.delete_character(
                    self.guild_id,
                    self.character_name
                )

            except TypeError:

                db.delete_character(
                    self.character_name
                )

            await interaction.response.edit_message(
                content=(
                    f"🗑️ تم حذف الشخصية "
                    f"**{self.character_name}**."
                ),
                embed=None,
                view=None
            )

        except Exception:

            traceback.print_exc()

            await interaction.response.send_message(
                "❌ تعذر حذف الشخصية.",
                ephemeral=True
            )

    @discord.ui.button(
        label="إلغاء",
        style=discord.ButtonStyle.secondary,
        emoji="❌"
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.edit_message(
            content="❌ تم إلغاء الحذف.",
            embed=None,
            view=None
        )


class CharacterDeleteSelect(
    discord.ui.Select
):

    def __init__(
        self,
        guild_id,
        characters
    ):

        self.guild_id = guild_id

        super().__init__(
            placeholder=(
                "اختر الشخصية التي تريد حذفها..."
            ),
            min_values=1,
            max_values=1,
            options=make_character_options(
                characters
            )
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        character = get_character(
            self.guild_id,
            self.values[0]
        )

        if not character:

            await interaction.response.send_message(
                "❌ الشخصية غير موجودة.",
                ephemeral=True
            )

            return

        data = row_to_dict(
            character
        )

        owner_id = data.get(
            "created_by",
            data.get(
                "owner_id"
            )
        )

        if owner_id != interaction.user.id:

            await interaction.response.send_message(
                "❌ يمكنك حذف الشخصيات التي تملكها فقط.",
                ephemeral=True
            )

            return

        name = data.get(
            "name",
            self.values[0]
        )

        embed = discord.Embed(
            title="⚠️ تأكيد حذف الشخصية",
            description=(
                f"هل أنت متأكد أنك تريد حذف "
                f"**{name}**؟\n\n"
                "هذا الإجراء لا يمكن التراجع عنه."
            ),
            color=discord.Color.red()
        )

        await interaction.response.send_message(
            embed=embed,
            view=CharacterDeleteConfirm(
                self.guild_id,
                name,
                interaction.user.id
            ),
            ephemeral=True
        )


class CharacterDeleteView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id,
        characters
    ):

        super().__init__(
            timeout=120
        )

        if characters:

            self.add_item(
                CharacterDeleteSelect(
                    guild_id,
                    characters
                )
            )


# ============================================================
# DASHBOARD EMBED
# ============================================================

def build_ai_dashboard(
    guild: discord.Guild
):

    config = get_config(
        guild.id
    )

    advanced = get_advanced(
        guild.id
    )

    character = (
        config.get("character")
        or "مساعد السيرفر"
    )

    mode = config.get(
        "mode",
        "normal"
    )

    reply_type = config.get(
        "reply_type",
        "mention"
    )

    channel_id = config.get(
        "channel_id"
    )

    channel_text = (
        f"<#{channel_id}>"
        if channel_id
        else "كل الرومات"
    )

    embed = discord.Embed(
        title="🤖 MyAI • AI Settings",
        description=(
            "لوحة التحكم الكاملة بالذكاء الاصطناعي.\n"
            "يمكن تعديل الإعدادات من الأزرار بالأسفل."
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="AI",
        value=(
            "🟢 مفعل"
            if config.get(
                "enabled",
                True
            )
            else "🔴 متوقف"
        ),
        inline=True
    )

    embed.add_field(
        name="الشخصية",
        value=character,
        inline=True
    )

    embed.add_field(
        name="الوضع",
        value=AI_MODES.get(
            mode,
            {}
        ).get(
            "name",
            mode
        ),
        inline=True
    )

    embed.add_field(
        name="طريقة الرد",
        value=REPLY_TYPES.get(
            reply_type,
            {}
        ).get(
            "name",
            reply_type
        ),
        inline=True
    )

    embed.add_field(
        name="الروم",
        value=channel_text,
        inline=True
    )

    embed.add_field(
        name="Provider",
        value=config.get(
            "provider",
            PRIMARY_AI_PROVIDER
        ),
        inline=True
    )

    embed.add_field(
        name="Model",
        value=config.get(
            "model",
            GOOGLE_MODEL
        ),
        inline=True
    )

    embed.add_field(
        name="الذاكرة",
        value=(
            "🟢 مفعلة"
            if advanced["memory_enabled"]
            else "🔴 متوقفة"
        ),
        inline=True
    )

    embed.add_field(
        name="الأمان",
        value=(
            "🟢 مفعل"
            if advanced["security_enabled"]
            else "🔴 متوقف"
        ),
        inline=True
    )

    embed.add_field(
        name="Bot to Bot",
        value=(
            "🟢 مفعل"
            if advanced["bot_chat_enabled"]
            else "🔴 متوقف"
        ),
        inline=True
    )

    embed.add_field(
        name="History",
        value=str(
            advanced["history_limit"]
        ),
        inline=True
    )

    embed.add_field(
        name="Response Length",
        value=str(
            advanced["response_length"]
        ),
        inline=True
    )

    embed.add_field(
        name="Timeout",
        value=f"{advanced['timeout']}s",
        inline=True
    )

    embed.set_footer(
        text=(
            "MyAI • أعلى 3 رتب فقط تستطيع تعديل لوحة AI"
        )
    )

    return embed


# ============================================================
# SETTINGS MODALS
# ============================================================

class TextSettingsModal(
    discord.ui.Modal,
    title="⚙️ الإعدادات المتقدمة"
):

    history_limit = discord.ui.TextInput(
        label="حد الذاكرة / History",
        placeholder="0 - 100",
        required=False,
        max_length=3
    )

    response_length = discord.ui.TextInput(
        label="طول الرد",
        placeholder="100 - 4000",
        required=False,
        max_length=4
    )

    timeout = discord.ui.TextInput(
        label="مهلة AI بالثواني",
        placeholder="10 - 180",
        required=False,
        max_length=3
    )

    bot_chat_max_chain = discord.ui.TextInput(
        label="أقصى سلسلة Bot-to-Bot",
        placeholder="1 - 50",
        required=False,
        max_length=2
    )

    bot_chat_cooldown = discord.ui.TextInput(
        label="Bot-to-Bot Cooldown",
        placeholder="0 - 60",
        required=False,
        max_length=5
    )

    def __init__(
        self,
        guild_id: int
    ):

        super().__init__()

        self.guild_id = guild_id

        settings = get_advanced(
            guild_id
        )

        self.history_limit.default = str(
            settings["history_limit"]
        )

        self.response_length.default = str(
            settings["response_length"]
        )

        self.timeout.default = str(
            settings["timeout"]
        )

        self.bot_chat_max_chain.default = str(
            settings["bot_chat_max_chain"]
        )

        self.bot_chat_cooldown.default = str(
            settings["bot_chat_cooldown"]
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        settings = get_advanced(
            self.guild_id
        )

        try:

            if self.history_limit.value.strip():

                settings["history_limit"] = max(
                    0,
                    min(
                        100,
                        int(
                            self.history_limit.value
                        )
                    )
                )

            if self.response_length.value.strip():

                settings["response_length"] = max(
                    100,
                    min(
                        4000,
                        int(
                            self.response_length.value
                        )
                    )
                )

            if self.timeout.value.strip():

                settings["timeout"] = max(
                    10,
                    min(
                        180,
                        int(
                            self.timeout.value
                        )
                    )
                )

            if self.bot_chat_max_chain.value.strip():

                settings["bot_chat_max_chain"] = max(
                    1,
                    min(
                        50,
                        int(
                            self.bot_chat_max_chain.value
                        )
                    )
                )

            if self.bot_chat_cooldown.value.strip():

                settings["bot_chat_cooldown"] = max(
                    0,
                    min(
                        60,
                        float(
                            self.bot_chat_cooldown.value
                        )
                    )
                )

        except ValueError:

            await interaction.response.send_message(
                "❌ تأكد أن جميع القيم أرقام صحيحة.",
                ephemeral=True
            )

            return

        if save_advanced(
            self.guild_id,
            settings
        ):

            await interaction.response.send_message(
                "✅ تم حفظ الإعدادات المتقدمة.",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "❌ تعذر حفظ الإعدادات.",
                ephemeral=True
            )


class AllowDenyModal(
    discord.ui.Modal,
    title="🔐 السماح والمنع"
):

    allow_members = discord.ui.TextInput(
        label="Allow Members",
        placeholder="IDs مفصولة بفواصل",
        required=False,
        style=discord.TextStyle.paragraph
    )

    deny_members = discord.ui.TextInput(
        label="Deny Members",
        placeholder="IDs مفصولة بفواصل",
        required=False,
        style=discord.TextStyle.paragraph
    )

    sensitive_keywords = discord.ui.TextInput(
        label="Sensitive Keywords",
        placeholder="كلمات مفصولة بفواصل",
        required=False,
        style=discord.TextStyle.paragraph
    )

    def __init__(
        self,
        guild_id: int
    ):

        super().__init__()

        self.guild_id = guild_id

        settings = get_advanced(
            guild_id
        )

        self.allow_members.default = (
            ", ".join(
                str(x)
                for x in settings[
                    "allow_members"
                ]
            )
        )

        self.deny_members.default = (
            ", ".join(
                str(x)
                for x in settings[
                    "deny_members"
                ]
            )
        )

        self.sensitive_keywords.default = (
            ", ".join(
                str(x)
                for x in settings[
                    "sensitive_keywords"
                ]
            )
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        settings = get_advanced(
            self.guild_id
        )

        settings["allow_members"] = [
            x.strip()
            for x in self.allow_members.value.split(",")
            if x.strip()
        ]

        settings["deny_members"] = [
            x.strip()
            for x in self.deny_members.value.split(",")
            if x.strip()
        ]

        settings["sensitive_keywords"] = [
            x.strip()
            for x in self.sensitive_keywords.value.split(",")
            if x.strip()
        ]

        if save_advanced(
            self.guild_id,
            settings
        ):

            await interaction.response.send_message(
                (
                    "✅ تم تحديث إعدادات السماح "
                    "والمنع والكلمات الحساسة."
                ),
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "❌ تعذر حفظ الإعدادات.",
                ephemeral=True
            )


# ============================================================
# DASHBOARD VIEW
# ============================================================

class AISettingsView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id: int
    ):

        super().__init__(
            timeout=300
        )

        self.guild_id = guild_id

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:

        if not interaction.guild:
            return False

        member = interaction.user

        if not isinstance(
            member,
            discord.Member
        ):
            return False

        if not can_use_ai_dashboard(
            member
        ):

            await interaction.response.send_message(
                "❌ لوحة AI مخصصة لأعلى 3 رتب فقط.",
                ephemeral=True
            )

            return False

        return True

    async def refresh(
        self,
        interaction: discord.Interaction
    ):

        await interaction.response.edit_message(
            embed=build_ai_dashboard(
                interaction.guild
            ),
            view=self
        )

    @discord.ui.button(
        label="AI",
        emoji="🤖",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def ai_toggle(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        config = get_config(
            self.guild_id
        )

        enabled = not config[
            "enabled"
        ]

        update_config(
            self.guild_id,
            enabled=enabled
        )

        await self.refresh(
            interaction
        )

    @discord.ui.button(
        label="Reply",
        emoji="💬",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def reply_settings(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.edit_message(
            content="💬 اختر طريقة الرد:",
            embed=None,
            view=ReplyTypeView(
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Character",
        emoji="🎭",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def character_settings(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        characters = get_all_characters(
            self.guild_id
        )

        if not characters:

            await interaction.response.send_message(
                "❌ لا توجد شخصيات.",
                ephemeral=True
            )

            return

        await interaction.response.edit_message(
            content="🎭 اختر الشخصية:",
            embed=None,
            view=CharacterDashboardView(
                self.guild_id,
                characters
            )
        )

    @discord.ui.button(
        label="Mode",
        emoji="🧠",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def mode_settings(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.edit_message(
            content="🧠 اختر وضع AI:",
            embed=None,
            view=ModeView(
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Memory",
        emoji="🧠",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def memory_toggle(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        settings = get_advanced(
            self.guild_id
        )

        settings["memory_enabled"] = not (
            settings["memory_enabled"]
        )

        save_advanced(
            self.guild_id,
            settings
        )

        await self.refresh(
            interaction
        )

    @discord.ui.button(
        label="Advanced",
        emoji="⚙️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def advanced(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_modal(
            TextSettingsModal(
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Security",
        emoji="🛡️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def security(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        settings = get_advanced(
            self.guild_id
        )

        settings["security_enabled"] = not (
            settings["security_enabled"]
        )

        save_advanced(
            self.guild_id,
            settings
        )

        await self.refresh(
            interaction
        )

    @discord.ui.button(
        label="Bot Chat",
        emoji="🤖",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def bot_chat(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        settings = get_advanced(
            self.guild_id
        )

        settings["bot_chat_enabled"] = not (
            settings["bot_chat_enabled"]
        )

        save_advanced(
            self.guild_id,
            settings
        )

        await self.refresh(
            interaction
        )

    @discord.ui.button(
        label="Allow / Deny",
        emoji="🔐",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def allow_deny(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_modal(
            AllowDenyModal(
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Channel",
        emoji="📢",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def channel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.edit_message(
            content="📢 اختر الروم:",
            embed=None,
            view=ChannelView(
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Clear Memory",
        emoji="🧹",
        style=discord.ButtonStyle.danger,
        row=2
    )
    async def clear_memory(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        try:

            db.clear_memory(
                self.guild_id
            )

            await interaction.response.send_message(
                "🧹 تم مسح ذاكرة AI.",
                ephemeral=True
            )

        except Exception:

            traceback.print_exc()

            await interaction.response.send_message(
                "❌ تعذر مسح الذاكرة.",
                ephemeral=True
            )

    @discord.ui.button(
        label="Reset Advanced",
        emoji="♻️",
        style=discord.ButtonStyle.danger,
        row=3
    )
    async def reset(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        reset_advanced(
            self.guild_id
        )

        await self.refresh(
            interaction
        )

    @discord.ui.button(
        label="Refresh",
        emoji="🔄",
        style=discord.ButtonStyle.success,
        row=3
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await self.refresh(
            interaction
        )


# ============================================================
# REPLY TYPE VIEW
# ============================================================

class ReplyTypeSelect(
    discord.ui.Select
):

    def __init__(
        self,
        guild_id: int
    ):

        self.guild_id = guild_id

        options = []

        for key, data in REPLY_TYPES.items():

            options.append(
                discord.SelectOption(
                    label=data["name"],
                    description=data["description"],
                    value=key
                )
            )

        super().__init__(
            placeholder="اختر طريقة الرد...",
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        value = self.values[0]

        try:

            update_config(
                self.guild_id,
                reply_type=value
            )

            await interaction.response.edit_message(
                content="✅ تم تحديث طريقة الرد.",
                embed=build_ai_dashboard(
                    interaction.guild
                ),
                view=AISettingsView(
                    self.guild_id
                )
            )

        except Exception:

            traceback.print_exc()

            await interaction.response.send_message(
                "❌ تعذر تحديث طريقة الرد.",
                ephemeral=True
            )


class ReplyTypeView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id: int
    ):

        super().__init__(
            timeout=120
        )

        self.guild_id = guild_id

        self.add_item(
            ReplyTypeSelect(
                guild_id
            )
        )

    @discord.ui.button(
        label="رجوع",
        emoji="↩️",
        style=discord.ButtonStyle.secondary
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.edit_message(
            content=None,
            embed=build_ai_dashboard(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            )
        )


# ============================================================
# MODE VIEW
# ============================================================

class ModeSelect(
    discord.ui.Select
):

    def __init__(
        self,
        guild_id: int
    ):

        self.guild_id = guild_id

        options = []

        for key, data in AI_MODES.items():

            options.append(
                discord.SelectOption(
                    label=data["name"],
                    description=data["description"],
                    value=key
                )
            )

        super().__init__(
            placeholder="اختر وضع AI...",
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        value = self.values[0]

        try:

            update_config(
                self.guild_id,
                mode=value
            )

            await interaction.response.edit_message(
                content=None,
                embed=build_ai_dashboard(
                    interaction.guild
                ),
                view=AISettingsView(
                    self.guild_id
                )
            )

        except Exception:

            traceback.print_exc()

            await interaction.response.send_message(
                "❌ تعذر تحديث الوضع.",
                ephemeral=True
            )


class ModeView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id: int
    ):

        super().__init__(
            timeout=120
        )

        self.guild_id = guild_id

        self.add_item(
            ModeSelect(
                guild_id
            )
        )

    @discord.ui.button(
        label="رجوع",
        emoji="↩️",
        style=discord.ButtonStyle.secondary
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.edit_message(
            content=None,
            embed=build_ai_dashboard(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            )
        )


# ============================================================
# CHARACTER DASHBOARD
# ============================================================

class CharacterDashboardSelect(
    discord.ui.Select
):

    def __init__(
        self,
        guild_id: int,
        characters
    ):

        self.guild_id = guild_id

        super().__init__(
            placeholder="اختر الشخصية...",
            options=make_character_options(
                characters
            )
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        name = self.values[0]

        try:

            update_config(
                self.guild_id,
                character=name
            )

            await interaction.response.edit_message(
                content=None,
                embed=build_ai_dashboard(
                    interaction.guild
                ),
                view=AISettingsView(
                    self.guild_id
                )
            )

        except Exception:

            traceback.print_exc()

            await interaction.response.send_message(
                "❌ تعذر تفعيل الشخصية.",
                ephemeral=True
            )


class CharacterDashboardView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id: int,
        characters
    ):

        super().__init__(
            timeout=120
        )

        self.guild_id = guild_id

        self.add_item(
            CharacterDashboardSelect(
                guild_id,
                characters
            )
        )

    @discord.ui.button(
        label="رجوع",
        emoji="↩️",
        style=discord.ButtonStyle.secondary
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.edit_message(
            content=None,
            embed=build_ai_dashboard(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            )
        )


# ============================================================
# CHANNEL VIEW
# ============================================================

class ChannelSelect(
    discord.ui.ChannelSelect
):

    def __init__(
        self,
        guild_id: int
    ):

        self.guild_id = guild_id

        super().__init__(
            placeholder="اختر روم AI...",
            channel_types=[
                discord.ChannelType.text
            ],
            min_values=1,
            max_values=1
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        channel = self.values[0]

        try:

            update_config(
                self.guild_id,
                channel_id=channel.id
            )

            await interaction.response.edit_message(
                content=None,
                embed=build_ai_dashboard(
                    interaction.guild
                ),
                view=AISettingsView(
                    self.guild_id
                )
            )

        except Exception:

            traceback.print_exc()

            await interaction.response.send_message(
                "❌ تعذر تحديث الروم.",
                ephemeral=True
            )


class ChannelView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id: int
    ):

        super().__init__(
            timeout=120
        )

        self.guild_id = guild_id

        self.add_item(
            ChannelSelect(
                guild_id
            )
        )

    @discord.ui.button(
        label="رجوع",
        emoji="↩️",
        style=discord.ButtonStyle.secondary
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.edit_message(
            content=None,
            embed=build_ai_dashboard(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            )
        )


# ============================================================
# SLASH COMMANDS
# ============================================================

@bot.tree.command(
    name="ai",
    description="تشغيل أو إيقاف AI"
)
async def ai_command(
    interaction: discord.Interaction
):

    if not interaction.guild:
        return

    member = interaction.user

    if (
        not isinstance(
            member,
            discord.Member
        )
        or not has_broad_management(member)
    ):

        await interaction.response.send_message(
            "❌ تحتاج صلاحيات إدارة السيرفر.",
            ephemeral=True
        )

        return

    config = get_config(
        interaction.guild.id
    )

    enabled = not config[
        "enabled"
    ]

    update_config(
        interaction.guild.id,
        enabled=enabled
    )

    await interaction.response.send_message(
        (
            "🟢 تم تشغيل AI."
            if enabled
            else "🔴 تم إيقاف AI."
        )
    )


# ============================================================
# AI SETUP
# ============================================================

@bot.tree.command(
    name="ai_setup",
    description="إعداد روم AI"
)
async def ai_setup(
    interaction: discord.Interaction
):

    if not interaction.guild:
        return

    member = interaction.user

    if (
        not isinstance(
            member,
            discord.Member
        )
        or not has_broad_management(member)
    ):

        await interaction.response.send_message(
            "❌ تحتاج صلاحيات إدارة السيرفر.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        "📢 اختر روم AI:",
        view=ChannelView(
            interaction.guild.id
        ),
        ephemeral=True
    )


# ============================================================
# AI SETTINGS
# ============================================================

@bot.tree.command(
    name="ai_settings",
    description="فتح لوحة إعدادات AI"
)
async def ai_settings(
    interaction: discord.Interaction
):

    if not interaction.guild:
        return

    member = interaction.user

    if (
        not isinstance(
            member,
            discord.Member
        )
        or not can_use_ai_dashboard(member)
    ):

        await interaction.response.send_message(
            (
                "❌ هذه اللوحة متاحة فقط "
                "لأعلى 3 رتب في السيرفر."
            ),
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        embed=build_ai_dashboard(
            interaction.guild
        ),
        view=AISettingsView(
            interaction.guild.id
        ),
        ephemeral=True
    )


# ============================================================
# AI CONFIG
# ============================================================

@bot.tree.command(
    name="ai_config",
    description="عرض إعدادات AI"
)
async def ai_config(
    interaction: discord.Interaction
):

    if not interaction.guild:
        return

    member = interaction.user

    if (
        not isinstance(
            member,
            discord.Member
        )
        or not can_use_ai_dashboard(member)
    ):

        await interaction.response.send_message(
            "❌ هذا الأمر متاح فقط لأعلى 3 رتب.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        embed=build_ai_dashboard(
            interaction.guild
        ),
        ephemeral=True
    )


# ============================================================
# CHARACTER CREATE
# ============================================================

@bot.tree.command(
    name="character_create",
    description="إنشاء شخصية AI"
)
@app_commands.describe(
    name="اسم الشخصية",
    character_type="نوع الشخصية"
)
async def character_create(
    interaction: discord.Interaction,
    name: str,
    character_type: str
):

    if not interaction.guild:
        return

    name = name.strip()

    if not 2 <= len(name) <= 80:

        await interaction.response.send_message(
            "❌ اسم الشخصية يجب أن يكون بين 2 و80 حرفًا.",
            ephemeral=True
        )

        return

    if character_type not in CHARACTER_TYPES:

        await interaction.response.send_message(
            "❌ نوع الشخصية غير صحيح.",
            ephemeral=True
        )

        return

    try:

        try:

            db.create_character(
                guild_id=interaction.guild.id,
                name=name,
                character_type=character_type,
                created_by=interaction.user.id,
                provider="google",
                model=GOOGLE_MODEL
            )

        except TypeError:

            db.create_character(
                interaction.guild.id,
                name,
                character_type=character_type,
                created_by=interaction.user.id,
                provider="google",
                model=GOOGLE_MODEL
            )

        await interaction.response.send_message(
            f"✅ تم إنشاء الشخصية **{name}**.",
            ephemeral=True
        )

    except Exception:

        traceback.print_exc()

        await interaction.response.send_message(
            (
                "❌ تعذر إنشاء الشخصية. "
                "ربما الاسم مستخدم مسبقًا."
            ),
            ephemeral=True
        )


# ============================================================
# CHARACTER INFO
# ============================================================

@bot.tree.command(
    name="character_info",
    description="عرض معلومات شخصية"
)
async def character_info(
    interaction: discord.Interaction
):

    if not interaction.guild:
        return

    characters = get_all_characters(
        interaction.guild.id
    )

    if not characters:

        await interaction.response.send_message(
            "❌ لا توجد شخصيات في هذا السيرفر.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        "🎭 اختر الشخصية:",
        view=CharacterInfoView(
            interaction.guild.id,
            characters
        ),
        ephemeral=True
    )


# ============================================================
# CHARACTER USE
# ============================================================

@bot.tree.command(
    name="character_use",
    description="تفعيل شخصية للسيرفر"
)
async def character_use(
    interaction: discord.Interaction
):

    if not interaction.guild:
        return

    member = interaction.user

    if (
        not isinstance(
            member,
            discord.Member
        )
        or not has_broad_management(member)
    ):

        await interaction.response.send_message(
            "❌ تحتاج صلاحيات إدارة السيرفر.",
            ephemeral=True
        )

        return

    characters = get_all_characters(
        interaction.guild.id
    )

    if not characters:

        await interaction.response.send_message(
            "❌ لا توجد شخصيات.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        "🎭 اختر الشخصية التي تريد تفعيلها:",
        view=CharacterUseView(
            interaction.guild.id,
            characters
        ),
        ephemeral=True
    )


# ============================================================
# CHARACTER EDIT
# ============================================================

@bot.tree.command(
    name="character_edit",
    description="تعديل شخصيتك"
)
async def character_edit(
    interaction: discord.Interaction
):

    if not interaction.guild:
        return

    characters = get_user_characters(
        interaction.guild.id,
        interaction.user.id
    )

    if not characters:

        await interaction.response.send_message(
            "❌ لا تملك أي شخصيات.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        "🎭 اختر الشخصية التي تريد تعديلها:",
        view=CharacterEditView(
            interaction.guild.id,
            characters
        ),
        ephemeral=True
    )


# ============================================================
# CHARACTER DELETE
# ============================================================

@bot.tree.command(
    name="character_delete",
    description="حذف شخصيتك"
)
async def character_delete(
    interaction: discord.Interaction
):

    if not interaction.guild:
        return

    characters = get_user_characters(
        interaction.guild.id,
        interaction.user.id
    )

    if not characters:

        await interaction.response.send_message(
            "❌ لا تملك أي شخصيات.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        "🗑️ اختر الشخصية:",
        view=CharacterDeleteView(
            interaction.guild.id,
            characters
        ),
        ephemeral=True
    )


# ============================================================
# CHARACTER LIST
# ============================================================

@bot.tree.command(
    name="character_list",
    description="عرض شخصيات السيرفر"
)
async def character_list(
    interaction: discord.Interaction
):

    if not interaction.guild:
        return

    characters = get_all_characters(
        interaction.guild.id
    )

    if not characters:

        await interaction.response.send_message(
            "❌ لا توجد شخصيات.",
            ephemeral=True
        )

        return

    lines = [
        "🎭 **شخصيات السيرفر:**",
        ""
    ]

    for character in characters:

        data = row_to_dict(
            character
        )

        name = data.get(
            "name",
            "بدون اسم"
        )

        char_type = data.get(
            "character_type",
            data.get(
                "type",
                "normal"
            )
        )

        lines.append(
            f"• **{name}** — "
            f"{CHARACTER_TYPES.get(char_type, char_type)}"
        )

    text = "\n".join(
        lines
    )

    if len(text) > 1900:
        text = text[:1890] + "\n..."

    await interaction.response.send_message(
        text,
        ephemeral=True
    )


# ============================================================
# AI STATUS
# ============================================================

@bot.tree.command(
    name="ai_status",
    description="عرض حالة AI"
)
async def ai_status(
    interaction: discord.Interaction
):

    if not interaction.guild:
        return

    config = get_config(
        interaction.guild.id
    )

    advanced = get_advanced(
        interaction.guild.id
    )

    embed = discord.Embed(
        title="🤖 MyAI Status",
        color=(
            discord.Color.green()
            if config["enabled"]
            else discord.Color.red()
        )
    )

    embed.add_field(
        name="AI",
        value=(
            "🟢 Online"
            if config["enabled"]
            else "🔴 Disabled"
        ),
        inline=True
    )

    embed.add_field(
        name="Provider",
        value=config["provider"],
        inline=True
    )

    embed.add_field(
        name="Model",
        value=config["model"],
        inline=True
    )

    embed.add_field(
        name="Memory",
        value=(
            "ON"
            if advanced["memory_enabled"]
            else "OFF"
        ),
        inline=True
    )

    embed.add_field(
        name="Bot Chat",
        value=(
            "ON"
            if advanced["bot_chat_enabled"]
            else "OFF"
        ),
        inline=True
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ============================================================
# MEMORY CLEAR
# ============================================================

@bot.tree.command(
    name="ai_memory_clear",
    description="مسح ذاكرة AI"
)
async def ai_memory_clear(
    interaction: discord.Interaction
):

    if not interaction.guild:
        return

    member = interaction.user

    if (
        not isinstance(
            member,
            discord.Member
        )
        or not has_broad_management(member)
    ):

        await interaction.response.send_message(
            "❌ تحتاج صلاحيات إدارة السيرفر.",
            ephemeral=True
        )

        return

    try:

        db.clear_memory(
            interaction.guild.id
        )

        await interaction.response.send_message(
            "🧹 تم مسح ذاكرة AI.",
            ephemeral=True
        )

    except Exception:

        traceback.print_exc()

        await interaction.response.send_message(
            "❌ تعذر مسح الذاكرة.",
            ephemeral=True
        )


# ============================================================
# AI DM
# ============================================================

@bot.tree.command(
    name="ai_dm",
    description="تشغيل أو إيقاف AI في الخاص"
)
async def ai_dm(
    interaction: discord.Interaction
):

    try:

        current = db.get_dm_enabled(
            interaction.user.id
        )

        new_value = not bool(
            current
        )

        db.set_dm_enabled(
            interaction.user.id,
            new_value
        )

        await interaction.response.send_message(
            (
                "🟢 تم تشغيل AI في الخاص."
                if new_value
                else "🔴 تم إيقاف AI في الخاص."
            ),
            ephemeral=True
        )

    except Exception:

        traceback.print_exc()

        await interaction.response.send_message(
            "❌ تعذر تحديث إعداد الخاص.",
            ephemeral=True
        )


# ============================================================
# ON MESSAGE
# ============================================================

@bot.event
async def on_message(
    message: discord.Message
):

    # --------------------------------------------------------
    # LOG MESSAGE
    # --------------------------------------------------------

    try:

        if message.guild:

            config = get_config(
                message.guild.id
            )

            save_database_message(
                message,
                config.get(
                    "character"
                )
            )

    except Exception:

        traceback.print_exc()

    # --------------------------------------------------------
    # IGNORE SELF
    # --------------------------------------------------------

    if (
        bot.user
        and message.author.id
        == bot.user.id
    ):
        return

    # --------------------------------------------------------
    # DIRECT MESSAGES
    # --------------------------------------------------------

    if message.guild is None:

        if message.author.bot:

            await bot.process_commands(
                message
            )

            return

        try:

            dm_enabled = (
                db.get_dm_enabled(
                    message.author.id
                )
            )

            if not dm_enabled:

                await bot.process_commands(
                    message
                )

                return

        except Exception:

            await bot.process_commands(
                message
            )

            return

        try:

            async with message.channel.typing():

                response = await asyncio.wait_for(
                    generate_dm_reply(
                        message.author.id,
                        message.content
                    ),
                    timeout=DEFAULT_AI_TIMEOUT
                )

            if response:

                await send_ai_response(
                    message,
                    response
                )

        except asyncio.TimeoutError:

            await message.channel.send(
                "⏱️ انتهى وقت معالجة الطلب."
            )

        except Exception:

            traceback.print_exc()

            await message.channel.send(
                "❌ حدث خطأ أثناء معالجة الرسالة."
            )

        await bot.process_commands(
            message
        )

        return

    # --------------------------------------------------------
    # GUILD CONFIG
    # --------------------------------------------------------

    config = get_config(
        message.guild.id
    )

    advanced = get_advanced(
        message.guild.id
    )

    if not config["enabled"]:

        await bot.process_commands(
            message
        )

        return

    if not channel_matches(
        message,
        config["channel_id"]
    ):

        await bot.process_commands(
            message
        )

        return

    # --------------------------------------------------------
    # MEMBER FILTER
    # --------------------------------------------------------

    if not message.author.bot:

        if not member_allowed(
            message.author.id,
            advanced
        ):

            await bot.process_commands(
                message
            )

            return

    # --------------------------------------------------------
    # BOT MESSAGE
    # --------------------------------------------------------

    if message.author.bot:

        if not should_process_bot_chat(
            message,
            config,
            advanced
        ):

            await bot.process_commands(
                message
            )

            return

        if config["reply_type"] != "bot_chat":

            await bot.process_commands(
                message
            )

            return

    # --------------------------------------------------------
    # HUMAN MESSAGE
    # --------------------------------------------------------

    else:

        reset_bot_chain(
            message.guild.id
        )

        if contains_sensitive_content(
            message.content,
            advanced
        ):

            await message.channel.send(
                "🛡️ لا أستطيع معالجة هذه الرسالة."
            )

            await bot.process_commands(
                message
            )

            return

    # --------------------------------------------------------
    # REPLY MODE
    # --------------------------------------------------------

    reply_type = config.get(
        "reply_type",
        "mention"
    )

    if not message.author.bot:

        if reply_type in (
            "mention",
            "direct"
        ):

            if not is_directed_to_bot(
                message
            ):

                await bot.process_commands(
                    message
                )

                return

        elif reply_type in (
            "channel",
            "auto"
        ):

            pass

        elif reply_type == "bot_chat":

            await bot.process_commands(
                message
            )

            return

    # --------------------------------------------------------
    # BOT LOCK
    # --------------------------------------------------------

    bot_lock = None

    if message.author.bot:

        bot_lock = get_bot_lock(
            message.guild.id
        )

        if bot_lock.locked():

            await bot.process_commands(
                message
            )

            return

    request_key = get_request_key(
        message
    )

    if request_key in ACTIVE_REQUESTS:

        await bot.process_commands(
            message
        )

        return

    # --------------------------------------------------------
    # BOT CHAT
    # --------------------------------------------------------

    if message.author.bot:

        async with bot_lock:

            chain = increment_bot_chain(
                message.guild.id
            )

            max_chain = advanced.get(
                "bot_chat_max_chain",
                DEFAULT_MAX_BOT_CHAIN
            )

            if chain > max_chain:

                reset_bot_chain(
                    message.guild.id
                )

                await bot.process_commands(
                    message
                )

                return

            response = await generate_chat_reply(
                message,
                message.content
            )

            if response:

                await send_ai_response(
                    message,
                    response
                )

                BOT_CHAT_LAST_RESPONSE[
                    message.guild.id
                ] = time.monotonic()

    # --------------------------------------------------------
    # HUMAN CHAT
    # --------------------------------------------------------

    else:

        await generate_with_typing_message(
            message,
            message.content
        )

    # --------------------------------------------------------
    # COMMANDS
    # --------------------------------------------------------

    await bot.process_commands(
        message
    )


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():

    print("=" * 60)
    print("MyAI BOT — ONLINE")
    print("=" * 60)

    print(
        f"Bot: {bot.user}"
    )

    print(
        f"Provider: {PRIMARY_AI_PROVIDER}"
    )

    print(
        f"Model: {GOOGLE_MODEL}"
    )

    print(
        f"Servers: {len(bot.guilds)}"
    )

    print("=" * 60)


# ============================================================
# APP COMMAND ERROR
# ============================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):

    traceback.print_exc()

    message = (
        "❌ حدث خطأ أثناء تنفيذ الأمر."
    )

    if interaction.response.is_done():

        await interaction.followup.send(
            message,
            ephemeral=True
        )

    else:

        await interaction.response.send_message(
            message,
            ephemeral=True
        )


# ============================================================
# SETUP HOOK
# ============================================================

@bot.event
async def setup_hook():

    try:

        synced = await bot.tree.sync()

        print(
            f"[commands] synced {len(synced)} commands"
        )

    except Exception:

        traceback.print_exc()


# ============================================================
# START BOT
# ============================================================

if not TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN is not configured."
    )


bot.run(TOKEN)
