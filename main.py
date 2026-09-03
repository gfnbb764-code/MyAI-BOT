import os
import re
import asyncio
import traceback
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

from database import Database
from ai_engine import AIEngine


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN")

DEFAULT_PROVIDER = os.getenv("AI_PROVIDER", "google")
DEFAULT_MODEL = os.getenv("GOOGLE_MODEL", "gemini-3.5-flash-lite")

MIN_TYPING_DELAY = 3
MAX_AI_WAIT = 120

MAX_RESPONSE_LENGTH = 1900
HISTORY_LIMIT = 20

AI_SEMAPHORE = asyncio.Semaphore(2)

BOT_CHAT_COOLDOWN = 8

active_requests = set()
bot_chat_last = {}
bot_chat_locks = {}


# ============================================================
# CONSTANTS
# ============================================================

AI_MODES = {
    "normal": "عادي",
    "friendly": "ودّي",
    "active": "نشط",
    "fun": "مرح",
    "professional": "احترافي",
}

REPLY_TYPES = {
    "mention": "عند المنشن",
    "channel": "داخل قناة AI",
    "direct": "الرد المباشر",
    "auto": "تلقائي",
    "bot_chat": "محادثة البوتات",
}

CHARACTER_TYPES = {
    "normal": "عادي",
    "assistant": "مساعد",
    "friend": "صديق",
    "teacher": "معلّم",
    "professional": "احترافي",
    "funny": "مرح",
    "custom": "مخصص",
}

CHARACTER_TYPE_ALIASES = {
    "عادي": "normal",
    "مساعد": "assistant",
    "صديق": "friend",
    "معلّم": "teacher",
    "معلم": "teacher",
    "احترافي": "professional",
    "مرح": "funny",
    "مخصص": "custom",
}

SENSITIVE_KEYWORDS = [
    "كيف أؤذي",
    "كيف اقتل",
    "كيف أقتل",
    "طريقة قتل",
    "طريقة الانتحار",
    "كيف انتحر",
    "كيف أصنع سلاح",
    "اصنع قنبلة",
    "صنع قنبلة",
]


# ============================================================
# DISCORD
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,
)


# ============================================================
# DATABASE / AI
# ============================================================

db = Database()
ai = AIEngine(
    provider=DEFAULT_PROVIDER,
    model=DEFAULT_MODEL,
)


# ============================================================
# HELPERS
# ============================================================

def normalize_character_type(value: str) -> str:
    value = (value or "").strip().lower()

    if value in CHARACTER_TYPES:
        return value

    return CHARACTER_TYPE_ALIASES.get(value, "normal")


def split_response(text: str, limit: int = MAX_RESPONSE_LENGTH):
    if not text:
        return ["لم يتم الحصول على رد."]

    text = str(text).strip()

    if len(text) <= limit:
        return [text]

    parts = []

    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)

        if cut < 500:
            cut = text.rfind(" ", 0, limit)

        if cut < 1:
            cut = limit

        parts.append(text[:cut].strip())
        text = text[cut:].strip()

    if text:
        parts.append(text)

    return parts


def contains_sensitive_request(text: str) -> bool:
    lowered = (text or "").lower()

    return any(
        keyword.lower() in lowered
        for keyword in SENSITIVE_KEYWORDS
    )


def is_directed_to_bot(message: discord.Message) -> bool:
    if not bot.user:
        return False

    if bot.user.mentioned_in(message):
        return True

    content = message.content.strip().lower()

    bot_name = bot.user.name.lower()

    if content.startswith(bot_name):
        return True

    return False


def remove_bot_mention(
    message: discord.Message,
) -> str:
    content = message.content

    if bot.user:
        content = content.replace(
            f"<@{bot.user.id}>",
            "",
        )

        content = content.replace(
            f"<@!{bot.user.id}>",
            "",
        )

    return content.strip()


def get_config(guild_id: int):
    try:
        return db.get_ai_config(guild_id)
    except Exception:
        try:
            return db.get_guild_config(guild_id)
        except Exception:
            return {}


def get_active_character(guild_id: int):
    try:
        return db.get_active_character(guild_id)
    except Exception:
        return None


def can_manage_ai(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True

    roles = sorted(
        member.roles,
        key=lambda r: r.position,
        reverse=True,
    )

    top_roles = roles[:3]

    return any(
        role.permissions.manage_guild
        or role.permissions.administrator
        for role in top_roles
    )


def can_manage_characters(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True

    return member.guild_permissions.manage_guild


def make_character_options(guild_id: int):
    characters = db.get_characters(guild_id)

    options = []

    for character in characters[:25]:
        name = character.get("name", "Character")

        options.append(
            discord.SelectOption(
                label=name[:100],
                value=name[:100],
                description=(
                    character.get("description", "")
                    or "شخصية"
                )[:100],
            )
        )

    return options


# ============================================================
# AI GENERATION
# ============================================================

async def generate_chat_reply(
    message: discord.Message,
    prompt: str,
):
    guild_id = message.guild.id
    channel_id = message.channel.id
    user_id = message.author.id

    config = get_config(guild_id)

    mode = config.get(
        "ai_mode",
        "normal",
    )

    provider = config.get(
        "active_provider",
        DEFAULT_PROVIDER,
    )

    model = config.get(
        "active_model",
        DEFAULT_MODEL,
    )

    character_name = config.get(
        "active_character",
    )

    character = None

    if character_name:
        try:
            character = db.get_character(
                guild_id,
                character_name,
            )
        except Exception:
            character = None

    try:
        return await ai.generate(
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            prompt=prompt,
            character=character,
            mode=mode,
            provider=provider,
            model=model,
            history_limit=HISTORY_LIMIT,
        )

    except TypeError as exc:
        # Compatibility fallback for older AIEngine versions.
        if "history_limit" in str(exc):
            return await ai.generate(
                guild_id=guild_id,
                channel_id=channel_id,
                user_id=user_id,
                prompt=prompt,
                character=character,
                mode=mode,
                provider=provider,
                model=model,
            )

        raise


async def generate_dm_reply(
    message: discord.Message,
    prompt: str,
):
    user_id = message.author.id

    try:
        return await ai.generate(
            guild_id=0,
            channel_id=message.channel.id,
            user_id=user_id,
            prompt=prompt,
            character=None,
            mode="normal",
            provider=DEFAULT_PROVIDER,
            model=DEFAULT_MODEL,
            history_limit=HISTORY_LIMIT,
        )

    except TypeError as exc:
        if "history_limit" in str(exc):
            return await ai.generate(
                guild_id=0,
                channel_id=message.channel.id,
                user_id=user_id,
                prompt=prompt,
                character=None,
                mode="normal",
                provider=DEFAULT_PROVIDER,
                model=DEFAULT_MODEL,
            )

        raise


async def generate_with_typing_message(
    message: discord.Message,
    prompt: str,
):
    typing_message = None

    try:
        typing_message = await message.channel.send(
            "🤖 جاري التفكير..."
        )

        await asyncio.sleep(MIN_TYPING_DELAY)

        if message.guild:
            async with AI_SEMAPHORE:
                response = await asyncio.wait_for(
                    generate_chat_reply(
                        message,
                        prompt,
                    ),
                    timeout=MAX_AI_WAIT,
                )
        else:
            async with AI_SEMAPHORE:
                response = await asyncio.wait_for(
                    generate_dm_reply(
                        message,
                        prompt,
                    ),
                    timeout=MAX_AI_WAIT,
                )

        if not response:
            response = "ما قدرت أطلع رد حاليًا 😅"

        parts = split_response(response)

        await typing_message.delete()

        for part in parts:
            await message.channel.send(
                part,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        return response

    except asyncio.TimeoutError:
        if typing_message:
            try:
                await typing_message.edit(
                    content="⏱️ أخذت العملية وقتًا أطول من المتوقع."
                )
            except Exception:
                pass

    except Exception:
        traceback.print_exc()

        if typing_message:
            try:
                await typing_message.edit(
                    content="❌ حصل خطأ أثناء توليد الرد."
                )
            except Exception:
                pass


# ============================================================
# CHARACTER INFO
# ============================================================

def character_embed(character):
    name = character.get("name", "Unknown")

    embed = discord.Embed(
        title=f"🎭 {name}",
        color=discord.Color.blurple(),
    )

    description = character.get(
        "description",
        "",
    )

    personality = character.get(
        "personality",
        "",
    )

    character_type = character.get(
        "character_type",
        "normal",
    )

    speaking_style = character.get(
        "speaking_style",
        "",
    )

    provider = character.get(
        "provider",
        DEFAULT_PROVIDER,
    )

    model = character.get(
        "model",
        DEFAULT_MODEL,
    )

    if description:
        embed.add_field(
            name="📝 الوصف",
            value=description[:1024],
            inline=False,
        )

    if personality:
        embed.add_field(
            name="🧠 الشخصية",
            value=personality[:1024],
            inline=False,
        )

    embed.add_field(
        name="🎭 النوع",
        value=CHARACTER_TYPES.get(
            character_type,
            character_type,
        ),
        inline=True,
    )

    if speaking_style:
        embed.add_field(
            name="💬 أسلوب الكلام",
            value=speaking_style[:1024],
            inline=False,
        )

    embed.add_field(
        name="⚙️ Provider",
        value=str(provider),
        inline=True,
    )

    embed.add_field(
        name="🧩 Model",
        value=str(model),
        inline=True,
    )

    return embed


# ============================================================
# CHARACTER CREATOR
# ============================================================

class CharacterCreatorModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(
            title="🎭 إنشاء شخصية"
        )

        self.name_input = discord.ui.TextInput(
            label="اسم الشخصية",
            placeholder="مثال: مساعد الألعاب",
            max_length=80,
        )

        self.description_input = discord.ui.TextInput(
            label="الوصف",
            placeholder="وش وظيفة الشخصية؟",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
        )

        self.personality_input = discord.ui.TextInput(
            label="الشخصية",
            placeholder="مثال: مرح، ذكي، سريع الرد",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
        )

        self.style_input = discord.ui.TextInput(
            label="أسلوب الكلام",
            placeholder="مثال: سعودي، مختصر، حماسي",
            required=False,
            max_length=300,
        )

        self.prompt_input = discord.ui.TextInput(
            label="تعليمات إضافية",
            placeholder="أي تعليمات خاصة للشخصية",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=800,
        )

        self.add_item(self.name_input)
        self.add_item(self.description_input)
        self.add_item(self.personality_input)
        self.add_item(self.style_input)
        self.add_item(self.prompt_input)

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ هذا الأمر داخل السيرفر فقط.",
                ephemeral=True,
            )
            return

        name = self.name_input.value.strip()

        if not name:
            await interaction.response.send_message(
                "❌ لازم تكتب اسم الشخصية.",
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

        db.create_character(
            guild_id=interaction.guild.id,
            name=name,
            description=self.description_input.value.strip(),
            personality=self.personality_input.value.strip(),
            system_prompt="",
            character_type="normal",
            custom_instructions=self.prompt_input.value.strip(),
            speaking_style=self.style_input.value.strip(),
            provider=DEFAULT_PROVIDER,
            model=DEFAULT_MODEL,
            created_by=interaction.user.id,
        )

        await interaction.response.send_message(
            f"✅ تم إنشاء الشخصية **{name}** بنجاح!",
            ephemeral=True,
        )


class CharacterCreatorView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(
        label="إنشاء شخصية",
        emoji="🎭",
        style=discord.ButtonStyle.primary,
    )
    async def create_character(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.send_modal(
            CharacterCreatorModal()
        )


# ============================================================
# CHARACTER SELECT
# ============================================================

class CharacterSelect(discord.ui.Select):
    def __init__(self, guild_id: int):
        options = make_character_options(guild_id)

        if not options:
            options = [
                discord.SelectOption(
                    label="لا توجد شخصيات",
                    value="none",
                )
            ]

        super().__init__(
            placeholder="🎭 اختر الشخصية",
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        if self.values[0] == "none":
            await interaction.response.send_message(
                "❌ لا توجد شخصيات حاليًا.",
                ephemeral=True,
            )
            return

        name = self.values[0]

        try:
            character = db.get_character(
                interaction.guild.id,
                name,
            )

            if not character:
                await interaction.response.send_message(
                    "❌ الشخصية غير موجودة.",
                    ephemeral=True,
                )
                return

            db.set_active_character(
                interaction.guild.id,
                character,
            )

            db.save_ai_config(
                interaction.guild.id,
                character_name=name,
                active_character=name,
            )

            await interaction.response.send_message(
                f"✅ تم تفعيل الشخصية **{name}**.",
                ephemeral=True,
            )

        except Exception:
            traceback.print_exc()

            await interaction.response.send_message(
                "❌ حدث خطأ أثناء تفعيل الشخصية.",
                ephemeral=True,
            )


class CharacterSelectView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.add_item(CharacterSelect(guild_id))


# ============================================================
# AI DASHBOARD
# ============================================================

def dashboard_embed(guild_id: int):
    config = get_config(guild_id)

    enabled = config.get(
        "ai_enabled",
        config.get("enabled", False),
    )

    channel_id = config.get(
        "ai_channel_id",
        config.get("channel_id"),
    )

    character = config.get(
        "active_character",
        "لا توجد",
    )

    provider = config.get(
        "active_provider",
        DEFAULT_PROVIDER,
    )

    model = config.get(
        "active_model",
        DEFAULT_MODEL,
    )

    mode = config.get(
        "ai_mode",
        "normal",
    )

    embed = discord.Embed(
        title="🤖 MyAI Dashboard",
        description="لوحة تحكم الذكاء الاصطناعي",
        color=discord.Color.blurple(),
    )

    embed.add_field(
        name="🟢 الحالة",
        value="مفعّل" if enabled else "متوقف",
        inline=True,
    )

    embed.add_field(
        name="📢 القناة",
        value=(
            f"<#{channel_id}>"
            if channel_id
            else "غير محددة"
        ),
        inline=True,
    )

    embed.add_field(
        name="🎭 الشخصية",
        value=str(character),
        inline=True,
    )

    embed.add_field(
        name="⚙️ Provider",
        value=str(provider),
        inline=True,
    )

    embed.add_field(
        name="🧩 Model",
        value=str(model),
        inline=True,
    )

    embed.add_field(
        name="🎮 الوضع",
        value=AI_MODES.get(
            mode,
            mode,
        ),
        inline=True,
    )

    return embed


class DashboardChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="📢 اختر قناة الذكاء الاصطناعي",
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.news,
            ],
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        channel = self.values[0]

        db.save_ai_config(
            interaction.guild.id,
            channel_id=channel.id,
            ai_channel_id=channel.id,
        )

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild.id
            ),
            view=DashboardView(),
        )


class DashboardModeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=label,
                value=value,
            )
            for value, label in AI_MODES.items()
        ]

        super().__init__(
            placeholder="🎮 اختر وضع الذكاء الاصطناعي",
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        mode = self.values[0]

        db.save_ai_config(
            interaction.guild.id,
            ai_mode=mode,
            mode=mode,
        )

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild.id
            ),
            view=DashboardView(),
        )


class DashboardCharacterSelect(discord.ui.Select):
    def __init__(self, guild_id: int):
        options = make_character_options(guild_id)

        if not options:
            options = [
                discord.SelectOption(
                    label="لا توجد شخصيات",
                    value="none",
                )
            ]

        super().__init__(
            placeholder="🎭 اختر الشخصية النشطة",
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        name = self.values[0]

        if name == "none":
            await interaction.response.send_message(
                "❌ لا توجد شخصيات.",
                ephemeral=True,
            )
            return

        character = db.get_character(
            interaction.guild.id,
            name,
        )

        if not character:
            await interaction.response.send_message(
                "❌ الشخصية غير موجودة.",
                ephemeral=True,
            )
            return

        db.set_active_character(
            interaction.guild.id,
            character,
        )

        db.save_ai_config(
            interaction.guild.id,
            character_name=name,
            active_character=name,
        )

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild.id
            ),
            view=DashboardView(),
        )


class DashboardToggleButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="تفعيل / تعطيل",
            emoji="🔄",
            style=discord.ButtonStyle.success,
            row=2,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        config = get_config(
            interaction.guild.id
        )

        current = config.get(
            "ai_enabled",
            False,
        )

        db.save_ai_config(
            interaction.guild.id,
            ai_enabled=not current,
            enabled=not current,
        )

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild.id
            ),
            view=DashboardView(),
        )


class DashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

        self.add_item(DashboardChannelSelect())
        self.add_item(DashboardModeSelect())

        if hasattr(self, "_children"):
            pass

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if not isinstance(
            interaction.user,
            discord.Member,
        ):
            return False

        if not can_manage_ai(
            interaction.user
        ):
            await interaction.response.send_message(
                "❌ ما عندك صلاحية إدارة إعدادات AI.",
                ephemeral=True,
            )
            return False

        return True


# ============================================================
# AI SETTINGS
# ============================================================

class AISettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(
        label="تفعيل",
        emoji="🟢",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def enable(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        db.save_ai_config(
            interaction.guild.id,
            ai_enabled=True,
            enabled=True,
        )

        await interaction.response.send_message(
            "🟢 تم تفعيل AI.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="تعطيل",
        emoji="🔴",
        style=discord.ButtonStyle.danger,
        row=0,
    )
    async def disable(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        db.save_ai_config(
            interaction.guild.id,
            ai_enabled=False,
            enabled=False,
        )

        await interaction.response.send_message(
            "🔴 تم تعطيل AI.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="الشخصية",
        emoji="🎭",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def character(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.send_message(
            "اختر الشخصية:",
            view=CharacterSelectView(
                interaction.guild.id
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="القناة",
        emoji="📢",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def channel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        view = discord.ui.View(timeout=300)
        view.add_item(DashboardChannelSelect())

        await interaction.response.send_message(
            "اختر قناة AI:",
            view=view,
            ephemeral=True,
        )


# ============================================================
# SLASH COMMANDS
# ============================================================

@bot.tree.command(
    name="ai",
    description="التحدث مع الذكاء الاصطناعي",
)
@app_commands.describe(
    message="رسالتك",
)
async def ai_command(
    interaction: discord.Interaction,
    message: str,
):
    await interaction.response.defer(
        thinking=True
    )

    if contains_sensitive_request(message):
        await interaction.followup.send(
            "❌ ما أقدر أساعد في هذا النوع من الطلبات.",
            ephemeral=True,
        )
        return

    try:
        if interaction.guild:
            fake_message = interaction.message

            # استخدام كائن بسيط متوافق مع الوظائف المطلوبة.
            class InteractionMessage:
                pass

            fake_message = InteractionMessage()
            fake_message.guild = interaction.guild
            fake_message.channel = interaction.channel
            fake_message.author = interaction.user

            response = await generate_chat_reply(
                fake_message,
                message,
            )
        else:
            class InteractionMessage:
                pass

            fake_message = InteractionMessage()
            fake_message.guild = None
            fake_message.channel = interaction.channel
            fake_message.author = interaction.user

            response = await generate_dm_reply(
                fake_message,
                message,
            )

        if not response:
            response = "ما قدرت أطلع رد حاليًا 😅"

        for part in split_response(response):
            await interaction.followup.send(
                part,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    except Exception:
        traceback.print_exc()

        await interaction.followup.send(
            "❌ حدث خطأ أثناء تشغيل AI.",
            ephemeral=True,
        )


@bot.tree.command(
    name="ai_setup",
    description="فتح إعدادات الذكاء الاصطناعي",
)
async def ai_setup(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ هذا الأمر داخل السيرفر فقط.",
            ephemeral=True,
        )
        return

    if not isinstance(
        interaction.user,
        discord.Member,
    ) or not can_manage_ai(
        interaction.user
    ):
        await interaction.response.send_message(
            "❌ ما عندك صلاحية.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        embed=dashboard_embed(
            interaction.guild.id
        ),
        view=DashboardView(),
        ephemeral=True,
    )


@bot.tree.command(
    name="ai_settings",
    description="إعدادات AI",
)
async def ai_settings(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True,
        )
        return

    if not isinstance(
        interaction.user,
        discord.Member,
    ) or not can_manage_ai(
        interaction.user
    ):
        await interaction.response.send_message(
            "❌ ما عندك صلاحية.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        embed=dashboard_embed(
            interaction.guild.id
        ),
        view=AISettingsView(),
        ephemeral=True,
    )


@bot.tree.command(
    name="ai_config",
    description="عرض إعدادات AI الحالية",
)
async def ai_config(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        embed=dashboard_embed(
            interaction.guild.id
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="ai_status",
    description="عرض حالة البوت",
)
async def ai_status(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "🤖 MyAI يعمل.",
            ephemeral=True,
        )
        return

    config = get_config(
        interaction.guild.id
    )

    enabled = config.get(
        "ai_enabled",
        False,
    )

    await interaction.response.send_message(
        f"🤖 **MyAI Status**\n"
        f"الحالة: {'🟢 مفعّل' if enabled else '🔴 متوقف'}\n"
        f"Provider: `{DEFAULT_PROVIDER}`\n"
        f"Model: `{DEFAULT_MODEL}`\n"
        f"الطلبات النشطة: `{len(active_requests)}`",
        ephemeral=True,
    )


@bot.tree.command(
    name="ai_memory_clear",
    description="مسح ذاكرة AI للسيرفر",
)
async def ai_memory_clear(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True,
        )
        return

    if not isinstance(
        interaction.user,
        discord.Member,
    ) or not can_manage_ai(
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

        await interaction.response.send_message(
            "🧹 تم مسح ذاكرة AI للسيرفر.",
            ephemeral=True,
        )

    except Exception:
        traceback.print_exc()

        await interaction.response.send_message(
            "❌ تعذر مسح الذاكرة.",
            ephemeral=True,
        )


@bot.tree.command(
    name="ai_dm",
    description="تفعيل أو تعطيل AI في الخاص",
)
@app_commands.describe(
    enabled="تشغيل أو إيقاف",
)
async def ai_dm(
    interaction: discord.Interaction,
    enabled: bool,
):
    try:
        db.set_dm_enabled(
            interaction.user.id,
            enabled,
        )

        await interaction.response.send_message(
            f"{'🟢 تم تفعيل' if enabled else '🔴 تم تعطيل'} AI في الخاص.",
            ephemeral=True,
        )

    except Exception:
        traceback.print_exc()

        await interaction.response.send_message(
            "❌ حدث خطأ.",
            ephemeral=True,
        )


@bot.tree.command(
    name="character_creator",
    description="إنشاء شخصية AI",
)
async def character_creator(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        "🎭 أنشئ شخصيتك:",
        view=CharacterCreatorView(),
        ephemeral=True,
    )


@bot.tree.command(
    name="character_type",
    description="تغيير نوع شخصية",
)
@app_commands.describe(
    name="اسم الشخصية",
    character_type="نوع الشخصية",
)
async def character_type(
    interaction: discord.Interaction,
    name: str,
    character_type: str,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True,
        )
        return

    character = db.get_character(
        interaction.guild.id,
        name,
    )

    if not character:
        await interaction.response.send_message(
            "❌ الشخصية غير موجودة.",
            ephemeral=True,
        )
        return

    normalized = normalize_character_type(
        character_type
    )

    db.update_character(
        interaction.guild.id,
        name,
        character_type=normalized,
    )

    await interaction.response.send_message(
        f"✅ تم تغيير نوع **{name}** إلى "
        f"**{CHARACTER_TYPES.get(normalized, normalized)}**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="character_info",
    description="معلومات شخصية",
)
@app_commands.describe(
    name="اسم الشخصية",
)
async def character_info(
    interaction: discord.Interaction,
    name: str,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True,
        )
        return

    character = db.get_character(
        interaction.guild.id,
        name,
    )

    if not character:
        await interaction.response.send_message(
            "❌ الشخصية غير موجودة.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        embed=character_embed(character),
        ephemeral=True,
    )


@bot.tree.command(
    name="character_use",
    description="تفعيل شخصية",
)
@app_commands.describe(
    name="اسم الشخصية",
)
async def character_use(
    interaction: discord.Interaction,
    name: str,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True,
        )
        return

    character = db.get_character(
        interaction.guild.id,
        name,
    )

    if not character:
        await interaction.response.send_message(
            "❌ الشخصية غير موجودة.",
            ephemeral=True,
        )
        return

    db.set_active_character(
        interaction.guild.id,
        character,
    )

    db.save_ai_config(
        interaction.guild.id,
        character_name=name,
        active_character=name,
    )

    await interaction.response.send_message(
        f"✅ تم تفعيل **{name}**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="character_list",
    description="عرض الشخصيات",
)
async def character_list(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True,
        )
        return

    characters = db.get_characters(
        interaction.guild.id
    )

    if not characters:
        await interaction.response.send_message(
            "📭 لا توجد شخصيات.",
            ephemeral=True,
        )
        return

    lines = []

    for index, character in enumerate(
        characters[:25],
        start=1,
    ):
        name = character.get(
            "name",
            "Unknown",
        )

        ctype = character.get(
            "character_type",
            "normal",
        )

        lines.append(
            f"**{index}. {name}** — "
            f"{CHARACTER_TYPES.get(ctype, ctype)}"
        )

    embed = discord.Embed(
        title="🎭 الشخصيات",
        description="\n".join(lines),
        color=discord.Color.blurple(),
    )

    await interaction.response.send_message(
        embed=embed,
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
    interaction: discord.Interaction,
    name: str,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True,
        )
        return

    character = db.get_character(
        interaction.guild.id,
        name,
    )

    if not character:
        await interaction.response.send_message(
            "❌ الشخصية غير موجودة.",
            ephemeral=True,
        )
        return

    owner_id = db.get_character_owner(
        interaction.guild.id,
        name,
    )

    allowed = (
        owner_id == interaction.user.id
        or (
            isinstance(
                interaction.user,
                discord.Member,
            )
            and can_manage_characters(
                interaction.user
            )
        )
    )

    if not allowed:
        await interaction.response.send_message(
            "❌ فقط صاحب الشخصية أو الإدارة يستطيع حذفها.",
            ephemeral=True,
        )
        return

    db.delete_character(
        interaction.guild.id,
        name,
    )

    config = get_config(
        interaction.guild.id
    )

    if config.get("active_character") == name:
        db.save_ai_config(
            interaction.guild.id,
            active_character=None,
            character_name=None,
        )

    await interaction.response.send_message(
        f"🗑️ تم حذف **{name}**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="character_edit",
    description="تعديل شخصية",
)
@app_commands.describe(
    name="اسم الشخصية",
    description="الوصف الجديد",
    personality="الشخصية الجديدة",
    speaking_style="أسلوب الكلام الجديد",
)
async def character_edit(
    interaction: discord.Interaction,
    name: str,
    description: Optional[str] = None,
    personality: Optional[str] = None,
    speaking_style: Optional[str] = None,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True,
        )
        return

    character = db.get_character(
        interaction.guild.id,
        name,
    )

    if not character:
        await interaction.response.send_message(
            "❌ الشخصية غير موجودة.",
            ephemeral=True,
        )
        return

    owner_id = db.get_character_owner(
        interaction.guild.id,
        name,
    )

    allowed = (
        owner_id == interaction.user.id
        or (
            isinstance(
                interaction.user,
                discord.Member,
            )
            and can_manage_characters(
                interaction.user
            )
        )
    )

    if not allowed:
        await interaction.response.send_message(
            "❌ ما عندك صلاحية تعديل هذه الشخصية.",
            ephemeral=True,
        )
        return

    updates = {}

    if description is not None:
        updates["description"] = description

    if personality is not None:
        updates["personality"] = personality

    if speaking_style is not None:
        updates["speaking_style"] = speaking_style

    if not updates:
        await interaction.response.send_message(
            "⚠️ ما أرسلت أي تعديل.",
            ephemeral=True,
        )
        return

    db.update_character(
        interaction.guild.id,
        name,
        **updates,
    )

    await interaction.response.send_message(
        f"✅ تم تعديل **{name}**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="ai_dashboard",
    description="فتح لوحة تحكم MyAI",
)
async def ai_dashboard(
    interaction: discord.Interaction,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True,
        )
        return

    if not isinstance(
        interaction.user,
        discord.Member,
    ) or not can_manage_ai(
        interaction.user
    ):
        await interaction.response.send_message(
            "❌ ما عندك صلاحية.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        embed=dashboard_embed(
            interaction.guild.id
        ),
        view=DashboardView(),
        ephemeral=True,
    )


# ============================================================
# MESSAGE HANDLER
# ============================================================

@bot.event
async def on_message(
    message: discord.Message,
):
    if message.author.bot:
        # السماح بمحادثات bot-to-bot فقط إذا كانت مفعلة.
        if (
            message.guild
            and message.author != bot.user
        ):
            config = get_config(
                message.guild.id
            )

            if config.get(
                "reply_type"
            ) == "bot_chat":
                now = asyncio.get_running_loop().time()

                last = bot_chat_last.get(
                    message.guild.id,
                    0,
                )

                if now - last >= BOT_CHAT_COOLDOWN:
                    bot_chat_last[
                        message.guild.id
                    ] = now

                    try:
                        await generate_with_typing_message(
                            message,
                            message.content,
                        )
                    except Exception:
                        traceback.print_exc()

        return

    if message.guild is None:
        try:
            enabled = db.get_dm_enabled(
                message.author.id
            )
        except Exception:
            enabled = False

        if enabled and message.content.strip():
            await generate_with_typing_message(
                message,
                message.content.strip(),
            )

        return

    await bot.process_commands(message)

    config = get_config(
        message.guild.id
    )

    enabled = config.get(
        "ai_enabled",
        False,
    )

    if not enabled:
        return

    ai_channel_id = config.get(
        "ai_channel_id",
        config.get("channel_id"),
    )

    reply_type = config.get(
        "reply_type",
        "mention",
    )

    should_reply = False

    if reply_type == "mention":
        should_reply = is_directed_to_bot(
            message
        )

    elif reply_type == "channel":
        should_reply = (
            ai_channel_id == message.channel.id
        )

    elif reply_type == "direct":
        should_reply = is_directed_to_bot(
            message
        )

    elif reply_type == "auto":
        should_reply = (
            ai_channel_id == message.channel.id
            or is_directed_to_bot(message)
        )

    if not should_reply:
        return

    prompt = remove_bot_mention(
        message
    )

    if not prompt:
        prompt = "مرحبا"

    if contains_sensitive_request(prompt):
        await message.reply(
            "❌ ما أقدر أساعد في هذا النوع من الطلبات.",
            mention_author=False,
        )
        return

    request_key = (
        message.guild.id,
        message.channel.id,
        message.author.id,
    )

    if request_key in active_requests:
        return

    active_requests.add(request_key)

    try:
        await generate_with_typing_message(
            message,
            prompt,
        )

    finally:
        active_requests.discard(
            request_key
        )


# ============================================================
# COMMAND ERROR
# ============================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    traceback.print_exc()

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
    print("=" * 60)
    print("MyAI BOT")
    print("=" * 60)

    print(
        f"Logged in as: {bot.user}"
    )

    print(
        f"Provider: {DEFAULT_PROVIDER}"
    )

    print(
        f"Google model: {DEFAULT_MODEL}"
    )

    print(
        f"Servers: {len(bot.guilds)}"
    )

    try:
        synced = await bot.tree.sync()

        print(
            f"[SLASH] Synced {len(synced)} commands."
        )

    except Exception:
        traceback.print_exc()

    print("=" * 60)


# ============================================================
# START
# ============================================================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN/TOKEN environment variable is missing."
    )

bot.run(TOKEN)
