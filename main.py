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
    يحول SQLite Row إلى dict.
    """

    if row is None:
        return None

    try:
        return dict(row)

    except Exception:
        return {
            key: row[key]
            for key in row.keys()
        }


def get_config(guild_id: int):
    """
    جلب إعدادات السيرفر الأساسية.
    """

    try:
        config = db.get_guild_config(
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
                True
            )
        ),
        "channel_id": data.get(
            "channel_id"
        ),
        "mode": (
            data.get("mode")
            or "normal"
        ),
        "reply_type": (
            data.get("reply_type")
            or "mention"
        ),
        "character": data.get(
            "character"
        ),
        "provider": (
            data.get("provider")
            or PRIMARY_AI_PROVIDER
        ),
        "model": (
            data.get("model")
            or GOOGLE_MODEL
        ),
    }


def get_advanced(guild_id: int):
    """
    جلب الإعدادات المتقدمة مع القيم الافتراضية.
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
        "sensitive_keywords":
            DEFAULT_SENSITIVE_KEYWORDS.copy(),
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
    جلب شخصية بالاسم من نفس السيرفر.
    """

    if not character_name:
        return None

    try:
        return db.get_character(
            guild_id,
            character_name
        )

    except Exception:
        traceback.print_exc()
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
    تقسيم الردود الطويلة إلى أجزاء مناسبة لديسكورد.
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
    تحويل channel_id إلى int بشكل آمن.
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
    التحقق أن الرسالة في الروم المحدد.
    """

    channel_id = normalize_channel_id(
        channel_id
    )

    if channel_id is None:
        return True

    return (
        message.channel.id
        == channel_id
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
    أعلى 3 رتب فعلية في السيرفر.
    """

    roles = [
        role
        for role in guild.roles
        if (
            not role.is_default()
            and not role.managed
        )
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
    فقط أصحاب أعلى 3 رتب يستطيعون
    استخدام لوحة AI.
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
    فحص صلاحية الإدارة/الأمان.
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
        (
            message.guild.id
            if message.guild
            else 0
        ),
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

    return BOT_CHAT_LOCKS[
        guild_id
    ]


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
    BOT_CHAT_CHAINS[
        guild_id
    ] = 0


def increment_bot_chain(
    guild_id: int
) -> int:

    value = BOT_CHAT_CHAINS.get(
        guild_id,
        0
    )

    value += 1

    BOT_CHAT_CHAINS[
        guild_id
    ] = value

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


# ============================================================
# BOT CHAT
# ============================================================

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
