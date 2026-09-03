import os
import re
import asyncio
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

MAX_ACTIVE_REQUESTS = 3
DEFAULT_AI_TIMEOUT = 35

MIN_TYPING_DELAY = 1.5
MAX_MESSAGE_LENGTH = 1900

DEFAULT_MAX_BOT_CHAIN = 6
DEFAULT_BOT_COOLDOWN = 2.0


# ============================================================
# AI MODES
# ============================================================

AI_MODES = {
    "normal": "عادي ومتوازن",
    "friendly": "ودود واجتماعي",
    "active": "نشط وحيوي",
    "fun": "مرح وخفيف",
    "professional": "رسمي ومنظم",
}


# ============================================================
# REPLY TYPES
# ============================================================

REPLY_TYPES = {
    "mention": "عند المنشن فقط",
    "direct": "عند توجيه الكلام للبوت",
    "channel": "داخل الروم المحدد",
    "auto": "تلقائيًا",
    "bot_chat": "التفاعل مع البوتات",
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
    "mischievous": "مشاغب",
    "curious": "فضولي",
    "creative": "إبداعي",
    "professional": "احترافي",
}


# ============================================================
# SECURITY
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


# ============================================================
# DISCORD
# ============================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
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

AI_SEMAPHORE = asyncio.Semaphore(
    MAX_ACTIVE_REQUESTS
)

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
    defaults = {
        "enabled": True,
        "channel_id": None,
        "mode": "normal",
        "reply_type": "mention",
        "character_name": None,
        "provider": PRIMARY_AI_PROVIDER,
        "model": GOOGLE_MODEL,
    }

    try:
        data = db.get_ai_config(
            guild_id
        )

        result = defaults.copy()
        result.update(
            row_to_dict(data) or {}
        )

        return result

    except Exception:
        return defaults


def get_advanced(guild_id: int):
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
        data = db.get_ai_advanced_settings(
            guild_id
        )

        settings = (
            row_to_dict(data) or {}
        )

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
                    value = json.loads(value)
                except Exception:
                    value = [
                        x.strip()
                        for x in value.split(",")
                        if x.strip()
                    ]

            result[key] = value or []

        return result

    except Exception:
        return defaults


def save_advanced(
    guild_id: int,
    **kwargs,
):
    try:
        return db.save_ai_advanced_settings(
            guild_id,
            **kwargs,
        )

    except Exception:
        traceback.print_exc()
        return False


def reset_advanced(
    guild_id: int,
):
    try:
        return db.reset_ai_advanced_settings(
            guild_id
        )

    except Exception:
        traceback.print_exc()
        return False


def get_character(
    guild_id: int,
    name: Optional[str],
):
    if not name:
        return None

    try:
        return db.get_character(
            guild_id,
            name,
        )

    except Exception:
        return None


def get_active_character(
    guild_id: int,
):
    config = get_config(
        guild_id
    )

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
        return db.get_active_character(
            guild_id
        )

    except Exception:
        return None


def normalize_text(
    text: str,
):
    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        text.strip(),
    )


def clean_mentions(
    text: str,
):
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

    return normalize_text(
        text
    )


def split_message(
    text: str,
    limit: int = MAX_MESSAGE_LENGTH,
):
    if not text:
        return []

    text = str(text)

    if len(text) <= limit:
        return [text]

    chunks = []

    while len(text) > limit:

        cut = text.rfind(
            "\n",
            0,
            limit,
        )

        if cut < 300:
            cut = text.rfind(
                " ",
                0,
                limit,
            )

        if cut < 1:
            cut = limit

        chunks.append(
            text[:cut]
        )

        text = text[
            cut:
        ].lstrip()

    if text:
        chunks.append(text)

    return chunks


def normalize_channel_id(
    value,
):
    if value is None:
        return None

    try:
        return int(value)

    except Exception:
        return None


def channel_matches(
    message,
    config,
):
    channel_id = (
        config.get("channel_id")
        or config.get("ai_channel_id")
    )

    channel_id = normalize_channel_id(
        channel_id
    )

    if channel_id is None:
        return True

    return (
        message.channel.id
        == channel_id
    )


def is_directed_to_bot(
    message,
):
    if not bot.user:
        return False

    if bot.user in message.mentions:
        return True

    text = (
        message.content
        or ""
    ).lower().strip()

    names = {
        bot.user.name.lower(),
        bot.user.display_name.lower(),
    }

    return any(
        text.startswith(name)
        for name in names
        if name
    )


# ============================================================
# PERMISSIONS
# ============================================================

def has_management_permission(
    member,
):
    if not member:
        return False

    if (
        member.guild.owner_id
        == member.id
    ):
        return True

    permissions = (
        member.guild_permissions
    )

    return (
        permissions.administrator
        or permissions.manage_guild
        or permissions.manage_channels
        or permissions.manage_roles
    )


def get_top_three_roles(
    guild,
):
    roles = [
        role
        for role in guild.roles
        if (
            role != guild.default_role
            and not role.managed
        )
    ]

    roles.sort(
        key=lambda role: role.position,
        reverse=True,
    )

    return roles[:3]


def is_top_three_role(
    member,
):
    if not member:
        return False

    if not member.guild:
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


def can_manage_ai(
    member,
):
    return has_management_permission(
        member
    )


def can_use_dashboard(
    member,
):
    return is_top_three_role(
        member
    )


# ============================================================
# MEMBER FILTERS
# ============================================================

def member_is_allowed(
    member,
    settings,
):
    try:
        allow = {
            int(x)
            for x in settings.get(
                "allow_members",
                [],
            )
        }

    except Exception:
        allow = set()

    try:
        deny = {
            int(x)
            for x in settings.get(
                "deny_members",
                [],
            )
        }

    except Exception:
        deny = set()

    if member.id in deny:
        return False

    if allow:
        return (
            member.id in allow
        )

    return True


# ============================================================
# SECURITY CHECK
# ============================================================

def contains_sensitive_request(
    text,
    settings,
):
    if not settings.get(
        "security_enabled",
        True,
    ):
        return False

    text = (
        text or ""
    ).lower()

    keywords = settings.get(
        "sensitive_keywords",
        DEFAULT_SENSITIVE_KEYWORDS,
    )

    for keyword in keywords:

        keyword = (
            str(keyword)
            .strip()
            .lower()
        )

        if (
            keyword
            and keyword in text
        ):
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

def get_bot_lock(
    guild_id,
):
    if (
        guild_id
        not in BOT_CHAT_LOCKS
    ):
        BOT_CHAT_LOCKS[
            guild_id
        ] = asyncio.Lock()

    return BOT_CHAT_LOCKS[
        guild_id
    ]


def get_bot_chain(
    guild_id,
):
    return BOT_CHAT_CHAINS.get(
        guild_id,
        0,
    )


def reset_bot_chain(
    guild_id,
):
    BOT_CHAT_CHAINS[
        guild_id
    ] = 0


def increment_bot_chain(
    guild_id,
):
    BOT_CHAT_CHAINS[
        guild_id
    ] = (
        get_bot_chain(
            guild_id
        ) + 1
    )

    return BOT_CHAT_CHAINS[
        guild_id
    ]


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
        time.monotonic()
        - last
        < cooldown
    )


def update_bot_chat_time(
    guild_id,
):
    BOT_CHAT_LAST_RESPONSE[
        guild_id
    ] = time.monotonic()


# ============================================================
# AI GENERATION
# ============================================================

async def generate_chat_reply(
    message,
    config,
    advanced,
):
    guild_id = (
        message.guild.id
    )

    character_name = (
        config.get(
            "character_name"
        )
        or config.get(
            "active_character"
        )
    )

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
        prompt = (
            "ابدأ التفاعل مع المستخدم بشكل طبيعي."
        )

    try:
        history_limit = max(
            0,
            min(
                int(
                    advanced.get(
                        "history_limit",
                        20,
                    )
                ),
                100,
            ),
        )

    except Exception:
        history_limit = 20

    try:
        response_length = max(
            100,
            min(
                int(
                    advanced.get(
                        "response_length",
                        1200,
                    )
                ),
                4000,
            ),
        )

    except Exception:
        response_length = 1200

    memory_enabled = bool(
        advanced.get(
            "memory_enabled",
            True,
        )
    )

    # مهم:
    # ai_engine.py يستقبل character
    # وليس character_name.
    #
    # ولا نضع Semaphore هنا.
    # الـSemaphore يتم أخذه من المكان
    # الذي يستدعي هذه الدالة.

    return await ai.generate(
        guild_id=guild_id,
        channel_id=message.channel.id,
        user_id=message.author.id,
        prompt=prompt,
        character=character,
        mode=mode,
        provider=provider,
        model=model,
        history_limit=(
            history_limit
            if memory_enabled
            else 0
        ),
        max_tokens_override=response_length,
        memory_enabled=memory_enabled,
    )


async def generate_dm_reply(
    message,
):
    prompt = clean_mentions(
        message.content
    )

    if not prompt:
        prompt = (
            "ابدأ التفاعل مع المستخدم بشكل طبيعي."
        )

    return await ai.generate(
        guild_id=0,
        channel_id=message.channel.id,
        user_id=message.author.id,
        prompt=prompt,
        character=None,
        mode="friendly",
        provider="google",
        model=GOOGLE_MODEL,
        history_limit=20,
        memory_enabled=True,
    )


# ============================================================
# SEND RESPONSE
# ============================================================

async def send_ai_response(
    destination,
    response,
):
    if not response:
        return

    chunks = split_message(
        response
    )

    for chunk in chunks:
        await destination.send(
            chunk,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def generate_with_typing_message(
    message,
    config,
    advanced,
):
    character = get_active_character(
        message.guild.id
    )

    character_data = (
        row_to_dict(character)
        or {}
    )

    character_name = (
        character_data.get(
            "name"
        )
        or config.get(
            "character_name"
        )
        or "مساعد السيرفر جيميناي"
    )

    try:
        timeout = max(
            10,
            min(
                int(
                    advanced.get(
                        "timeout",
                        DEFAULT_AI_TIMEOUT,
                    )
                ),
                180,
            ),
        )

    except Exception:
        timeout = DEFAULT_AI_TIMEOUT

    typing_message = None

    try:
        typing_message = (
            await message.channel.send(
                f"**{character_name}** يكتب..."
            )
        )

        started = time.monotonic()

        # Semaphore واحد فقط.
        async with AI_SEMAPHORE:
            response = await asyncio.wait_for(
                generate_chat_reply(
                    message,
                    config,
                    advanced,
                ),
                timeout=timeout,
            )

        elapsed = (
            time.monotonic()
            - started
        )

        if elapsed < MIN_TYPING_DELAY:
            await asyncio.sleep(
                MIN_TYPING_DELAY
                - elapsed
            )

        chunks = split_message(
            response
        )

        if not chunks:
            chunks = [
                "❌ ما قدرت أطلع رد."
            ]

        if typing_message:
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
            try:
                await typing_message.edit(
                    content=(
                        "⏱️ انتهى وقت انتظار "
                        "الذكاء الاصطناعي."
                    )
                )

            except Exception:
                pass

        return None

    except Exception:

        traceback.print_exc()

        if typing_message:
            try:
                await typing_message.edit(
                    content=(
                        "❌ حدث خطأ أثناء "
                        "توليد الرد."
                    )
                )

            except Exception:
                pass

        return None


# ============================================================
# CHARACTER UI
# ============================================================

def character_options(
    characters,
):
    options = []

    for character in characters[:25]:

        data = (
            row_to_dict(
                character
            )
            or {}
        )

        name = data.get(
            "name"
        )

        if not name:
            continue

        character_type = data.get(
            "character_type",
            "normal",
        )

        description = (
            data.get(
                "description"
            )
            or CHARACTER_TYPES.get(
                character_type,
                "شخصية",
            )
        )

        options.append(
            discord.SelectOption(
                label=str(
                    name
                )[:100],
                description=str(
                    description
                )[:100],
                value=str(
                    name
                )[:100],
                emoji="🎭",
            )
        )

    return options


# ============================================================
# CHARACTER INFO
# ============================================================

class CharacterInfoSelect(
    discord.ui.Select
):

    def __init__(
        self,
        characters,
    ):
        options = character_options(
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
            placeholder=(
                "اختر شخصية لعرض معلوماتها..."
            ),
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(
        self,
        interaction,
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

        data = (
            row_to_dict(
                character
            )
            or {}
        )

        name = data.get(
            "name",
            value,
        )

        character_type = data.get(
            "character_type",
            "normal",
        )

        owner_id = data.get(
            "created_by",
            0,
        )

        embed = discord.Embed(
            title=f"🎭 {name}",
            description=(
                data.get(
                    "description"
                )
                or "لا يوجد وصف."
            ),
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="النوع",
            value=CHARACTER_TYPES.get(
                character_type,
                character_type,
            ),
            inline=True,
        )

        embed.add_field(
            name="المالك",
            value=(
                f"<@{owner_id}>"
                if owner_id
                else "النظام"
            ),
            inline=True,
        )

        embed.add_field(
            name="المزود",
            value=data.get(
                "provider",
                "google",
            ),
            inline=True,
        )

        embed.add_field(
            name="النموذج",
            value=data.get(
                "model",
                GOOGLE_MODEL,
            ),
            inline=True,
        )

        embed.add_field(
            name="الشخصية",
            value=(
                data.get(
                    "personality"
                )
                or "غير محددة"
            )[:1000],
            inline=False,
        )

        embed.set_footer(
            text=(
                "التعليمات السرية و system prompt "
                "لا يتم عرضها."
            )
        )

        await interaction.response.edit_message(
            content=None,
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
# CHARACTER USE
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

        options = character_options(
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
            placeholder=(
                "اختر الشخصية النشطة..."
            ),
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(
        self,
        interaction,
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

        try:
            db.save_ai_config(
                self.guild_id,
                character_name=value,
            )
        except Exception:
            pass

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
# CHARACTER CREATOR
# ============================================================

class CharacterCreateModal(
    discord.ui.Modal,
    title="🎭 إنشاء شخصية",
):

    name = discord.ui.TextInput(
        label="اسم الشخصية",
        placeholder="مثال: مساعد الألعاب",
        required=True,
        max_length=80,
    )

    description = discord.ui.TextInput(
        label="الوصف",
        placeholder="وصف مختصر للشخصية",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    custom_instructions = discord.ui.TextInput(
        label="التعليمات المخصصة",
        placeholder="كيف يجب أن تتصرف؟",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1500,
    )

    speaking_style = discord.ui.TextInput(
        label="أسلوب الكلام",
        placeholder="هادئ، مرح، رسمي...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=800,
    )

    async def on_submit(
        self,
        interaction,
    ):
        if not can_manage_ai(
            interaction.user
        ):
            await interaction.response.send_message(
                "❌ ما عندك صلاحية إنشاء شخصية.",
                ephemeral=True,
            )
            return

        name = normalize_text(
            str(self.name)
        )

        if len(name) < 2:
            await interaction.response.send_message(
                "❌ اسم الشخصية قصير جدًا.",
                ephemeral=True,
            )
            return

        if db.character_exists(
            interaction.guild.id,
            name,
        ):
            await interaction.response.send_message(
                "❌ توجد شخصية بهذا الاسم بالفعل.",
                ephemeral=True,
            )
            return

        try:
            db.create_character(
                guild_id=interaction.guild.id,
                name=name,
                description=str(
                    self.description
                ),
                personality=str(
                    self.speaking_style
                ),
                system_prompt="",
                character_type="normal",
                custom_instructions=str(
                    self.custom_instructions
                ),
                speaking_style=str(
                    self.speaking_style
                ),
                provider="google",
                model=GOOGLE_MODEL,
                created_by=interaction.user.id,
            )

            await interaction.response.send_message(
                f"✅ تم إنشاء الشخصية **{name}** بنجاح! 🎭",
                ephemeral=True,
            )

        except Exception as exc:
            traceback.print_exc()

            await interaction.response.send_message(
                f"❌ تعذر إنشاء الشخصية: `{str(exc)[:500]}`",
                ephemeral=True,
            )


class CharacterCreatorView(
    discord.ui.View
):

    def __init__(self):
        super().__init__(
            timeout=180
        )

    @discord.ui.button(
        label="إنشاء الشخصية",
        style=discord.ButtonStyle.primary,
        emoji="🎭",
    )
    async def create_button(
        self,
        interaction,
        button,
    ):
        if not can_manage_ai(
            interaction.user
        ):
            await interaction.response.send_message(
                "❌ ما عندك صلاحية.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            CharacterCreateModal()
        )


# ============================================================
# CHARACTER TYPE
# ============================================================

class CharacterTypeSelect(
    discord.ui.Select
):

    def __init__(self):
        options = []

        for key, name in CHARACTER_TYPES.items():

            options.append(
                discord.SelectOption(
                    label=name,
                    value=key,
                    description=f"نوع الشخصية: {name}",
                    emoji="🎭",
                )
            )

        super().__init__(
            placeholder="اختر نوع الشخصية...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(
        self,
        interaction,
    ):
        value = self.values[0]

        await interaction.response.send_message(
            f"🎭 النوع المختار: "
            f"**{CHARACTER_TYPES[value]}**\n"
            f"المعرف: `{value}`",
            ephemeral=True,
        )


class CharacterTypeView(
    discord.ui.View
):

    def __init__(self):
        super().__init__(
            timeout=120
        )

        self.add_item(
            CharacterTypeSelect()
        )


# ============================================================
# DASHBOARD
# ============================================================

def dashboard_embed(
    guild,
):
    config = get_config(
        guild.id
    )

    advanced = get_advanced(
        guild.id
    )

    character = (
        config.get(
            "character_name"
        )
        or config.get(
            "active_character"
        )
        or "مساعد السيرفر جيميناي"
    )

    channel_id = (
        config.get(
            "channel_id"
        )
        or config.get(
            "ai_channel_id"
        )
    )

    channel_text = (
        f"<#{channel_id}>"
        if channel_id
        else "كل الرومات"
    )

    mode = (
        config.get("mode")
        or config.get("ai_mode")
        or "normal"
    )

    reply_type = config.get(
        "reply_type",
        "mention",
    )

    provider = (
        config.get("provider")
        or PRIMARY_AI_PROVIDER
    )

    model = (
        config.get("model")
        or GOOGLE_MODEL
    )

    embed = discord.Embed(
        title="⚙️ MyAI — لوحة التحكم",
        description=(
            "لوحة التحكم الخاصة بالذكاء الاصطناعي."
        ),
        color=discord.Color.blurple(),
    )

    embed.add_field(
        name="🤖 الحالة",
        value=(
            "🟢 مفعّل"
            if config.get(
                "enabled",
                True,
            )
            else "🔴 متوقف"
        ),
        inline=True,
    )

    embed.add_field(
        name="🎭 الشخصية",
        value=str(
            character
        )[:100],
        inline=True,
    )

    embed.add_field(
        name="🧠 الوضع",
        value=AI_MODES.get(
            mode,
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
        name="📢 الروم",
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
        name="💾 الذاكرة",
        value=(
            "🟢"
            if advanced.get(
                "memory_enabled",
                True,
            )
            else "🔴"
        ),
        inline=True,
    )

    embed.add_field(
        name="🛡️ الحماية",
        value=(
            "🟢"
            if advanced.get(
                "security_enabled",
                True,
            )
            else "🔴"
        ),
        inline=True,
    )

    embed.add_field(
        name="🤖 Bot-to-Bot",
        value=(
            "🟢"
            if advanced.get(
                "bot_chat_enabled",
                True,
            )
            else "🔴"
        ),
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
        value=(
            f"{advanced.get('timeout', 35)} ثانية"
        ),
        inline=True,
    )

    embed.set_footer(
        text=(
            "🔐 لوحة التحكم متاحة لأعلى 3 رتب فقط."
        )
    )

    return embed


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
        )

    async def callback(
        self,
        interaction,
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


class DashboardChannelSelect(
    discord.ui.ChannelSelect
):

    def __init__(
        self,
        guild_id,
    ):
        self.guild_id = guild_id

        super().__init__(
            placeholder=(
                "اختر روم الذكاء الاصطناعي..."
            ),
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.news,
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(
        self,
        interaction,
    ):
        channel = self.values[0]

        db.save_ai_config(
            self.guild_id,
            channel_id=channel.id,
        )

        await interaction.response.edit_message(
            content=None,
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

        options = character_options(
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
            min_values=1,
            max_values=1,
        )

    async def callback(
        self,
        interaction,
    ):
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

        db.save_ai_config(
            self.guild_id,
            character_name=value,
        )

        await interaction.response.edit_message(
            content=None,
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
# MODE
# ============================================================

class ModeSelect(
    discord.ui.Select
):

    def __init__(
        self,
        guild_id,
    ):
        self.guild_id = guild_id

        options = [
            discord.SelectOption(
                label=name,
                value=value,
                description=name,
                emoji="🧠",
            )
            for value, name
            in AI_MODES.items()
        ]

        super().__init__(
            placeholder="اختر وضع الذكاء...",
            options=options,
        )

    async def callback(
        self,
        interaction,
    ):
        value = self.values[0]

        db.save_ai_config(
            self.guild_id,
            mode=value,
        )

        await interaction.response.edit_message(
            content=None,
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
# REPLY TYPE
# ============================================================

class ReplySelect(
    discord.ui.Select
):

    def __init__(
        self,
        guild_id,
    ):
        self.guild_id = guild_id

        options = [
            discord.SelectOption(
                label=name,
                value=value,
                description=name,
                emoji="💬",
            )
            for value, name
            in REPLY_TYPES.items()
        ]

        super().__init__(
            placeholder="اختر طريقة الرد...",
            options=options,
        )

    async def callback(
        self,
        interaction,
    ):
        value = self.values[0]

        db.save_ai_config(
            self.guild_id,
            reply_type=value,
        )

        await interaction.response.edit_message(
            content=None,
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
# ADVANCED SETTINGS MODAL
# ============================================================

class TextSettingsModal(
    discord.ui.Modal,
    title="⚙️ إعدادات متقدمة",
):

    history_limit = discord.ui.TextInput(
        label="حد الذاكرة / History",
        placeholder="20",
        required=False,
        max_length=4,
    )

    response_length = discord.ui.TextInput(
        label="طول الرد",
        placeholder="1200",
        required=False,
        max_length=5,
    )

    timeout = discord.ui.TextInput(
        label="Timeout",
        placeholder="35",
        required=False,
        max_length=4,
    )

    bot_chain = discord.ui.TextInput(
        label="أقصى سلسلة Bot-to-Bot",
        placeholder="6",
        required=False,
        max_length=3,
    )

    bot_cooldown = discord.ui.TextInput(
        label="Cooldown للبوتات",
        placeholder="2",
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
        interaction,
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
                content=None,
                embed=dashboard_embed(
                    interaction.guild
                ),
                view=AISettingsView(
                    self.guild_id
                ),
            )

        except ValueError:
            await interaction.response.send_message(
                "❌ تأكد أن القيم أرقام صحيحة.",
                ephemeral=True,
            )


class AllowDenyModal(
    discord.ui.Modal,
    title="🛡️ Allow / Deny",
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
        style=discord.TextStyle.paragraph,
        required=False,
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
        interaction,
    ):
        def parse_ids(
            value,
        ):
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
                    pass

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
            content=None,
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AISettingsView(
                self.guild_id
            ),
        )


# ============================================================
# AI SETTINGS VIEW
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
        interaction,
    ):
        if not interaction.guild:
            return False

        if not can_use_dashboard(
            interaction.user
        ):
            await interaction.response.send_message(
                "🔒 هذه اللوحة متاحة فقط لأعلى 3 رتب.",
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
        interaction,
        button,
    ):
        config = get_config(
            self.guild_id
        )

        enabled = bool(
            config.get(
                "enabled",
                True,
            )
        )

        db.save_ai_config(
            self.guild_id,
            enabled=not enabled,
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
        label="الردود",
        style=discord.ButtonStyle.secondary,
        emoji="💬",
        row=0,
    )
    async def replies_button(
        self,
        interaction,
        button,
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
        interaction,
        button,
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
        interaction,
        button,
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
        interaction,
        button,
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
        interaction,
        button,
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
        interaction,
        button,
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
        interaction,
        button,
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
        interaction,
        button,
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
        interaction,
        button,
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
        interaction,
        button,
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
        interaction,
        button,
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
        interaction,
        button,
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
# SLASH COMMANDS
# ============================================================

@bot.tree.command(
    name="ai",
    description="تشغيل أو إيقاف الذكاء الاصطناعي",
)
@app_commands.describe(
    enabled="تشغيل أو إيقاف AI"
)
async def ai_command(
    interaction,
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
        (
            "🟢 تم تشغيل الذكاء الاصطناعي."
            if enabled
            else
            "🔴 تم إيقاف الذكاء الاصطناعي."
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="ai_setup",
    description="تحديد روم الذكاء الاصطناعي",
)
async def ai_setup(
    interaction,
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


@bot.tree.command(
    name="ai_settings",
    description="فتح لوحة تحكم MyAI",
)
async def ai_settings(
    interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ هذا الأمر للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    if not can_use_dashboard(
        interaction.user
    ):
        await interaction.response.send_message(
            "🔒 هذا الأمر متاح فقط لأعضاء أعلى 3 رتب.",
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


@bot.tree.command(
    name="ai_config",
    description="عرض إعدادات AI الحالية",
)
async def ai_config(
    interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    if not can_use_dashboard(
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


@bot.tree.command(
    name="ai_status",
    description="عرض حالة AI",
)
async def ai_status(
    interaction,
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


@bot.tree.command(
    name="ai_memory_clear",
    description="مسح ذاكرة AI",
)
async def ai_memory_clear(
    interaction,
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


@bot.tree.command(
    name="ai_dm",
    description="تشغيل أو إيقاف AI في الخاص",
)
@app_commands.describe(
    enabled="تشغيل أو إيقاف",
)
async def ai_dm(
    interaction,
    enabled: bool,
):
    try:
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

    except Exception:
        traceback.print_exc()

        await interaction.response.send_message(
            "❌ تعذر تغيير إعداد الخاص.",
            ephemeral=True,
        )


# ============================================================
# CHARACTER COMMANDS
# ============================================================

@bot.tree.command(
    name="character_creator",
    description="فتح منشئ الشخصيات",
)
async def character_creator(
    interaction,
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

    embed = discord.Embed(
        title="🎭 منشئ الشخصيات",
        description=(
            "اضغط الزر لإنشاء شخصية جديدة.\n\n"
            "يمكنك تحديد الاسم والوصف والتعليمات "
            "وأسلوب الكلام."
        ),
        color=discord.Color.blurple(),
    )

    await interaction.response.send_message(
        embed=embed,
        view=CharacterCreatorView(),
        ephemeral=True,
    )


@bot.tree.command(
    name="character_type",
    description="عرض أنواع الشخصيات",
)
async def character_type(
    interaction,
):
    embed = discord.Embed(
        title="🎭 أنواع الشخصيات",
        description="\n".join(
            f"**{name}** — `{key}`"
            for key, name
            in CHARACTER_TYPES.items()
        ),
        color=discord.Color.blurple(),
    )

    await interaction.response.send_message(
        embed=embed,
        view=CharacterTypeView(),
        ephemeral=True,
    )


@bot.tree.command(
    name="character_info",
    description="عرض معلومات شخصية AI",
)
async def character_info(
    interaction,
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
            "❌ لا توجد شخصيات.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        "🎭 اختر الشخصية:",
        view=CharacterInfoView(
            characters
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="character_use",
    description="اختيار شخصية السيرفر",
)
async def character_use(
    interaction,
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


@bot.tree.command(
    name="character_list",
    description="عرض شخصيات السيرفر",
)
async def character_list(
    interaction,
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
        data = (
            row_to_dict(
                character
            )
            or {}
        )

        name = data.get(
            "name",
            "بدون اسم",
        )

        character_type = data.get(
            "character_type",
            "normal",
        )

        owner = data.get(
            "created_by",
            0,
        )

        lines.append(
            f"🎭 **{name}** — "
            f"{CHARACTER_TYPES.get(character_type, character_type)} "
            f"— <@{owner}>"
        )

    await interaction.response.send_message(
        "\n".join(lines)[:1900],
        ephemeral=True,
    )


@bot.tree.command(
    name="character_delete",
    description="حذف شخصية",
)
@app_commands.describe(
    name="اسم الشخصية",
)
async def character_delete(
    interaction,
    name: str,
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

    character = get_character(
        interaction.guild.id,
        name,
    )

    if not character:
        await interaction.response.send_message(
            "❌ الشخصية غير موجودة.",
            ephemeral=True,
        )
        return

    data = (
        row_to_dict(
            character
        )
        or {}
    )

    owner_id = int(
        data.get(
            "created_by",
            0,
        )
        or 0
    )

    if (
        owner_id
        and owner_id != interaction.user.id
        and not has_management_permission(
            interaction.user
        )
    ):
        await interaction.response.send_message(
            "❌ هذه الشخصية ليست لك.",
            ephemeral=True,
        )
        return

    db.delete_character(
        interaction.guild.id,
        name,
    )

    await interaction.response.send_message(
        f"🗑️ تم حذف الشخصية **{name}**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="character_edit",
    description="تعديل شخصية",
)
@app_commands.describe(
    name="اسم الشخصية",
    description="الوصف الجديد",
    personality="أسلوب الشخصية",
    instructions="التعليمات الجديدة",
)
async def character_edit(
    interaction,
    name: str,
    description: Optional[str] = None,
    personality: Optional[str] = None,
    instructions: Optional[str] = None,
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

    character = get_character(
        interaction.guild.id,
        name,
    )

    if not character:
        await interaction.response.send_message(
            "❌ الشخصية غير موجودة.",
            ephemeral=True,
        )
        return

    data = (
        row_to_dict(
            character
        )
        or {}
    )

    owner_id = int(
        data.get(
            "created_by",
            0,
        )
        or 0
    )

    if (
        owner_id
        and owner_id != interaction.user.id
        and not has_management_permission(
            interaction.user
        )
    ):
        await interaction.response.send_message(
            "❌ هذه الشخصية ليست لك.",
            ephemeral=True,
        )
        return

    changes = {}

    if description is not None:
        changes[
            "description"
        ] = description

    if personality is not None:
        changes[
            "personality"
        ] = personality

        changes[
            "speaking_style"
        ] = personality

    if instructions is not None:
        changes[
            "custom_instructions"
        ] = instructions

    if not changes:
        await interaction.response.send_message(
            "ℹ️ لم ترسل أي تعديل.",
            ephemeral=True,
        )
        return

    db.update_character(
        interaction.guild.id,
        name,
        **changes,
    )

    await interaction.response.send_message(
        f"✅ تم تعديل الشخصية **{name}**.",
        ephemeral=True,
    )


# ============================================================
# DASHBOARD COMMAND
# ============================================================

@bot.tree.command(
    name="ai_dashboard",
    description="فتح لوحة تحكم MyAI",
)
async def ai_dashboard(
    interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ هذا الأمر للسيرفرات فقط.",
            ephemeral=True,
        )
        return

    if not can_use_dashboard(
        interaction.user
    ):
        await interaction.response.send_message(
            "🔒 لوحة التحكم متاحة فقط لأعلى 3 رتب.",
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
# MESSAGE HANDLER
# ============================================================

@bot.event
async def on_message(
    message,
):
    try:

        # ====================================================
        # SELF
        # ====================================================

        if (
            bot.user
            and message.author.id
            == bot.user.id
        ):
            return


        # ====================================================
        # DMS
        # ====================================================

        if message.guild is None:

            if message.author.bot:
                return

            try:
                dm_enabled = (
                    db.get_dm_enabled(
                        message.author.id
                    )
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

            ACTIVE_REQUESTS.add(
                key
            )

            try:

                async with AI_SEMAPHORE:
                    response = (
                        await asyncio.wait_for(
                            generate_dm_reply(
                                message
                            ),
                            timeout=DEFAULT_AI_TIMEOUT,
                        )
                    )

                await send_ai_response(
                    message.channel,
                    response,
                )

            except Exception:
                traceback.print_exc()

            finally:
                ACTIVE_REQUESTS.discard(
                    key
                )

            return


        # ====================================================
        # CONFIG
        # ====================================================

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


        # ====================================================
        # CHANNEL
        # ====================================================

        if not channel_matches(
            message,
            config,
        ):
            await bot.process_commands(
                message
            )
            return


        # ====================================================
        # MEMBER FILTER
        # ====================================================

        if not message.author.bot:

            if not member_is_allowed(
                message.author,
                advanced,
            ):
                await bot.process_commands(
                    message
                )
                return


        # ====================================================
        # BOT CHAT
        # ====================================================

        if message.author.bot:

            if not advanced.get(
                "bot_chat_enabled",
                True,
            ):
                await bot.process_commands(
                    message
                )
                return

            if (
                bot.user
                and message.author.id
                == bot.user.id
            ):
                return

            reply_type = "bot_chat"

        else:

            reset_bot_chain(
                message.guild.id
            )

            reply_type = (
                config.get(
                    "reply_type"
                )
                or "mention"
            )


        # ====================================================
        # SECURITY
        # ====================================================

        if (
            not message.author.bot
            and contains_sensitive_request(
                message.content,
                advanced,
            )
        ):

            await message.channel.send(
                "🛡️ ما أقدر أساعد في هذا النوع من الطلبات.",
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )

            await bot.process_commands(
                message
            )

            return


        # ====================================================
        # REPLY TYPE
        # ====================================================

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


        # ====================================================
        # REQUEST KEY
        # ====================================================

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

        ACTIVE_REQUESTS.add(
            key
        )


        # ====================================================
        # BOT CHAT LIMIT
        # ====================================================

        if message.author.bot:

            guild_id = (
                message.guild.id
            )

            max_chain = int(
                advanced.get(
                    "bot_chat_max_chain",
                    DEFAULT_MAX_BOT_CHAIN,
                )
            )

            cooldown = float(
                advanced.get(
                    "bot_chat_cooldown",
                    DEFAULT_BOT_COOLDOWN,
                )
            )

            chain = (
                BOT_CHAT_CHAINS.get(
                    guild_id,
                    0,
                )
            )

            if chain >= max_chain:

                reset_bot_chain(
                    guild_id
                )

                ACTIVE_REQUESTS.discard(
                    key
                )

                await bot.process_commands(
                    message
                )

                return


            if bot_chat_on_cooldown(
                guild_id,
                cooldown,
            ):

                ACTIVE_REQUESTS.discard(
                    key
                )

                await bot.process_commands(
                    message
                )

                return


            increment_bot_chain(
                guild_id
            )


        # ====================================================
        # GENERATE
        # ====================================================

        try:

            if message.author.bot:

                timeout = int(
                    advanced.get(
                        "timeout",
                        DEFAULT_AI_TIMEOUT,
                    )
                )

                async with AI_SEMAPHORE:

                    response = (
                        await asyncio.wait_for(
                            generate_chat_reply(
                                message,
                                config,
                                advanced,
                            ),
                            timeout=timeout,
                        )
                    )

                if response:

                    await send_ai_response(
                        message.channel,
                        response,
                    )

                    update_bot_chat_time(
                        message.guild.id
                    )

            else:

                await generate_with_typing_message(
                    message,
                    config,
                    advanced,
                )

        except asyncio.TimeoutError:
            pass

        except Exception:
            traceback.print_exc()

        finally:

            ACTIVE_REQUESTS.discard(
                key
            )

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
# APP COMMAND ERROR
# ============================================================

@bot.tree.error
async def on_app_command_error(
    interaction,
    error,
):

    traceback.print_exception(
        type(error),
        error,
        error.__traceback__,
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
# READY
# ============================================================

@bot.event
async def on_ready():

    try:

        synced = await bot.tree.sync()

        print("=" * 60)
        print("MyAI BOT")
        print("=" * 60)

        print(
            f"Logged in as: "
            f"{bot.user}"
        )

        print(
            f"Provider: "
            f"{PRIMARY_AI_PROVIDER}"
        )

        print(
            f"Google model: "
            f"{GOOGLE_MODEL}"
        )

        print(
            f"Servers: "
            f"{len(bot.guilds)}"
        )

        print(
            f"[SLASH] Synced "
            f"{len(synced)} commands."
        )

        print("=" * 60)

    except Exception:
        traceback.print_exc()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN غير موجود في Environment Variables."
        )

    bot.run(
        TOKEN
)
