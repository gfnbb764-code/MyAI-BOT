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

PRIMARY_AI_PROVIDER = os.getenv("PRIMARY_AI_PROVIDER", "google").lower()
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
        "description": "ردود طبيعية ومتوازنة",
    },
    "friendly": {
        "name": "ودود",
        "description": "ردود لطيفة واجتماعية",
    },
    "active": {
        "name": "نشط",
        "description": "تفاعل أكثر وحيوية أعلى",
    },
    "fun": {
        "name": "مرح",
        "description": "أسلوب مرح وخفيف",
    },
    "professional": {
        "name": "احترافي",
        "description": "أسلوب رسمي ومنظم",
    },
}


# ============================================================
# REPLY TYPES
# ============================================================

REPLY_TYPES = {
    "mention": "عند المنشن فقط",
    "channel": "الرد داخل الروم",
    "direct": "الرد عند توجيه الكلام للبوت",
    "auto": "الرد تلقائيًا",
    "bot_chat": "التحدث مع البوتات",
}


# ============================================================
# CHARACTER TYPES
# ============================================================

CHARACTER_TYPES = {
    "normal": "عادي",
    "calm": "هادئ",
    "smart": "ذكي",
    "funny": "مرح",
    "friendly": "ودود",
    "formal": "رسمي",
    "energetic": "حماسي",
    "rude": "غير مهذب",
    "mischievous": "مشاغب",
    "curious": "فضولي",
    "creative": "إبداعي",
    "professional": "احترافي",
}


# ============================================================
# SENSITIVE KEYWORDS
# ============================================================

DEFAULT_SENSITIVE_KEYWORDS = [
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
]


# ============================================================
# BOT CHAT
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
intents.presences = True
intents.messages = True
intents.message_content = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)


# ============================================================
# DATABASE / AI
# ============================================================

db = Database()
ai = AIEngine(db)


# ============================================================
# PERFORMANCE
# ============================================================

AI_SEMAPHORE = asyncio.Semaphore(MAX_ACTIVE_REQUESTS)
ACTIVE_REQUESTS = set()


# ============================================================
# HELPERS
# ============================================================

def row_to_dict(row):
    if row is None:
        return None

    if isinstance(row, dict):
        return dict(row)

    try:
        return dict(row)
    except Exception:
        return None


def get_config(guild_id: int):
    try:
        config = db.get_ai_config(guild_id)

        if not config:
            return {
                "enabled": True,
                "channel_id": None,
                "mode": "normal",
                "reply_type": "mention",
                "character_name": None,
                "provider": PRIMARY_AI_PROVIDER,
                "model": GOOGLE_MODEL,
            }

        return row_to_dict(config) or {}
    except Exception:
        return {}


def get_advanced(guild_id: int):
    """
    Reads advanced AI settings.

    Expected database method:
        db.get_ai_advanced_settings(guild_id)
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
        "sensitive_keywords": DEFAULT_SENSITIVE_KEYWORDS.copy(),
    }

    try:
        settings = db.get_ai_advanced_settings(guild_id)

        if not settings:
            return defaults

        settings = row_to_dict(settings) or {}

        result = defaults.copy()
        result.update(settings)

        for key in (
            "allow_members",
            "deny_members",
            "sensitive_keywords",
        ):
            value = result.get(key)

            if isinstance(value, str):
                try:
                    result[key] = json.loads(value)
                except Exception:
                    result[key] = [
                        x.strip()
                        for x in value.split(",")
                        if x.strip()
                    ]

            if result[key] is None:
                result[key] = []

        return result

    except AttributeError:
        return defaults

    except Exception:
        return defaults


def save_advanced(guild_id: int, **kwargs):
    try:
        return db.save_ai_advanced_settings(
            guild_id,
            **kwargs,
        )
    except AttributeError:
        return False
    except Exception:
        traceback.print_exc()
        return False


def reset_advanced(guild_id: int):
    try:
        return db.reset_ai_advanced_settings(guild_id)
    except AttributeError:
        return False
    except Exception:
        traceback.print_exc()
        return False


def get_character(guild_id: int, name: str):
    if not name:
        return None

    try:
        return db.get_character(
            guild_id,
            name,
        )
    except Exception:
        return None


def get_active_character(guild_id: int):
    config = get_config(guild_id)

    name = (
        config.get("character_name")
        or config.get("active_character")
    )

    if name:
        return get_character(
            guild_id,
            name,
        )

    try:
        return db.get_active_character(guild_id)
    except Exception:
        return None


def normalize_text(text: str):
    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        text.strip(),
    )


def clean_mentions(text: str):
    if not text:
        return ""

    text = re.sub(
        r"<@!?\d+>",
        "",
        text,
    )

    text = re.sub(
        r"<@&\d+>",
        "",
        text,
    )

    text = re.sub(
        r"<#\d+>",
        "",
        text,
    )

    return normalize_text(text)


def split_message(text: str, limit: int = 1900):
    if not text:
        return []

    if len(text) <= limit:
        return [text]

    chunks = []

    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)

        if cut < 500:
            cut = text.rfind(" ", 0, limit)

        if cut < 1:
            cut = limit

        chunks.append(text[:cut])
        text = text[cut:].lstrip()

    if text:
        chunks.append(text)

    return chunks


def normalize_channel_id(value):
    if value is None:
        return None

    try:
        return int(value)
    except Exception:
        return None


def channel_matches(message, config):
    configured = (
        config.get("channel_id")
        or config.get("ai_channel_id")
    )

    configured = normalize_channel_id(configured)

    if configured is None:
        return True

    return message.channel.id == configured


def is_directed_to_bot(message):
    if not message.guild:
        return False

    if bot.user is None:
        return False

    if bot.user in message.mentions:
        return True

    text = message.content.lower().strip()

    names = [
        bot.user.name.lower(),
        bot.user.display_name.lower(),
    ]

    return any(
        text.startswith(name)
        for name in names
    )


# ============================================================
# PERMISSIONS
# ============================================================

def has_management_permission(member: discord.Member):
    if not member:
        return False

    if member.guild.owner_id == member.id:
        return True

    permissions = member.guild_permissions

    return any([
        permissions.administrator,
        permissions.manage_guild,
        permissions.manage_channels,
        permissions.manage_roles,
    ])


def get_top_three_roles(guild: discord.Guild):
    roles = [
        role
        for role in guild.roles
        if role != guild.default_role
        and not role.managed
    ]

    roles.sort(
        key=lambda role: role.position,
        reverse=True,
    )

    return roles[:3]


def is_top_three_role(member: discord.Member):
    if not member or not member.guild:
        return False

    top_three = get_top_three_roles(
        member.guild
    )

    top_ids = {
        role.id
        for role in top_three
    }

    return any(
        role.id in top_ids
        for role in member.roles
    )


def can_manage_ai(member: discord.Member):
    return (
        has_management_permission(member)
    )


def can_use_ai_dashboard(member: discord.Member):
    """
    Dashboard = STRICTLY top 3 roles.

    Server owner does NOT bypass this rule.
    """

    if not member:
        return False

    return is_top_three_role(member)


def security_check(member: discord.Member):
    return (
        is_top_three_role(member)
        or has_management_permission(member)
    )


# ============================================================
# MEMBER FILTERS
# ============================================================

def member_is_allowed(
    member: discord.Member,
    settings: dict,
):
    allow = settings.get(
        "allow_members",
        [],
    )

    deny = settings.get(
        "deny_members",
        [],
    )

    try:
        allow = {
            int(x)
            for x in allow
        }
    except Exception:
        allow = set()

    try:
        deny = {
            int(x)
            for x in deny
        }
    except Exception:
        deny = set()

    if member.id in deny:
        return False

    if allow:
        return member.id in allow

    return True


# ============================================================
# SENSITIVE CHECK
# ============================================================

def contains_sensitive_request(
    text: str,
    settings: dict,
):
    if not settings.get(
        "security_enabled",
        True,
    ):
        return False

    keywords = settings.get(
        "sensitive_keywords",
        DEFAULT_SENSITIVE_KEYWORDS,
    )

    text = text.lower()

    for keyword in keywords:
        keyword = str(keyword).strip().lower()

        if keyword and keyword in text:
            return True

    return False


# ============================================================
# REQUEST MANAGEMENT
# ============================================================

def get_request_key(
    guild_id,
    user_id,
    channel_id,
):
    return (
        guild_id,
        user_id,
        channel_id,
    )


# ============================================================
# BOT CHAT PROTECTION
# ============================================================

def get_bot_lock(guild_id):
    if guild_id not in BOT_CHAT_LOCKS:
        BOT_CHAT_LOCKS[guild_id] = asyncio.Lock()

    return BOT_CHAT_LOCKS[guild_id]


def get_bot_chain(guild_id):
    return BOT_CHAT_CHAINS.get(
        guild_id,
        0,
    )


def reset_bot_chain(guild_id):
    BOT_CHAT_CHAINS[guild_id] = 0


def increment_bot_chain(guild_id):
    BOT_CHAT_CHAINS[guild_id] = (
        get_bot_chain(guild_id) + 1
    )

    return BOT_CHAT_CHAINS[guild_id]


def bot_chat_on_cooldown(
    guild_id,
    cooldown,
):
    last = BOT_CHAT_LAST_RESPONSE.get(
        guild_id
    )

    if last is None:
        return False

    return (
        time.monotonic() - last
        < cooldown
    )


def update_bot_chat_time(guild_id):
    BOT_CHAT_LAST_RESPONSE[
        guild_id
    ] = time.monotonic()


# ============================================================
# AI GENERATION
# ============================================================

async def generate_chat_reply(
    message: discord.Message,
    config: dict,
    advanced: dict,
):
    guild_id = message.guild.id

    character_name = (
        config.get("character_name")
        or config.get("active_character")
    )

    character = None

    if character_name:
        character = get_character(
            guild_id,
            character_name,
        )

    mode = (
        config.get("mode")
        or config.get("ai_mode")
        or "normal"
    )

    provider = (
        config.get("provider")
        or config.get("active_provider")
        or PRIMARY_AI_PROVIDER
    )

    model = (
        config.get("model")
        or config.get("active_model")
        or GOOGLE_MODEL
    )

    prompt = clean_mentions(
        message.content
    )

    if not prompt:
        prompt = "ابدأ التفاعل مع المستخدم بشكل طبيعي."

    history_limit = int(
        advanced.get(
            "history_limit",
            20,
        )
    )

    response_length = int(
        advanced.get(
            "response_length",
            1200,
        )
    )

    memory_enabled = bool(
        advanced.get(
            "memory_enabled",
            True,
        )
    )

    async with AI_SEMAPHORE:
        if memory_enabled:
            try:
                return await ai.generate(
                    guild_id=guild_id,
                    channel_id=message.channel.id,
                    user_id=message.author.id,
                    character_name=(
                        character_name
                        or "مساعد السيرفر جيميناي"
                    ),
                    prompt=prompt,
                    mode=mode,
                    provider=provider,
                    model=model,
                    history_limit=history_limit,
                    max_tokens_override=response_length,
                )
            except TypeError:
                return await ai.generate(
                    guild_id=guild_id,
                    channel_id=message.channel.id,
                    user_id=message.author.id,
                    character_name=(
                        character_name
                        or "مساعد السيرفر جيميناي"
                    ),
                    prompt=prompt,
                    mode=mode,
                    provider=provider,
                    model=model,
                )

        try:
            return await ai.generate(
                guild_id=guild_id,
                channel_id=message.channel.id,
                user_id=message.author.id,
                character_name=(
                    character_name
                    or "مساعد السيرفر جيميناي"
                ),
                prompt=prompt,
                mode=mode,
                provider=provider,
                model=model,
                history_limit=0,
                max_tokens_override=response_length,
            )
        except TypeError:
            return await ai.generate(
                guild_id=guild_id,
                channel_id=message.channel.id,
                user_id=message.author.id,
                character_name=(
                    character_name
                    or "مساعد السيرفر جيميناي"
                ),
                prompt=prompt,
                mode=mode,
                provider=provider,
                model=model,
            )


async def generate_dm_reply(
    message: discord.Message,
):
    try:
        return await ai.generate(
            guild_id=0,
            channel_id=message.channel.id,
            user_id=message.author.id,
            character_name="مساعد MyAI",
            prompt=message.content,
            mode="friendly",
            provider="google",
            model=GOOGLE_MODEL,
        )

    except Exception as exc:
        print(
            "[DM AI ERROR]",
            repr(exc),
        )

        return "صار خطأ وأنا أحاول أرد عليك 😭"


# ============================================================
# SEND RESPONSE
# ============================================================

async def send_ai_response(
    destination,
    response: str,
):
    if not response:
        return

    chunks = split_message(response)

    for chunk in chunks:
        await destination.send(
            chunk,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def generate_with_typing_message(
    message: discord.Message,
    config: dict,
    advanced: dict,
):
    character = get_active_character(
        message.guild.id
    )

    character_name = (
        character.get("name")
        if character
        else (
            config.get("character_name")
            or "مساعد السيرفر جيميناي"
        )
    )

    timeout = int(
        advanced.get(
            "timeout",
            DEFAULT_AI_TIMEOUT,
        )
    )

    typing_message = None

    try:
        typing_message = await message.channel.send(
            f"**{character_name}** يكتب..."
        )

        start = time.monotonic()

        async with AI_SEMAPHORE:
            response = await asyncio.wait_for(
                generate_chat_reply(
                    message,
                    config,
                    advanced,
                ),
                timeout=timeout,
            )

        elapsed = time.monotonic() - start

        if elapsed < MIN_TYPING_DELAY:
            await asyncio.sleep(
                MIN_TYPING_DELAY - elapsed
            )

        if typing_message:
            chunks = split_message(response)

            if chunks:
                await typing_message.edit(
                    content=chunks[0]
                )

                for chunk in chunks[1:]:
                    await message.channel.send(
                        chunk,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )

        return response

    except asyncio.TimeoutError:
        if typing_message:
            await typing_message.edit(
                content="⏱️ انتهى وقت انتظار الذكاء الاصطناعي."
            )

        return None

    except Exception as exc:
        traceback.print_exc()

        if typing_message:
            try:
                await typing_message.edit(
                    content="❌ حدث خطأ أثناء توليد الرد."
                )
            except Exception:
                pass

        return None


# ============================================================
# CHARACTER SELECT
# ============================================================

def character_label(character):
    data = row_to_dict(character) or {}

    name = (
        data.get("name")
        or data.get("character_name")
        or "بدون اسم"
    )

    char_type = (
        data.get("character_type")
        or "normal"
    )

    display_type = CHARACTER_TYPES.get(
        char_type,
        char_type,
    )

    return (
        f"{name[:60]} — {display_type}"
    )


def character_description(character):
    data = row_to_dict(character) or {}

    description = (
        data.get("description")
        or "بدون وصف"
    )

    return description[:90]


def make_character_options(
    characters,
    include_owner=False,
):
    options = []

    for character in characters[:25]:
        data = row_to_dict(character) or {}

        name = (
            data.get("name")
            or data.get("character_name")
        )

        if not name:
            continue

        description = character_description(
            character
        )

        options.append(
            discord.SelectOption(
                label=name[:100],
                description=description,
                value=name[:100],
                emoji="🎭",
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
        characters,
    ):
        self.characters = characters

        options = make_character_options(
            characters
        )

        if not options:
            options = [
                discord.SelectOption(
                    label="لا توجد شخصيات",
                    value="none",
                    emoji="❌",
                )
            ]

        super().__init__(
            placeholder="اختر شخصية لعرض معلوماتها...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        value = self.values[0]

        if value == "none":
            await interaction.response.send_message(
                "❌ لا توجد شخصيات.",
                ephemeral=True,
            )
            return

        character = get_character(
            interaction.guild.id,
            value,
        )

        if not character:
            await interaction.response.send_message(
                "❌ الشخصية غير موجودة.",
                ephemeral=True,
            )
            return

        data = row_to_dict(character) or {}

        name = data.get(
            "name",
            value,
        )

        char_type = data.get(
            "character_type",
            "normal",
        )

        type_name = CHARACTER_TYPES.get(
            char_type,
            char_type,
        )

        description = data.get(
            "description"
        ) or "لا يوجد وصف."

        personality = data.get(
            "personality"
        ) or "غير محددة"

        owner_id = data.get(
            "created_by",
            0,
        )

        owner_text = (
            f"<@{owner_id}>"
            if owner_id
            else "النظام"
        )

        provider = data.get(
            "provider",
            "google",
        )

        model = data.get(
            "model",
            GOOGLE_MODEL,
        )

        embed = discord.Embed(
            title=f"🎭 {name}",
            description=description,
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="النوع",
            value=type_name,
            inline=True,
        )

        embed.add_field(
            name="المالك",
            value=owner_text,
            inline=True,
        )

        embed.add_field(
            name="المزود",
            value=provider,
            inline=True,
        )

        embed.add_field(
            name="النموذج",
            value=model,
            inline=True,
        )

        embed.add_field(
            name="الشخصية",
            value=personality[:1000],
            inline=False,
        )

        embed.set_footer(
            text="المعلومات الخاصة والتعليمات السرية لا يتم عرضها."
        )

        await interaction.response.edit_message(
            embed=embed,
            view=None,
        )


class CharacterInfoView(
    discord.ui.View
):
    def __init__(
        self,
        characters,
    ):
        super().__init__(
            timeout=120
        )

        self.add_item(
            CharacterInfoSelect(
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
        characters,
    ):
        self.guild_id = guild_id

        options = make_character_options(
            characters
        )

        if not options:
            options = [
                discord.SelectOption(
                    label="لا توجد شخصيات",
                    value="none",
                )
            ]

        super().__init__(
            placeholder="اختر الشخصية النشطة...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        if not can_manage_ai(
            interaction.user
        ):
            await interaction.response.send_message(
                "❌ ما عندك صلاحية.",
                ephemeral=True,
            )
            return

        value = self.values[0]

        if value == "none":
            await interaction.response.send_message(
                "❌ لا توجد شخصيات.",
                ephemeral=True,
            )
            return

        character = get_character(
            self.guild_id,
            value,
        )

        if not character:
            await interaction.response.send_message(
                "❌ الشخصية غير موجودة.",
                ephemeral=True,
            )
            return

        try:
            db.set_active_character(
                self.guild_id,
                character,
            )

        except Exception:
            db.set_active_character(
                self.guild_id,
                value,
            )

        await interaction.response.edit_message(
            content=(
                f"✅ تم اختيار الشخصية **{value}** "
                "كشخصية السيرفر الحالية."
            ),
            embed=None,
            view=None,
        )


class CharacterUseView(
    discord.ui.View
):
    def __init__(
        self,
        guild_id,
        characters,
    ):
        super().__init__(
            timeout=120
        )

        self.add_item(
            CharacterUseSelect(
                guild_id,
                characters,
            )
        )


# ============================================================
# CHARACTER EDIT VIEW
# ============================================================

class CharacterEditModal(
    discord.ui.Modal,
    title="✏️ تعديل الشخصية",
):
    custom_instructions = discord.ui.TextInput(
        label="التعليمات المخصصة",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1500,
    )

    speaking_style = discord.ui.TextInput(
        label="أسلوب الكلام",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    description = discord.ui.TextInput(
        label="الوصف",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(
        self,
        character_name,
    ):
        super().__init__()

        self.character_name = character_name

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        character = get_character(
            interaction.guild.id,
            self.character_name,
        )

        if not character:
            await interaction.response.send_message(
                "❌ الشخصية غير موجودة.",
                ephemeral=True,
            )
            return

        data = row_to_dict(character) or {}

        if int(
            data.get("created_by", 0)
        ) != interaction.user.id:
            await interaction.response.send_message(
                "❌ هذه الشخصية ليست ملكك.",
                ephemeral=True,
            )
            return

        kwargs = {}

        if self.custom_instructions.value.strip():
            kwargs["custom_instructions"] = (
                self.custom_instructions.value.strip()
            )

        if self.speaking_style.value.strip():
            kwargs["speaking_style"] = (
                self.speaking_style.value.strip()
            )

        if self.description.value.strip():
            kwargs["description"] = (
                self.description.value.strip()
            )

        if not kwargs:
            await interaction.response.send_message(
                "ℹ️ ما تم إدخال أي تعديل.",
                ephemeral=True,
            )
            return

        db.update_character(
            interaction.guild.id,
            self.character_name,
            **kwargs,
        )

        await interaction.response.send_message(
            f"✅ تم تعديل **{self.character_name}**.",
            ephemeral=True,
        )


class CharacterEditSelect(
    discord.ui.Select
):
    def __init__(
        self,
        guild_id,
        user_id,
        characters,
    ):
        self.guild_id = guild_id
        self.user_id = user_id

        owned = []

        for character in characters:
            data = row_to_dict(character) or {}

            if int(
                data.get("created_by", 0)
            ) == user_id:
                owned.append(character)

        self.characters = owned

        options = make_character_options(
            owned
        )

        if not options:
            options = [
                discord.SelectOption(
                    label="لا توجد شخصيات تملكها",
                    value="none",
                )
            ]

        super().__init__(
            placeholder="اختر الشخصية التي تريد تعديلها...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ هذه القائمة ليست لك.",
                ephemeral=True,
            )
            return

        value = self.values[0]

        if value == "none":
            await interaction.response.send_message(
                "❌ ما عندك شخصيات قابلة للتعديل.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            CharacterEditModal(value)
        )


class CharacterEditView(
    discord.ui.View
):
    def __init__(
        self,
        guild_id,
        user_id,
        characters,
    ):
        super().__init__(
            timeout=120
        )

        self.add_item(
            CharacterEditSelect(
                guild_id,
                user_id,
                characters,
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
        user_id,
        character_name,
    ):
        super().__init__(
            timeout=60
        )

        self.guild_id = guild_id
        self.user_id = user_id
        self.character_name = character_name

    @discord.ui.button(
        label="حذف",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ هذه العملية ليست لك.",
                ephemeral=True,
            )
            return

        character = get_character(
            self.guild_id,
            self.character_name,
        )

        if not character:
            await interaction.response.edit_message(
                content="❌ الشخصية غير موجودة.",
                view=None,
            )
            return

        data = row_to_dict(character) or {}

        if int(
            data.get("created_by", 0)
        ) != self.user_id:
            await interaction.response.edit_message(
                content="❌ لا يمكنك حذف هذه الشخصية.",
                view=None,
            )
            return

        db.delete_character(
            self.guild_id,
            self.character_name,
        )

        await interaction.response.edit_message(
            content=(
                f"🗑️ تم حذف الشخصية "
                f"**{self.character_name}**."
            ),
            view=None,
        )

    @discord.ui.button(
        label="إلغاء",
        style=discord.ButtonStyle.secondary,
        emoji="✖️",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ هذه العملية ليست لك.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content="تم إلغاء الحذف.",
            view=None,
        )


class CharacterDeleteSelect(
    discord.ui.Select
):
    def __init__(
        self,
        guild_id,
        user_id,
        characters,
    ):
        self.guild_id = guild_id
        self.user_id = user_id

        owned = []

        for character in characters:
            data = row_to_dict(character) or {}

            if int(
                data.get("created_by", 0)
            ) == user_id:
                owned.append(character)

        options = make_character_options(
            owned
        )

        if not options:
            options = [
                discord.SelectOption(
                    label="لا توجد شخصيات تملكها",
                    value="none",
                )
            ]

        super().__init__(
            placeholder="اختر الشخصية التي تريد حذفها...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ هذه القائمة ليست لك.",
                ephemeral=True,
            )
            return

        value = self.values[0]

        if value == "none":
            await interaction.response.send_message(
                "❌ ما عندك شخصيات.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content=(
                f"⚠️ هل أنت متأكد من حذف "
                f"**{value}**؟"
            ),
            view=CharacterDeleteConfirm(
                self.guild_id,
                self.user_id,
                value,
            ),
        )


class CharacterDeleteView(
    discord.ui.View
):
    def __init__(
        self,
        guild_id,
        user_id,
        characters,
    ):
        super().__init__(
            timeout=120
        )

        self.add_item(
            CharacterDeleteSelect(
                guild_id,
                user_id,
                characters,
            )
        )


# ============================================================
# DASHBOARD
# ============================================================

def dashboard_embed(
    guild: discord.Guild,
):
    config = get_config(
        guild.id
    )

    advanced = get_advanced(
        guild.id
    )

    enabled = bool(
        config.get(
            "enabled",
            config.get(
                "ai_enabled",
                True,
            ),
        )
    )

    character = (
        config.get("character_name")
        or config.get("active_character")
        or "مساعد السيرفر جيميناي"
    )

    mode = (
        config.get("mode")
        or config.get("ai_mode")
        or "normal"
    )

    reply_type = (
        config.get("reply_type")
        or "mention"
    )

    channel_id = (
        config.get("channel_id")
        or config.get("ai_channel_id")
    )

    channel_text = (
        f"<#{channel_id}>"
        if channel_id
        else "كل الرومات"
    )

    provider = (
        config.get("provider")
        or PRIMARY_AI_PROVIDER
    )

    model = (
        config.get("model")
        or GOOGLE_MODEL
    )

    status = "🟢 مفعّل" if enabled else "🔴 متوقف"

    memory = (
        "🟢"
        if advanced.get("memory_enabled", True)
        else "🔴"
    )

    security = (
        "🟢"
        if advanced.get("security_enabled", True)
        else "🔴"
    )

    bot_chat = (
        "🟢"
        if advanced.get("bot_chat_enabled", True)
        else "🔴"
    )

    embed = discord.Embed(
        title="⚙️ MyAI — لوحة التحكم",
        description=(
            "لوحة التحكم الكاملة للذكاء الاصطناعي.\n"
            "يمكن تعديل الإعدادات من الأزرار بالأسفل."
        ),
        color=discord.Color.blurple(),
    )

    embed.add_field(
        name="🤖 حالة AI",
        value=status,
        inline=True,
    )

    embed.add_field(
        name="🎭 الشخصية",
        value=str(character)[:100],
        inline=True,
    )

    embed.add_field(
        name="🧠 الوضع",
        value=AI_MODES.get(
            mode,
            {}
        ).get(
            "name",
            mode,
        ),
        inline=True,
    )

    embed.add_field(
        name="💬 نوع الرد",
        value=REPLY_TYPES.get(
            reply_type,
            reply_type,
        ),
        inline=True,
    )

    embed.add_field(
        name="📡 الروم",
        value=channel_text,
        inline=True,
    )

    embed.add_field(
        name="🔌 Provider",
        value=provider,
        inline=True,
    )

    embed.add_field(
        name="🧩 Model",
        value=model,
        inline=True,
    )

    embed.add_field(
        name="🧠 الذاكرة",
        value=memory,
        inline=True,
    )

    embed.add_field(
        name="🛡️ الحماية",
        value=security,
        inline=True,
    )

    embed.add_field(
        name="🤖 Bot-to-Bot",
        value=bot_chat,
        inline=True,
    )

    embed.add_field(
        name="📚 History",
        value=str(
            advanced.get(
                "history_limit",
                20,
            )
        ),
        inline=True,
    )

    embed.add_field(
        name="⏱️ Timeout",
        value=f"{advanced.get('timeout', 35)} ثانية",
        inline=True,
    )

    embed.set_footer(
        text="🔐 لوحة التحكم متاحة لأعلى 3 رتب فقط."
    )

    return embed


# ============================================================
# DASHBOARD MODALS
# ============================================================

class TextSettingsModal(
    discord.ui.Modal,
    title="⚙️ إعدادات متقدمة",
):
    history_limit = discord.ui.TextInput(
        label="حد الذاكرة / History",
        placeholder="مثال: 20",
        required=False,
        max_length=4,
    )

    response_length = discord.ui.TextInput(
        label="طول الرد",
        placeholder="مثال: 1200",
        required=False,
        max_length=5,
    )

    timeout = discord.ui.TextInput(
        label="Timeout بالثواني",
        placeholder="مثال: 35",
        required=False,
        max_length=4,
    )

    bot_chain = discord.ui.TextInput(
        label="أقصى سلسلة Bot-to-Bot",
        placeholder="مثال: 6",
        required=False,
        max_length=3,
    )

    bot_cooldown = discord.ui.TextInput(
        label="Cooldown للبوتات",
        placeholder="مثال: 2",
        required=False,
        max_length=5,
    )

    def __init__(
        self,
        guild_id,
    ):
        super().__init__()

        self.guild_id = guild_id

        settings = get_advanced(
            guild_id
        )

        self.history_limit.default = str(
            settings.get(
                "history_limit",
                20,
            )
        )

        self.response_length.default = str(
            settings.get(
                "response_length",
                1200,
            )
        )

        self.timeout.default = str(
            settings.get(
                "timeout",
                35,
            )
        )

        self.bot_chain.default = str(
            settings.get(
                "bot_chat_max_chain",
                6,
            )
        )

        self.bot_cooldown.default = str(
            settings.get(
                "bot_chat_cooldown",
                2,
            )
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        try:
            history = max(
                0,
                min(
                    int(
                        self.history_limit.value
                    ),
                    100,
                ),
            )

            response_length = max(
                100,
                min(
                    int(
                        self.response_length.value
                    ),
                    4000,
                ),
            )

            timeout = max(
                10,
                min(
                    int(
                        self.timeout.value
                    ),
                    180,
                ),
            )

            chain = max(
                1,
                min(
                    int(
                        self.bot_chain.value
                    ),
                    50,
                ),
            )

            cooldown = max(
                0,
                min(
                    float(
                        self.bot_cooldown.value
                    ),
                    60,
                ),
            )

            save_advanced(
                self.guild_id,
                history_limit=history,
                response_length=response_length,
                timeout=timeout,
                bot_chat_max_chain=chain,
                bot_chat_cooldown=cooldown,
            )

            await interaction.response.edit_message(
                embed=dashboard_embed(
                    interaction.guild
                ),
                view=AISettingsView(
                    interaction.guild.id
                ),
            )

        except ValueError:
            await interaction.response.send_message(
                "❌ تأكد أن القيم أرقام صحيحة.",
                ephemeral=True,
            )


class AllowDenyModal(
    discord.ui.Modal,
    title="🛡️ Allow / Deny Members",
):
    allow = discord.ui.TextInput(
        label="Allow IDs",
        placeholder="123,456",
        required=False,
        max_length=1000,
    )

    deny = discord.ui.TextInput(
        label="Deny IDs",
        placeholder="123,456",
        required=False,
        max_length=1000,
    )

    keywords = discord.ui.TextInput(
        label="Sensitive Keywords",
        placeholder="كلمة,كلمة ثانية",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=1500,
    )

    def __init__(
        self,
        guild_id,
    ):
        super().__init__()

        self.guild_id = guild_id

        settings = get_advanced(
            guild_id
        )

        self.allow.default = ",".join(
            str(x)
            for x in settings.get(
                "allow_members",
                [],
            )
        )

        self.deny.default = ",".join(
            str(x)
            for x in settings.get(
                "deny_members",
                [],
            )
        )

        self.keywords.default = ",".join(
            str(x)
            for x in settings.get(
                "sensitive_keywords",
                DEFAULT_SENSITIVE_KEYWORDS,
            )
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        def parse_ids(value):
            result = []

            for item in value.split(","):
                item = item.strip()

                if not item:
                    continue

                try:
                    result.append(
                        int(item)
                    )
                except ValueError:
                    continue

            return result

        allow = parse_ids(
            self.allow.value
        )

        deny = parse_ids(
            self.deny.value
        )

        keywords = [
            x.strip()
            for x in self.keywords.value.split(",")
            if x.strip()
        ]

        save_advanced(
            self.guild_id,
            allow_members=allow,
            deny_members=deny,
            sensitive_keywords=keywords,
        )

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AISettingsView(
                interaction.guild.id
            ),
        )


# ============================================================
# DASHBOARD VIEW
# ============================================================

class AISettingsView(
    discord.ui.View
):
    def __init__(
        self,
        guild_id,
    ):
        super().__init__(
            timeout=300
        )

        self.guild_id = guild_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ):
        if not interaction.guild:
            return False

        if not can_use_ai_dashboard(
            interaction.user
        ):
            await interaction.response.send_message(
                "🔒 هذه اللوحة متاحة فقط لأعضاء **أعلى 3 رتب** في السيرفر.",
                ephemeral=True,
            )
            return False

        return True

    @discord.ui.button(
        label="AI",
        style=discord.ButtonStyle.primary,
        emoji="🤖",
        row=0,
    )
    async def ai_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        config = get_config(
            self.guild_id
        )

        enabled = bool(
            config.get(
                "enabled",
                config.get(
                    "ai_enabled",
                    True,
                ),
            )
        )

        try:
            db.save_ai_config(
                self.guild_id,
                enabled=not enabled,
            )
        except Exception:
            pass

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            ),
        )

    @discord.ui.button(
        label="الردود",
        style=discord.ButtonStyle.secondary,
        emoji="💬",
        row=0,
    )
    async def replies_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.edit_message(
            content="💬 اختر نوع الرد:",
            embed=None,
            view=ReplySettingsView(
                self.guild_id
            ),
        )

    @discord.ui.button(
        label="الشخصية",
        style=discord.ButtonStyle.secondary,
        emoji="🎭",
        row=0,
    )
    async def character_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        characters = db.get_characters(
            self.guild_id
        )

        await interaction.response.edit_message(
            content="🎭 اختر الشخصية:",
            embed=None,
            view=DashboardCharacterView(
                self.guild_id,
                characters,
            ),
        )

    @discord.ui.button(
        label="الوضع",
        style=discord.ButtonStyle.secondary,
        emoji="🧠",
        row=1,
    )
    async def mode_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.edit_message(
            content="🧠 اختر وضع الذكاء:",
            embed=None,
            view=ModeSettingsView(
                self.guild_id
            ),
        )

    @discord.ui.button(
        label="الذاكرة",
        style=discord.ButtonStyle.secondary,
        emoji="💾",
        row=1,
    )
    async def memory_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        settings = get_advanced(
            self.guild_id
        )

        save_advanced(
            self.guild_id,
            memory_enabled=not settings.get(
                "memory_enabled",
                True,
            ),
        )

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            ),
        )

    @discord.ui.button(
        label="متقدم",
        style=discord.ButtonStyle.secondary,
        emoji="⚙️",
        row=1,
    )
    async def advanced_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.send_modal(
            TextSettingsModal(
                self.guild_id
            )
        )

    @discord.ui.button(
        label="الحماية",
        style=discord.ButtonStyle.secondary,
        emoji="🛡️",
        row=2,
    )
    async def security_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        settings = get_advanced(
            self.guild_id
        )

        save_advanced(
            self.guild_id,
            security_enabled=not settings.get(
                "security_enabled",
                True,
            ),
        )

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            ),
        )

    @discord.ui.button(
        label="Bot-to-Bot",
        style=discord.ButtonStyle.secondary,
        emoji="🤖",
        row=2,
    )
    async def bot_chat_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        settings = get_advanced(
            self.guild_id
        )

        save_advanced(
            self.guild_id,
            bot_chat_enabled=not settings.get(
                "bot_chat_enabled",
                True,
            ),
        )

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            ),
        )

    @discord.ui.button(
        label="Allow / Deny",
        style=discord.ButtonStyle.secondary,
        emoji="👥",
        row=2,
    )
    async def allow_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.send_modal(
            AllowDenyModal(
                self.guild_id
            )
        )

    @discord.ui.button(
        label="الروم",
        style=discord.ButtonStyle.secondary,
        emoji="📢",
        row=3,
    )
    async def channel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.edit_message(
            content="📢 اختر روم الذكاء الاصطناعي:",
            embed=None,
            view=DashboardChannelView(
                self.guild_id
            ),
        )

    @discord.ui.button(
        label="مسح الذاكرة",
        style=discord.ButtonStyle.danger,
        emoji="🧹",
        row=3,
    )
    async def clear_memory_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        try:
            db.clear_memory(
                self.guild_id
            )

        except Exception:
            try:
                db.clear_history(
                    self.guild_id
                )
            except Exception:
                pass

        reset_bot_chain(
            self.guild_id
        )

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            ),
        )

    @discord.ui.button(
        label="إعادة ضبط",
        style=discord.ButtonStyle.danger,
        emoji="♻️",
        row=3,
    )
    async def reset_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        reset_advanced(
            self.guild_id
        )

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            ),
        )

    @discord.ui.button(
        label="تحديث",
        style=discord.ButtonStyle.success,
        emoji="🔄",
        row=4,
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            ),
        )


# ============================================================
# DASHBOARD CHARACTER
# ============================================================

class DashboardCharacterSelect(
    discord.ui.Select
):
    def __init__(
        self,
        guild_id,
        characters,
    ):
        self.guild_id = guild_id

        options = make_character_options(
            characters
        )

        if not options:
            options = [
                discord.SelectOption(
                    label="لا توجد شخصيات",
                    value="none",
                )
            ]

        super().__init__(
            placeholder="اختر شخصية...",
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        value = self.values[0]

        if value == "none":
            await interaction.response.send_message(
                "❌ لا توجد شخصيات.",
                ephemeral=True,
            )
            return

        try:
            db.set_active_character(
                self.guild_id,
                value,
            )

        except Exception:
            character = get_character(
                self.guild_id,
                value,
            )

            if character:
                db.set_active_character(
                    self.guild_id,
                    character,
                )

        try:
            db.save_ai_config(
                self.guild_id,
                character_name=value,
            )
        except Exception:
            pass

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            ),
        )


class DashboardCharacterView(
    discord.ui.View
):
    def __init__(
        self,
        guild_id,
        characters,
    ):
        super().__init__(
            timeout=120
        )

        self.add_item(
            DashboardCharacterSelect(
                guild_id,
                characters,
            )
        )

        self.add_item(
            DashboardBackButton(
                guild_id
            )
        )


# ============================================================
# BACK BUTTON
# ============================================================

class DashboardBackButton(
    discord.ui.Button
):
    def __init__(
        self,
        guild_id,
    ):
        self.guild_id = guild_id

        super().__init__(
            label="رجوع",
            style=discord.ButtonStyle.secondary,
            emoji="↩️",
            row=4,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.edit_message(
            content=None,
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            ),
        )


# ============================================================
# MODE VIEW
# ============================================================

class ModeSelect(
    discord.ui.Select
):
    def __init__(
        self,
        guild_id,
    ):
        self.guild_id = guild_id

        options = []

        for key, data in AI_MODES.items():
            options.append(
                discord.SelectOption(
                    label=data["name"],
                    description=data["description"],
                    value=key,
                    emoji="🧠",
                )
            )

        super().__init__(
            placeholder="اختر وضع الذكاء...",
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        value = self.values[0]

        db.save_ai_config(
            self.guild_id,
            mode=value,
        )

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            ),
        )


class ModeSettingsView(
    discord.ui.View
):
    def __init__(
        self,
        guild_id,
    ):
        super().__init__(
            timeout=120
        )

        self.add_item(
            ModeSelect(
                guild_id
            )
        )

        self.add_item(
            DashboardBackButton(
                guild_id
            )
        )


# ============================================================
# REPLY VIEW
# ============================================================

class ReplySelect(
    discord.ui.Select
):
    def __init__(
        self,
        guild_id,
    ):
        self.guild_id = guild_id

        options = []

        for key, name in REPLY_TYPES.items():
            options.append(
                discord.SelectOption(
                    label=name,
                    value=key,
                    emoji="💬",
                )
            )

        super().__init__(
            placeholder="اختر طريقة الرد...",
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        value = self.values[0]

        db.save_ai_config(
            self.guild_id,
            reply_type=value,
        )

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            ),
        )


class ReplySettingsView(
    discord.ui.View
):
    def __init__(
        self,
        guild_id,
    ):
        super().__init__(
            timeout=120
        )

        self.add_item(
            ReplySelect(
                guild_id
            )
        )

        self.add_item(
            DashboardBackButton(
                guild_id
            )
        )


# ============================================================
# CHANNEL VIEW
# ============================================================

class DashboardChannelSelect(
    discord.ui.ChannelSelect
):
    def __init__(
        self,
        guild_id,
    ):
        self.guild_id = guild_id

        super().__init__(
            placeholder="اختر روم الذكاء الاصطناعي...",
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.news,
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        channel = self.values[0]

        db.save_ai_config(
            self.guild_id,
            channel_id=channel.id,
        )

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            ),
        )


class DashboardChannelView(
    discord.ui.View
):
    def __init__(
        self,
        guild_id,
    ):
        super().__init__(
            timeout=120
        )

        self.add_item(
            DashboardChannelSelect(
                guild_id
            )
        )

        self.add_item(
            DashboardBackButton(
                guild_id
            )
        )


# ============================================================
# BOT CHAT CHECK
# ============================================================

def should_process_bot_chat(
    message: discord.Message,
    settings: dict,
):
    if not settings.get(
        "bot_chat_enabled",
        True,
    ):
        return False

    if not message.author.bot:
        return False

    if bot.user and message.author.id == bot.user.id:
        return False

    max_chain = int(
        settings.get(
            "bot_chat_max_chain",
            DEFAULT_MAX_BOT_CHAIN,
        )
    )

    if get_bot_chain(
        message.guild.id
    ) >= max_chain:
        reset_bot_chain(
            message.guild.id
        )
        return False

    cooldown = float(
        settings.get(
            "bot_chat_cooldown",
            DEFAULT_BOT_COOLDOWN,
        )
    )

    if bot_chat_on_cooldown(
        message.guild.id,
        cooldown,
    ):
        return False

    return True


# ============================================================
# SLASH COMMAND: AI
# ============================================================

@bot.tree.command(
    name="ai",
    description="تشغيل أو إيقاف الذكاء الاصطناعي",
)
@app_commands.describe(
    enabled="تشغيل أو إيقاف AI"
)
async def ai_command(
    interaction: discord.Interaction,
    enabled: bool,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ هذا الأمر للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    if not can_manage_ai(
        interaction.user
    ):
        await interaction.response.send_message(
            "❌ ما عندك صلاحية إدارة AI.",
            ephemeral=True,
        )
        return

    db.save_ai_config(
        interaction.guild.id,
        enabled=enabled,
    )

    await interaction.response.send_message(
        f"{'🟢 تم تشغيل' if enabled else '🔴 تم إيقاف'} الذكاء الاصطناعي.",
        ephemeral=True,
    )


# ============================================================
# /ai_setup
# ============================================================

@bot.tree.command(
    name="ai_setup",
    description="تحديد روم الذكاء الاصطناعي",
)
async def ai_setup(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    if not can_manage_ai(
        interaction.user
    ):
        await interaction.response.send_message(
            "❌ ما عندك صلاحية.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        "📢 اختر الروم:",
        view=DashboardChannelView(
            interaction.guild.id
        ),
        ephemeral=True,
    )


# ============================================================
# /ai_settings
# ============================================================

@bot.tree.command(
    name="ai_settings",
    description="فتح لوحة تحكم MyAI",
)
async def ai_settings(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ هذا الأمر للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    if not can_use_ai_dashboard(
        interaction.user
    ):
        await interaction.response.send_message(
            "🔒 هذا الأمر متاح فقط لأعضاء أعلى 3 رتب في السيرفر.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        embed=dashboard_embed(
            interaction.guild
        ),
        view=AISettingsView(
            interaction.guild.id
        ),
        ephemeral=True,
    )


# ============================================================
# /ai_config
# ============================================================

@bot.tree.command(
    name="ai_config",
    description="عرض إعدادات AI الحالية",
)
async def ai_config(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    if not can_use_ai_dashboard(
        interaction.user
    ):
        await interaction.response.send_message(
            "🔒 هذا الأمر متاح فقط لأعلى 3 رتب.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        embed=dashboard_embed(
            interaction.guild
        ),
        ephemeral=True,
    )


# ============================================================
# /character_create
# ============================================================

@bot.tree.command(
    name="character_create",
    description="إنشاء شخصية AI جديدة",
)
@app_commands.describe(
    name="اسم الشخصية",
    character_type="نوع الشخصية",
    custom_instructions="تعليمات خاصة",
    speaking_style="أسلوب الكلام",
)
async def character_create(
    interaction: discord.Interaction,
    name: str,
    character_type: str,
    custom_instructions: str = "",
    speaking_style: str = "",
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    name = normalize_text(name)

    if len(name) < 2:
        await interaction.response.send_message(
            "❌ اسم الشخصية قصير جدًا.",
            ephemeral=True,
        )
        return

    if len(name) > 80:
        await interaction.response.send_message(
            "❌ اسم الشخصية طويل جدًا.",
            ephemeral=True,
        )
        return

    character_type = (
        character_type.lower().strip()
    )

    if character_type not in CHARACTER_TYPES:
        await interaction.response.send_message(
            "❌ نوع الشخصية غير صحيح.",
            ephemeral=True,
        )
        return

    existing = get_character(
        interaction.guild.id,
        name,
    )

    if existing:
        await interaction.response.send_message(
            "❌ توجد شخصية بهذا الاسم.",
            ephemeral=True,
        )
        return

    db.create_character(
        guild_id=interaction.guild.id,
        name=name,
        description="شخصية مخصصة",
        personality=CHARACTER_TYPES[
            character_type
        ],
        system_prompt="",
        character_type=character_type,
        custom_instructions=custom_instructions,
        speaking_style=speaking_style,
        provider="google",
        model=GOOGLE_MODEL,
        created_by=interaction.user.id,
    )

    await interaction.response.send_message(
        f"✅ تم إنشاء الشخصية **{name}**.",
        ephemeral=True,
    )


# ============================================================
# /character_info
# ============================================================

@bot.tree.command(
    name="character_info",
    description="عرض معلومات شخصية AI",
)
async def character_info(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    characters = db.get_characters(
        interaction.guild.id
    )

    await interaction.response.send_message(
        "🎭 اختر الشخصية:",
        view=CharacterInfoView(
            characters
        ),
        ephemeral=True,
    )


# ============================================================
# /character_use
# ============================================================

@bot.tree.command(
    name="character_use",
    description="اختيار شخصية السيرفر",
)
async def character_use(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    if not can_manage_ai(
        interaction.user
    ):
        await interaction.response.send_message(
            "❌ ما عندك صلاحية.",
            ephemeral=True,
        )
        return

    characters = db.get_characters(
        interaction.guild.id
    )

    await interaction.response.send_message(
        "🎭 اختر الشخصية:",
        view=CharacterUseView(
            interaction.guild.id,
            characters,
        ),
        ephemeral=True,
    )


# ============================================================
# /character_edit
# ============================================================

@bot.tree.command(
    name="character_edit",
    description="تعديل شخصية تملكها",
)
async def character_edit(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    characters = db.get_characters(
        interaction.guild.id
    )

    await interaction.response.send_message(
        "✏️ اختر الشخصية التي تملكها:",
        view=CharacterEditView(
            interaction.guild.id,
            interaction.user.id,
            characters,
        ),
        ephemeral=True,
    )


# ============================================================
# /character_delete
# ============================================================

@bot.tree.command(
    name="character_delete",
    description="حذف شخصية تملكها",
)
async def character_delete(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    characters = db.get_characters(
        interaction.guild.id
    )

    await interaction.response.send_message(
        "🗑️ اختر الشخصية:",
        view=CharacterDeleteView(
            interaction.guild.id,
            interaction.user.id,
            characters,
        ),
        ephemeral=True,
    )


# ============================================================
# /character_list
# ============================================================

@bot.tree.command(
    name="character_list",
    description="عرض شخصيات السيرفر",
)
async def character_list(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    characters = db.get_characters(
        interaction.guild.id
    )

    if not characters:
        await interaction.response.send_message(
            "🎭 لا توجد شخصيات.",
            ephemeral=True,
        )
        return

    lines = []

    for character in characters:
        data = row_to_dict(character) or {}

        name = data.get(
            "name",
            "بدون اسم",
        )

        char_type = data.get(
            "character_type",
            "normal",
        )

        type_name = CHARACTER_TYPES.get(
            char_type,
            char_type,
        )

        owner = data.get(
            "created_by",
            0,
        )

        lines.append(
            f"🎭 **{name}** — {type_name} — <@{owner}>"
        )

    await interaction.response.send_message(
        "\n".join(lines)[:1900],
        ephemeral=True,
    )


# ============================================================
# /ai_status
# ============================================================

@bot.tree.command(
    name="ai_status",
    description="عرض حالة AI",
)
async def ai_status(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        embed=dashboard_embed(
            interaction.guild
        ),
        ephemeral=True,
    )


# ============================================================
# /ai_memory_clear
# ============================================================

@bot.tree.command(
    name="ai_memory_clear",
    description="مسح ذاكرة AI",
)
async def ai_memory_clear(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    if not can_manage_ai(
        interaction.user
    ):
        await interaction.response.send_message(
            "❌ ما عندك صلاحية.",
            ephemeral=True,
        )
        return

    try:
        db.clear_memory(
            interaction.guild.id
        )
    except Exception:
        db.clear_history(
            interaction.guild.id
        )

    reset_bot_chain(
        interaction.guild.id
    )

    await interaction.response.send_message(
        "🧹 تم مسح ذاكرة AI.",
        ephemeral=True,
    )


# ============================================================
# /ai_dm
# ============================================================

@bot.tree.command(
    name="ai_dm",
    description="تشغيل أو إيقاف ردود AI في الخاص",
)
@app_commands.describe(
    enabled="تشغيل أو إيقاف",
)
async def ai_dm(
    interaction: discord.Interaction,
    enabled: bool,
):
    db.set_dm_enabled(
        interaction.user.id,
        enabled,
    )

    await interaction.response.send_message(
        (
            "🟢 تم تشغيل AI في الخاص."
            if enabled
            else
            "🔴 تم إيقاف AI في الخاص."
        ),
        ephemeral=True,
    )


# ============================================================
# MESSAGE HANDLER
# ============================================================

@bot.event
async def on_message(
    message: discord.Message,
):
    try:
        print(
            f"[MESSAGE] "
            f"{message.author} "
            f"({message.author.id}) "
            f"in {message.channel}: "
            f"{message.content[:200]}"
        )

        # ----------------------------------------------------
        # SELF
        # ----------------------------------------------------

        if bot.user and message.author.id == bot.user.id:
            return

        # ----------------------------------------------------
        # DMs
        # ----------------------------------------------------

        if message.guild is None:
            if message.author.bot:
                return

            try:
                dm_enabled = db.get_dm_enabled(
                    message.author.id
                )
            except Exception:
                dm_enabled = False

            if not dm_enabled:
                await bot.process_commands(
                    message
                )
                return

            key = get_request_key(
                0,
                message.author.id,
                message.channel.id,
            )

            if key in ACTIVE_REQUESTS:
                return

            ACTIVE_REQUESTS.add(key)

            try:
                async with message.channel.typing():
                    response = await asyncio.wait_for(
                        generate_dm_reply(
                            message
                        ),
                        timeout=DEFAULT_AI_TIMEOUT,
                    )

                await send_ai_response(
                    message.channel,
                    response,
                )

            except Exception:
                traceback.print_exc()

            finally:
                ACTIVE_REQUESTS.discard(key)

            await bot.process_commands(
                message
            )

            return

        # ----------------------------------------------------
        # SERVER CONFIG
        # ----------------------------------------------------

        config = get_config(
            message.guild.id
        )

        advanced = get_advanced(
            message.guild.id
        )

        enabled = bool(
            config.get(
                "enabled",
                config.get(
                    "ai_enabled",
                    True,
                ),
            )
        )

        if not enabled:
            await bot.process_commands(
                message
            )
            return

        # ----------------------------------------------------
        # CHANNEL
        # ----------------------------------------------------

        if not channel_matches(
            message,
            config,
        ):
            await bot.process_commands(
                message
            )
            return

        # ----------------------------------------------------
        # MEMBER ALLOW / DENY
        # ----------------------------------------------------

        if not message.author.bot:
            if not member_is_allowed(
                message.author,
                advanced,
            ):
                await bot.process_commands(
                    message
                )
                return

        # ----------------------------------------------------
        # BOT MESSAGE
        # ----------------------------------------------------

        if message.author.bot:

            if not should_process_bot_chat(
                message,
                advanced,
            ):
                await bot.process_commands(
                    message
                )
                return

            reply_type = "bot_chat"

        else:
            # Human message resets chain.
            reset_bot_chain(
                message.guild.id
            )

            reply_type = (
                config.get(
                    "reply_type"
                )
                or "mention"
            )

        # ----------------------------------------------------
        # SECURITY
        # ----------------------------------------------------

        if (
            not message.author.bot
            and contains_sensitive_request(
                message.content,
                advanced,
            )
        ):
            await message.channel.send(
                "🛡️ ما أقدر أساعد في هذا النوع من الطلبات.",
                allowed_mentions=discord.AllowedMentions.none(),
            )

            await bot.process_commands(
                message
            )

            return

        # ----------------------------------------------------
        # REPLY TYPE
        # ----------------------------------------------------

        if reply_type not in REPLY_TYPES:
            reply_type = "mention"

        if (
            reply_type == "mention"
            and not message.author.bot
        ):
            if not is_directed_to_bot(
                message
            ):
                await bot.process_commands(
                    message
                )
                return

        elif (
            reply_type == "direct"
            and not message.author.bot
        ):
            if not is_directed_to_bot(
                message
            ):
                await bot.process_commands(
                    message
                )
                return

        elif (
            reply_type == "channel"
            and not message.author.bot
        ):
            pass

        elif (
            reply_type == "auto"
            and not message.author.bot
        ):
            pass

        elif reply_type == "bot_chat":
            if not message.author.bot:
                await bot.process_commands(
                    message
                )
                return

        # ----------------------------------------------------
        # BOT CHAT LOCK
        # ----------------------------------------------------

        lock = None

        if message.author.bot:
            lock = get_bot_lock(
                message.guild.id
            )

            if lock.locked():
                await bot.process_commands(
                    message
                )
                return

        # ----------------------------------------------------
        # REQUEST
        # ----------------------------------------------------

        key = get_request_key(
            message.guild.id,
            message.author.id,
            message.channel.id,
        )

        if key in ACTIVE_REQUESTS:
            await bot.process_commands(
                message
            )
            return

        ACTIVE_REQUESTS.add(key)

        try:

            if lock:
                await lock.acquire()

            # Bot chain increment happens
            # only when we're actually going
            # to generate a bot reply.
            if message.author.bot:
                chain = increment_bot_chain(
                    message.guild.id
                )

                max_chain = int(
                    advanced.get(
                        "bot_chat_max_chain",
                        DEFAULT_MAX_BOT_CHAIN,
                    )
                )

                if chain > max_chain:
                    reset_bot_chain(
                        message.guild.id
                    )
                    return

            # ------------------------------------------------
            # BOT CHAT = NO "يكتب..." PLACEHOLDER
            # ------------------------------------------------

            if message.author.bot:
                timeout = int(
                    advanced.get(
                        "timeout",
                        DEFAULT_AI_TIMEOUT,
                    )
                )

                try:
                    async with AI_SEMAPHORE:
                        response = await asyncio.wait_for(
                            generate_chat_reply(
                                message,
                                config,
                                advanced,
                            ),
                            timeout=timeout,
                        )

                    if response:
                        await send_ai_response(
                            message.channel,
                            response,
                        )

                        update_bot_chat_time(
                            message.guild.id
                        )

                except asyncio.TimeoutError:
                    pass

                except Exception:
                    traceback.print_exc()

            else:
                await generate_with_typing_message(
                    message,
                    config,
                    advanced,
                )

        finally:
            ACTIVE_REQUESTS.discard(
                key
            )

            if lock and lock.locked():
                lock.release()

        # ----------------------------------------------------
        # COMMANDS
        # ----------------------------------------------------

        await bot.process_commands(
            message
        )

    except Exception:
        traceback.print_exc()

        try:
            await bot.process_commands(
                message
            )
        except Exception:
            pass


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():
    print("=" * 60)
    print("MyAI BOT")
    print("=" * 60)
    print(
        f"Logged in as: "
        f"{bot.user} "
        f"({bot.user.id if bot.user else 'N/A'})"
    )

    print(
        f"Provider: {PRIMARY_AI_PROVIDER}"
    )

    print(
        f"Google model: {GOOGLE_MODEL}"
    )

    print(
        f"Servers: {len(bot.guilds)}"
    )

    print("=" * 60)


# ============================================================
# APP COMMAND ERROR
# ============================================================

@bot.event
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    print(
        "[APP COMMAND ERROR]",
        repr(error),
    )

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                "❌ حدث خطأ أثناء تنفيذ الأمر.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "❌ حدث خطأ أثناء تنفيذ الأمر.",
                ephemeral=True,
            )

    except Exception:
        pass


# ============================================================
# SETUP HOOK
# ============================================================

@bot.event
async def setup_hook():
    try:
        synced = await bot.tree.sync()

        print(
            f"[SLASH] Synced {len(synced)} commands."
        )

    except Exception:
        traceback.print_exc()


# ============================================================
# START
# ============================================================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is not configured."
    )


bot.run(TOKEN)
