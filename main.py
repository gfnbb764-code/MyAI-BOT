import os
import re
import asyncio
import random
import traceback

import discord
from discord.ext import commands
from discord import app_commands

from database import Database
from ai_engine import AIEngine


# ==========================================================
# CONFIG
# ==========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

PRIMARY_AI_PROVIDER = os.getenv(
    "PRIMARY_AI_PROVIDER",
    "google"
).lower().strip()

GOOGLE_MODEL = os.getenv(
    "GOOGLE_MODEL",
    "gemini-3.5-flash-lite"
)


# ==========================================================
# AI MODES
# ==========================================================

AI_MODES = {
    "normal": {
        "temperature": 0.7,
        "description": "ردود طبيعية ومتوازنة"
    },
    "friendly": {
        "temperature": 0.85,
        "description": "ردود ودية وحماسية"
    },
    "active": {
        "temperature": 0.8,
        "description": "ردود نشطة وتفاعلية"
    },
    "fun": {
        "temperature": 0.95,
        "description": "ردود مرحة"
    },
    "professional": {
        "temperature": 0.45,
        "description": "ردود رسمية"
    }
}


# ==========================================================
# REPLY TYPES
# ==========================================================

REPLY_TYPES = {
    "mention",
    "channel",
    "direct",
    "auto",
    "bot_chat",
}


# ==========================================================
# CHARACTER TYPES
# ==========================================================

CHARACTER_TYPES = {
    "normal": {
        "name": "عادي",
        "description": "شخصية متوازنة وطبيعية."
    },

    "calm": {
        "name": "هادئ",
        "description": "هادئ، متزن، ولا يتسرع في الرد."
    },

    "smart": {
        "name": "ذكي",
        "description": "تحليلي، دقيق، ويشرح الأمور بوضوح."
    },

    "funny": {
        "name": "مرح",
        "description": "مرح ويحب إضافة لمسات خفيفة ومضحكة."
    },

    "friendly": {
        "name": "ودود",
        "description": "لطيف، متعاون، ومريح في الحوار."
    },

    "formal": {
        "name": "رسمي",
        "description": "رسمي، مرتب، وواضح في كلامه."
    },

    "energetic": {
        "name": "حماسي",
        "description": "نشط ومتحمس ويجعل الحوار أكثر تفاعلًا."
    },

    "rude": {
        "name": "غير مهذب",
        "description": "مباشر وصريح وقليل المجاملة، مع تجنب الإهانات المؤذية."
    },

    "mischievous": {
        "name": "مشاغب",
        "description": "مشاغب ويميل للمزاح والمقالب الكلامية الخفيفة."
    },

    "curious": {
        "name": "فضولي",
        "description": "فضولي ويحب طرح الأسئلة واستكشاف التفاصيل."
    },

    "creative": {
        "name": "إبداعي",
        "description": "خيالي ويقدم أفكارًا وطرقًا غير تقليدية."
    },

    "professional": {
        "name": "احترافي",
        "description": "دقيق ومنظم ويركز على الحلول العملية."
    },
}


# ==========================================================
# SENSITIVE ACTIONS
# ==========================================================

SENSITIVE_ACTIONS = {
    "manage_roles",
    "manage_channels",
    "edit_channel_permissions",
    "create_role",
    "delete_role",
    "edit_role",
    "assign_role",
    "remove_role",
    "create_channel",
    "delete_channel",
    "edit_channel",
    "manage_guild",
    "ban",
    "kick",
    "timeout",
}


SENSITIVE_KEYWORDS = (
    "احذف الرتبة",
    "حذف الرتبة",
    "أنشئ رتبة",
    "انشئ رتبة",
    "إنشاء رتبة",
    "انشاء رتبة",
    "عدل الرتبة",
    "عدّل الرتبة",
    "غير الرتبة",
    "غيّر الرتبة",
    "صلاحيات الرتبة",
    "صلاحيات الروم",
    "صلاحيات القناة",
    "غيّر صلاحيات",
    "غير صلاحيات",
    "احذف الروم",
    "حذف الروم",
    "احذف القناة",
    "حذف القناة",
    "أنشئ روم",
    "انشئ روم",
    "إنشاء روم",
    "انشاء روم",
    "أنشئ قناة",
    "انشئ قناة",
    "إنشاء قناة",
    "انشاء قناة",
    "عدل الروم",
    "عدّل الروم",
    "عدل القناة",
    "عدّل القناة",
    "غيّر اسم الروم",
    "غير اسم الروم",
    "غيّر اسم القناة",
    "غير اسم القناة",
    "بان",
    "حظر",
    "طرد",
    "كيك",
    "تايم اوت",
    "تايم أوت",
    "timeout",
    "ban",
    "kick",
    "delete role",
    "create role",
    "edit role",
    "manage roles",
    "manage channels",
    "permissions",
)


# ==========================================================
# DISCORD INTENTS
# ==========================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.presences = True
intents.messages = True
intents.message_content = True


# ==========================================================
# DATABASE / AI
# ==========================================================

db = Database()
ai = AIEngine(db)


# ==========================================================
# PERFORMANCE / REQUEST CONTROL
# ==========================================================

AI_SEMAPHORE = asyncio.Semaphore(3)

ACTIVE_REQUESTS = set()

AI_TIMEOUT = 35

MIN_TYPING_TIME = 3.0
MAX_TYPING_TIME = 5.0


# ==========================================================
# BOT
# ==========================================================

class MyAIBot(commands.Bot):

    def __init__(self):

        super().__init__(
            command_prefix="!",
            intents=intents
        )

    async def setup_hook(self):

        try:

            synced = await self.tree.sync()

            print(
                f"Synced {len(synced)} slash commands."
            )

        except Exception as e:

            print(
                f"❌ Slash command sync error: {e}"
            )


bot = MyAIBot()


# ==========================================================
# GENERAL HELPERS
# ==========================================================

def row_to_dict(row):

    if row is None:
        return None

    if isinstance(row, dict):
        return dict(row)

    try:
        return dict(row)

    except Exception:

        try:
            return {
                key: row[key]
                for key in row.keys()
            }

        except Exception:
            return None


def get_config(guild_id):

    return db.get_ai_config(
        guild_id
    )


def get_character(
    guild_id,
    name
):

    if not name:
        return None

    return row_to_dict(
        db.get_character(
            guild_id,
            name
        )
    )


def get_active_character(
    guild_id
):

    return row_to_dict(
        db.get_active_character(
            guild_id
        )
    )


def normalize_text(text):

    return re.sub(
        r"\s+",
        " ",
        str(text or "")
    ).strip()


def clean_mentions(
    text,
    bot_user=None
):

    text = str(text or "")

    if bot_user:

        text = text.replace(
            f"<@{bot_user.id}>",
            ""
        )

        text = text.replace(
            f"<@!{bot_user.id}>",
            ""
        )

    return normalize_text(
        text
    )


def split_message(
    text,
    limit=1900
):

    text = str(text or "")

    if not text:
        return []

    parts = []

    while len(text) > limit:

        cut = text.rfind(
            "\n",
            0,
            limit
        )

        if cut < 500:

            cut = text.rfind(
                " ",
                0,
                limit
            )

        if cut < 500:

            cut = limit

        parts.append(
            text[:cut].strip()
        )

        text = text[cut:].strip()

    if text:
        parts.append(text)

    return parts


def normalize_channel_id(
    value
):

    try:
        return int(value)

    except Exception:
        return None


def channel_matches(
    message,
    config
):

    configured = normalize_channel_id(
        config.get("channel_id")
    )

    if configured is None:
        return True

    return (
        message.channel.id
        == configured
    )


def is_directed_to_bot(
    message
):

    if not bot.user:
        return False

    if bot.user in message.mentions:
        return True

    content = (
        message.content
        or ""
    ).lower().strip()

    bot_name = (
        bot.user.name
        or ""
    ).lower()

    return (
        bool(bot_name)
        and content.startswith(bot_name)
    )


# ==========================================================
# MANAGEMENT PERMISSIONS
# ==========================================================

def has_management_permission(
    member
):

    if not isinstance(
        member,
        discord.Member
    ):
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


def can_manage_ai(
    obj
):

    if isinstance(
        obj,
        discord.Interaction
    ):

        member = obj.user

    elif isinstance(
        obj,
        discord.Message
    ):

        member = obj.author

    else:

        return False

    return has_management_permission(
        member
    )


# ==========================================================
# TOP 3 ROLE SECURITY
# ==========================================================

def get_top_three_roles(
    guild
):

    if guild is None:
        return []

    roles = [
        role
        for role in guild.roles
        if not role.is_default()
    ]

    roles.sort(
        key=lambda role: role.position,
        reverse=True
    )

    return roles[:3]


def get_top_role_rank(
    member
):

    if not isinstance(
        member,
        discord.Member
    ):
        return None

    top_three = get_top_three_roles(
        member.guild
    )

    member_role_ids = {
        role.id
        for role in member.roles
    }

    for index, role in enumerate(
        top_three,
        start=1
    ):

        if role.id in member_role_ids:
            return index

    return None


def member_has_top_three_role(
    member
):

    return (
        get_top_role_rank(member)
        is not None
    )


def is_sensitive_action(
    action
):

    if not action:
        return False

    return (
        str(action)
        .strip()
        .lower()
        in SENSITIVE_ACTIONS
    )


def is_sensitive_request(
    text
):

    normalized = normalize_text(
        text
    ).lower()

    return any(
        keyword.lower()
        in normalized
        for keyword in SENSITIVE_KEYWORDS
    )


def security_check(
    member,
    action=None
):

    if not isinstance(
        member,
        discord.Member
    ):

        return (
            False,
            "المستخدم ليس عضوًا صالحًا في السيرفر."
        )

    if (
        member.guild.owner_id
        == member.id
    ):

        return (
            True,
            "server_owner"
        )

    if not member_has_top_three_role(
        member
    ):

        return (
            False,
            "هذا الإجراء حساس ومسموح فقط لأعلى 3 رتب في السيرفر."
        )

    if action == "manage_roles":

        if not member.guild_permissions.manage_roles:

            return (
                False,
                "تحتاج إلى Manage Roles."
            )

    elif action == "manage_channels":

        if not member.guild_permissions.manage_channels:

            return (
                False,
                "تحتاج إلى Manage Channels."
            )

    elif action == "manage_guild":

        if not member.guild_permissions.manage_guild:

            return (
                False,
                "تحتاج إلى Manage Server."
            )

    elif action == "ban":

        if not member.guild_permissions.ban_members:

            return (
                False,
                "تحتاج إلى Ban Members."
            )

    elif action == "kick":

        if not member.guild_permissions.kick_members:

            return (
                False,
                "تحتاج إلى Kick Members."
            )

    elif action == "timeout":

        if not member.guild_permissions.moderate_members:

            return (
                False,
                "تحتاج إلى Moderate Members."
            )

    return (
        True,
        "authorized"
    )


# ==========================================================
# CHARACTER SECURITY
# ==========================================================

def owns_character(
    interaction,
    character
):

    if not interaction.guild:
        return False

    if not character:
        return False

    owner_id = character.get(
        "created_by"
    )

    try:
        owner_id = int(owner_id)

    except Exception:
        return False

    return (
        owner_id
        == interaction.user.id
    )


# ==========================================================
# BOT ROLE HIERARCHY
# ==========================================================

def bot_can_manage_role(
    guild,
    role
):

    me = guild.me

    if me is None:
        return False

    if role.is_default():
        return False

    return role < me.top_role


def bot_can_manage_member(
    guild,
    member
):

    me = guild.me

    if me is None:
        return False

    return (
        member.top_role
        < me.top_role
    )


# ==========================================================
# AI GENERATION - SERVER
# ==========================================================

async def generate_chat_reply(
    message,
    config
):

    character_name = (
        config.get("character_name")
        or "مساعد السيرفر جيميناي"
    )

    ai_mode = (
        config.get("mode")
        or "normal"
    )

    if ai_mode not in AI_MODES:

        print(
            f"⚠️ Unknown AI mode: {ai_mode}"
        )

        ai_mode = "normal"

    provider = (
        config.get("provider")
        or PRIMARY_AI_PROVIDER
    )

    model = (
        config.get("model")
        or GOOGLE_MODEL
    )

    user_text = clean_mentions(
        message.content,
        bot.user
    )

    if not user_text:
        user_text = "تكلم معي."

    print(
        "🧠 GENERATING AI RESPONSE"
    )

    print(
        f"🎭 Character : {character_name}"
    )

    print(
        f"⚙️ Mode      : {ai_mode}"
    )

    print(
        f"🤖 Provider  : {provider}"
    )

    print(
        f"🧠 Model     : {model}"
    )

    async with AI_SEMAPHORE:

        response = await asyncio.wait_for(

            ai.generate(

                guild_id=message.guild.id,

                channel_id=message.channel.id,

                user_id=message.author.id,

                character_name=character_name,

                prompt=user_text,

                mode=ai_mode,

                provider=provider,

                model=model,
            ),

            timeout=AI_TIMEOUT
        )

    return response


# ==========================================================
# AI GENERATION - DM
# ==========================================================

async def generate_dm_reply(
    message
):

    user_text = clean_mentions(
        message.content,
        bot.user
    )

    if not user_text:
        return None

    print(
        "🧠 GENERATING DM AI RESPONSE"
    )

    print(
        f"👤 User      : {message.author}"
    )

    print(
        f"📝 Prompt    : {user_text}"
    )

    print(
        f"🎭 Character : {db.DM_CHARACTER_NAME}"
    )

    print(
        "🤖 Provider  : google"
    )

    print(
        f"🧠 Model     : {GOOGLE_MODEL}"
    )

    async with AI_SEMAPHORE:

        response = await asyncio.wait_for(

            ai.generate(

                guild_id=db.DM_GUILD_ID,

                channel_id=message.channel.id,

                user_id=message.author.id,

                character_name=db.DM_CHARACTER_NAME,

                prompt=user_text,

                mode="friendly",

                provider="google",

                model=GOOGLE_MODEL,
            ),

            timeout=AI_TIMEOUT
        )

    return response


# ==========================================================
# AI WAITING MESSAGE
# ==========================================================

async def generate_with_typing_message(
    message,
    generator,
    character_name
):

    started_at = asyncio.get_running_loop().time()

    waiting_message = None

    try:

        waiting_message = await message.reply(
            f"**{character_name} يكتب...**",
            mention_author=False
        )

    except discord.HTTPException as e:

        print(
            f"⚠️ Could not create typing message: {e}"
        )

    generation_task = asyncio.create_task(
        generator()
    )

    minimum_time = random.uniform(
        MIN_TYPING_TIME,
        MAX_TYPING_TIME
    )

    try:

        if waiting_message:

            try:

                response, _ = await asyncio.gather(

                    generation_task,

                    asyncio.sleep(
                        minimum_time
                    )
                )

            except Exception:

                await asyncio.sleep(
                    max(
                        0,
                        minimum_time
                        - (
                            asyncio.get_running_loop().time()
                            - started_at
                        )
                    )
                )

                raise

        else:

            response = await generation_task

    except asyncio.TimeoutError:

        response = (
            "⏱️ عذرًا، استغرق توليد الرد وقتًا أطول من المتوقع. "
            "حاول مرة ثانية."
        )

    except Exception as e:

        print(
            f"❌ AI request failed: {e}"
        )

        traceback.print_exc()

        response = (
            "⚠️ حصل خطأ مؤقت أثناء تجهيز الرد. "
            "جرّب مرة ثانية بعد قليل."
        )

    if not response:

        response = (
            "⚠️ لم يتم إنشاء رد."
        )

    response = str(
        response
    ).strip()

    parts = split_message(
        response
    )

    if not parts:

        parts = [
            "⚠️ لم يتم إنشاء رد."
        ]

    if waiting_message:

        try:

            await waiting_message.edit(
                content=parts[0]
            )

            for part in parts[1:]:

                try:

                    await message.channel.send(
                        part
                    )

                except discord.HTTPException as e:

                    print(
                        f"❌ Failed sending extra response part: {e}"
                    )

        except discord.HTTPException as e:

            print(
                f"❌ Failed editing waiting message: {e}"
            )

            await send_ai_response(
                message,
                response
            )

    else:

        await send_ai_response(
            message,
            response
        )

    elapsed = (
        asyncio.get_running_loop().time()
        - started_at
    )

    print(
        f"⏱️ AI response completed in {elapsed:.2f}s"
    )

    return response


# ==========================================================
# SEND AI RESPONSE
# ==========================================================

async def send_ai_response(
    message,
    response
):

    if not response:
        return

    response = str(
        response
    ).strip()

    if not response:
        return

    for part in split_message(
        response
    ):

        try:

            await message.reply(
                part,
                mention_author=False
            )

        except discord.HTTPException as e:

            print(
                f"❌ Failed sending AI response: {e}"
            )


# ==========================================================
# /ai
# ==========================================================

@bot.tree.command(
    name="ai",
    description="تفعيل أو تعطيل نظام MyAI"
)
@app_commands.describe(
    enabled="هل تريد تشغيل MyAI؟"
)
async def ai_command(
    interaction: discord.Interaction,
    enabled: bool
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    if not can_manage_ai(
        interaction
    ):

        await interaction.response.send_message(
            "🛡️ ليس لديك صلاحية إدارة MyAI.",
            ephemeral=True
        )

        return

    config = db.save_ai_config(
        interaction.guild.id,
        enabled=enabled
    )

    status = (
        "🟢 مفعّل"
        if config["enabled"]
        else "🔴 معطّل"
    )

    await interaction.response.send_message(
        f"🤖 MyAI: **{status}**",
        ephemeral=True
    )


# ==========================================================
# /ai_setup
# ==========================================================

@bot.tree.command(
    name="ai_setup",
    description="إعداد قناة MyAI"
)
@app_commands.describe(
    channel="القناة التي سيعمل فيها MyAI"
)
async def ai_setup(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    if not can_manage_ai(
        interaction
    ):

        await interaction.response.send_message(
            "🛡️ ليس لديك صلاحية إدارة MyAI.",
            ephemeral=True
        )

        return

    db.save_ai_config(
        interaction.guild.id,
        channel_id=channel.id
    )

    await interaction.response.send_message(
        f"✅ تم تحديد قناة MyAI: {channel.mention}",
        ephemeral=True
    )


# ==========================================================
# /ai_config
# TOP 3 ROLES ONLY
# ==========================================================

@bot.tree.command(
    name="ai_config",
    description="عرض إعدادات MyAI"
)
async def ai_config(
    interaction: discord.Interaction
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    if not member_has_top_three_role(
        interaction.user
    ):

        await interaction.response.send_message(
            "🛡️ هذا الأمر متاح فقط لأعضاء أعلى 3 رتب في السيرفر.",
            ephemeral=True
        )

        return

    config = get_config(
        interaction.guild.id
    )

    character = (
        config.get("character_name")
        or "غير محددة"
    )

    channel_id = config.get(
        "channel_id"
    )

    channel = (
        f"<#{channel_id}>"
        if channel_id
        else "كل القنوات"
    )

    mode = (
        config.get("mode")
        or "normal"
    )

    mode_description = (
        AI_MODES.get(
            mode,
            AI_MODES["normal"]
        )["description"]
    )

    enabled = (
        "🟢 مفعّل"
        if config.get("enabled")
        else "🔴 معطّل"
    )

    embed = discord.Embed(
        title="🤖 MyAI Configuration",
        description=(
            "إعدادات نظام الذكاء الاصطناعي "
            "لهذا السيرفر."
        )
    )

    embed.add_field(
        name="الحالة",
        value=enabled,
        inline=True
    )

    embed.add_field(
        name="الشخصية",
        value=f"`{character}`",
        inline=True
    )

    embed.add_field(
        name="الوضع",
        value=(
            f"`{mode}`\n"
            f"{mode_description}"
        ),
        inline=True
    )

    embed.add_field(
        name="نوع الرد",
        value=f"`{config.get('reply_type', 'mention')}`",
        inline=True
    )

    embed.add_field(
        name="القناة",
        value=channel,
        inline=True
    )

    embed.add_field(
        name="Provider",
        value=f"`{config.get('provider', PRIMARY_AI_PROVIDER)}`",
        inline=True
    )

    embed.add_field(
        name="Model",
        value=f"`{config.get('model', GOOGLE_MODEL)}`",
        inline=False
    )

    embed.set_footer(
        text="🛡️ ai_config متاح فقط لأعلى 3 رتب."
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ==========================================================
# CHARACTER TYPE CHOICES
# ==========================================================

CHARACTER_CHOICES = [
    app_commands.Choice(
        name=value["name"],
        value=key
    )
    for key, value in CHARACTER_TYPES.items()
]


# ==========================================================
# /character_create
# ALL MEMBERS
# ==========================================================

@bot.tree.command(
    name="character_create",
    description="إنشاء شخصية MyAI جديدة"
)
@app_commands.describe(
    name="اسم الشخصية",
    character_type="نوع الشخصية",
    custom_instructions="تعليمات مخصصة للشخصية",
    speaking_style="كيف تريد أن يتكلم البوت؟"
)
@app_commands.choices(
    character_type=CHARACTER_CHOICES
)
async def character_create(
    interaction: discord.Interaction,
    name: str,
    character_type: app_commands.Choice[str],
    custom_instructions: str,
    speaking_style: str
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    name = normalize_text(
        name
    )

    custom_instructions = str(
        custom_instructions or ""
    ).strip()

    speaking_style = str(
        speaking_style or ""
    ).strip()

    type_data = CHARACTER_TYPES.get(
        character_type.value
    )

    if not type_data:

        await interaction.response.send_message(
            "❌ نوع الشخصية غير صالح.",
            ephemeral=True
        )

        return

    try:

        character = db.create_character(

            guild_id=interaction.guild.id,

            name=name,

            personality=type_data["description"],

            character_type=character_type.value,

            custom_instructions=custom_instructions,

            speaking_style=speaking_style,

            provider="google",

            model=GOOGLE_MODEL,

            created_by=interaction.user.id
        )

        await interaction.response.send_message(
            "✅ **تم إنشاء الشخصية بنجاح!**\n\n"
            f"🎭 الاسم: **{character['name']}**\n"
            f"🧩 النوع: **{type_data['name']}**\n"
            f"👤 المالك: {interaction.user.mention}\n\n"
            "يمكنك تعديلها لاحقًا باستخدام "
            "`/character_edit`.",
            ephemeral=True
        )

    except Exception as e:

        print(
            f"❌ Character create error: {e}"
        )

        await interaction.response.send_message(
            f"❌ {e}",
            ephemeral=True
        )


# ==========================================================
# /character_edit
# OWNER ONLY
# ==========================================================

@bot.tree.command(
    name="character_edit",
    description="تعديل شخصيتك فقط"
)
@app_commands.describe(
    character="اسم الشخصية التي تملكها",
    character_type="نوع الشخصية الجديد",
    custom_instructions="التعليمات المخصصة الجديدة",
    speaking_style="أسلوب الكلام الجديد"
)
@app_commands.choices(
    character_type=CHARACTER_CHOICES
)
async def character_edit(
    interaction: discord.Interaction,
    character: str,
    character_type: app_commands.Choice[str] = None,
    custom_instructions: str = None,
    speaking_style: str = None
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    character_data = get_character(
        interaction.guild.id,
        character
    )

    if not character_data:

        await interaction.response.send_message(
            "❌ الشخصية غير موجودة.",
            ephemeral=True
        )

        return

    if not owns_character(
        interaction,
        character_data
    ):

        await interaction.response.send_message(
            "🔒 لا يمكنك تعديل شخصية شخص آخر.",
            ephemeral=True
        )

        return

    if character_type is None and custom_instructions is None and speaking_style is None:

        await interaction.response.send_message(
            "ℹ️ لم ترسل أي تغيير.",
            ephemeral=True
        )

        return

    try:

        updated = db.update_character(

            guild_id=interaction.guild.id,

            name=character,

            character_type=(
                character_type.value
                if character_type
                else None
            ),

            custom_instructions=(
                custom_instructions
                if custom_instructions is not None
                else None
            ),

            speaking_style=(
                speaking_style
                if speaking_style is not None
                else None
            ),

            editor_id=interaction.user.id
        )

        await interaction.response.send_message(
            f"✅ تم تحديث الشخصية **{updated['name']}**.",
            ephemeral=True
        )

    except Exception as e:

        print(
            f"❌ Character edit error: {e}"
        )

        await interaction.response.send_message(
            f"❌ {e}",
            ephemeral=True
        )


# ==========================================================
# /character_delete
# OWNER ONLY
# ==========================================================

@bot.tree.command(
    name="character_delete",
    description="حذف شخصيتك فقط"
)
@app_commands.describe(
    character="اسم الشخصية التي تريد حذفها"
)
async def character_delete(
    interaction: discord.Interaction,
    character: str
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    character_data = get_character(
        interaction.guild.id,
        character
    )

    if not character_data:

        await interaction.response.send_message(
            "❌ الشخصية غير موجودة.",
            ephemeral=True
        )

        return

    if not owns_character(
        interaction,
        character_data
    ):

        await interaction.response.send_message(
            "🔒 لا يمكنك حذف شخصية شخص آخر.",
            ephemeral=True
        )

        return

    try:

        db.delete_character(
            guild_id=interaction.guild.id,
            name=character,
            requester_id=interaction.user.id
        )

        await interaction.response.send_message(
            f"🗑️ تم حذف الشخصية **{character}**.",
            ephemeral=True
        )

    except Exception as e:

        print(
            f"❌ Character delete error: {e}"
        )

        await interaction.response.send_message(
            f"❌ {e}",
            ephemeral=True
        )


# ==========================================================
# /character_list
# ==========================================================

@bot.tree.command(
    name="character_list",
    description="عرض شخصيات MyAI"
)
async def character_list(
    interaction: discord.Interaction
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    characters = db.get_characters(
        interaction.guild.id
    )

    if not characters:

        await interaction.response.send_message(
            "📭 لا توجد شخصيات.",
            ephemeral=True
        )

        return

    lines = []

    for index, character in enumerate(
        characters,
        start=1
    ):

        item = row_to_dict(
            character
        )

        if not item:
            continue

        char_type = (
            item.get("character_type")
            or "normal"
        )

        type_name = (
            CHARACTER_TYPES.get(
                char_type,
                CHARACTER_TYPES["normal"]
            )["name"]
        )

        owner_id = item.get(
            "created_by"
        )

        owner = (
            f"<@{owner_id}>"
            if owner_id and int(owner_id) != 0
            else "System"
        )

        lines.append(
            f"`{index}` • **{item['name']}** "
            f"• {type_name} "
            f"• 👤 {owner}"
        )

    await interaction.response.send_message(
        "🤖 **شخصيات MyAI**\n\n"
        + "\n".join(lines),
        ephemeral=True
    )


# ==========================================================
# /character_use
# MANAGEMENT ONLY
# ==========================================================

@bot.tree.command(
    name="character_use",
    description="اختيار شخصية MyAI للسيرفر"
)
@app_commands.describe(
    character="اسم الشخصية"
)
async def character_use(
    interaction: discord.Interaction,
    character: str
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    if not can_manage_ai(
        interaction
    ):

        await interaction.response.send_message(
            "🛡️ ليس لديك صلاحية تغيير الشخصية.",
            ephemeral=True
        )

        return

    try:

        selected = db.set_active_character(
            interaction.guild.id,
            character
        )

        await interaction.response.send_message(
            f"✅ الشخصية الحالية: **{selected['character_name']}**",
            ephemeral=True
        )

    except Exception as e:

        print(
            f"❌ Character use error: {e}"
        )

        await interaction.response.send_message(
            f"❌ {e}",
            ephemeral=True
        )


# ==========================================================
# /ai_status
# ==========================================================

@bot.tree.command(
    name="ai_status",
    description="عرض حالة MyAI"
)
async def ai_status(
    interaction: discord.Interaction
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    config = get_config(
        interaction.guild.id
    )

    enabled = (
        "🟢 Enabled"
        if config.get("enabled")
        else "🔴 Disabled"
    )

    character = (
        config.get("character_name")
        or "غير محددة"
    )

    channel_id = config.get(
        "channel_id"
    )

    channel = (
        f"<#{channel_id}>"
        if channel_id
        else "كل القنوات"
    )

    await interaction.response.send_message(
        "🤖 **MyAI Status**\n\n"
        f"الحالة: **{enabled}**\n"
        f"الشخصية: **{character}**\n"
        f"القناة: {channel}\n"
        f"الوضع: **{config.get('mode', 'normal')}**\n"
        f"نوع الرد: **{config.get('reply_type', 'mention')}**\n"
        f"Provider: **{config.get('provider', PRIMARY_AI_PROVIDER)}**\n"
        f"Model: **{config.get('model', GOOGLE_MODEL)}**",
        ephemeral=True
    )


# ==========================================================
# /ai_memory_clear
# ==========================================================

@bot.tree.command(
    name="ai_memory_clear",
    description="مسح ذاكرة MyAI"
)
async def ai_memory_clear(
    interaction: discord.Interaction
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    if not can_manage_ai(
        interaction
    ):

        await interaction.response.send_message(
            "🛡️ ليس لديك صلاحية مسح الذاكرة.",
            ephemeral=True
        )

        return

    db.clear_history(
        interaction.guild.id
    )

    await interaction.response.send_message(
        "🧹 تم مسح ذاكرة MyAI لهذا السيرفر.",
        ephemeral=True
    )


# ==========================================================
# /ai_dm
# ==========================================================

@bot.tree.command(
    name="ai_dm",
    description="تشغيل أو إيقاف رد MyAI في الخاص"
)
@app_commands.describe(
    option="اختر Enabled أو Disable"
)
@app_commands.choices(
    option=[
        app_commands.Choice(
            name="Enabled",
            value="enabled"
        ),
        app_commands.Choice(
            name="Disable",
            value="disable"
        )
    ]
)
async def ai_dm(
    interaction: discord.Interaction,
    option: app_commands.Choice[str]
):

    enabled = (
        option.value == "enabled"
    )

    try:

        db.set_dm_enabled(
            interaction.user.id,
            enabled
        )

        if enabled:

            await interaction.response.send_message(
                "🟢 **AI DM Enabled**\n\n"
                "🤖 أصبح MyAI قادرًا على الرد عليك "
                "في الرسائل الخاصة.\n\n"
                "أرسل لي رسالة في الخاص الآن 💬",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "🔴 **AI DM Disabled**\n\n"
                "لن يرد MyAI عليك في الخاص.",
                ephemeral=True
            )

    except Exception as e:

        print(
            f"❌ AI DM setting error: {e}"
        )

        await interaction.response.send_message(
            "❌ حدث خطأ أثناء تحديث إعداد AI DM.",
            ephemeral=True
        )


# ==========================================================
# MESSAGE REQUEST KEY
# ==========================================================

def get_request_key(
    message
):

    guild_id = (
        message.guild.id
        if message.guild
        else 0
    )

    return (
        guild_id,
        message.channel.id,
        message.author.id
    )


# ==========================================================
# ON MESSAGE
# ==========================================================

@bot.event
async def on_message(
    message
):

    print()
    print("📩 NEW MESSAGE EVENT RECEIVED")

    print(
        f"👤 Sender     : {message.author}"
    )

    print(
        f"🆔 Author ID  : {message.author.id}"
    )

    print(
        f"🤖 Is Bot     : {message.author.bot}"
    )

    if message.guild:

        print(
            f"🏠 Server     : {message.guild.name}"
        )

        print(
            f"🆔 Guild ID   : {message.guild.id}"
        )

        print(
            f"📍 Channel    : {message.channel}"
        )

        print(
            f"🆔 Channel ID : {message.channel.id}"
        )

    else:

        print(
            "🏠 Server     : None"
        )

        print(
            "📍 Channel    : DM"
        )

    print(
        f"📝 Message    : {message.content!r}"
    )

    # ------------------------------------------------------
    # Ignore own messages
    # ------------------------------------------------------

    if (
        bot.user
        and message.author.id
        == bot.user.id
    ):

        print(
            "⏭️ Ignored MyAI own message"
        )

        return

    # ------------------------------------------------------
    # Ignore bots
    # ------------------------------------------------------

    if message.author.bot:

        print(
            "⏭️ Ignored another bot"
        )

        return

    # ------------------------------------------------------
    # DM
    # ------------------------------------------------------

    if message.guild is None:

        print(
            "📩 Direct Message received"
        )

        try:

            enabled = db.get_dm_enabled(
                message.author.id
            )

        except Exception:

            traceback.print_exc()

            return

        if not enabled:

            print(
                "⏭️ AI DM disabled for this user"
            )

            return

        key = get_request_key(
            message
        )

        if key in ACTIVE_REQUESTS:

            print(
                "⏭️ Existing AI request for this user"
            )

            return

        ACTIVE_REQUESTS.add(
            key
        )

        try:

            await generate_with_typing_message(

                message,

                lambda: generate_dm_reply(
                    message
                ),

                db.DM_CHARACTER_NAME
            )

        finally:

            ACTIVE_REQUESTS.discard(
                key
            )

        return

    # ------------------------------------------------------
    # SERVER CONFIG
    # ------------------------------------------------------

    config = get_config(
        message.guild.id
    )

    if not config.get("enabled"):

        print(
            "⏭️ AI disabled in this server"
        )

        return

    # ------------------------------------------------------
    # CHANNEL FILTER
    # ------------------------------------------------------

    if not channel_matches(
        message,
        config
    ):

        print(
            "⏭️ Message is outside configured AI channel"
        )

        return

    # ------------------------------------------------------
    # SENSITIVE REQUEST SECURITY
    # ------------------------------------------------------

    if is_sensitive_request(
        message.content
    ):

        print(
            "🛡️ Sensitive request detected"
        )

        authorized, reason = security_check(
            message.author
        )

        if not authorized:

            print(
                f"🛡️ BLOCKED: {reason}"
            )

            await message.reply(
                "🛡️ **تم رفض الطلب**\n\n"
                "هذا الطلب يتعلق بإدارة حساسة "
                "للسيرفر.\n\n"
                "👑 التنفيذ مسموح فقط لأعلى "
                "3 رتب في السيرفر.\n\n"
                f"⚠️ السبب: {reason}",
                mention_author=False
            )

            return

        print(
            "🛡️ Sensitive request passed security gate"
        )

    # ------------------------------------------------------
    # MODE
    # ------------------------------------------------------

    mode = (
        config.get("mode")
        or "normal"
    )

    reply_type = (
        config.get("reply_type")
        or "mention"
    )

    if mode not in AI_MODES:

        print(
            f"⚠️ Unknown AI mode: {mode}"
        )

        mode = "normal"

    if reply_type not in REPLY_TYPES:

        print(
            f"⚠️ Unknown reply type: {reply_type}"
        )

        reply_type = "mention"

    directed = is_directed_to_bot(
        message
    )

    # ------------------------------------------------------
    # MENTION
    # ------------------------------------------------------

    if reply_type == "mention":

        if not directed:

            return

    # ------------------------------------------------------
    # DIRECT
    # ------------------------------------------------------

    elif reply_type == "direct":

        if not directed:

            return

    # ------------------------------------------------------
    # CHANNEL / AUTO / BOT CHAT
    # ------------------------------------------------------

    elif reply_type == "channel":

        pass

    elif reply_type == "auto":

        pass

    elif reply_type == "bot_chat":

        pass

    print(
        f"🎯 Selected mode: {reply_type}"
    )

    key = get_request_key(
        message
    )

    if key in ACTIVE_REQUESTS:

        print(
            "⏭️ Duplicate active AI request ignored"
        )

        return

    ACTIVE_REQUESTS.add(
        key
    )

    try:

        character_name = (
            config.get("character_name")
            or "مساعد السيرفر جيميناي"
        )

        await generate_with_typing_message(

            message,

            lambda: generate_chat_reply(
                message,
                config
            ),

            character_name
        )

    finally:

        ACTIVE_REQUESTS.discard(
            key
        )


# ==========================================================
# READY
# ==========================================================

@bot.event
async def on_ready():

    print()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🔌 DISCORD CONNECT EVENT")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    print(
        f"📡 Message Content Intent : "
        f"{intents.message_content}"
    )

    print(
        f"👥 Members Intent         : "
        f"{intents.members}"
    )

    print(
        f"🟢 Presence Intent        : "
        f"{intents.presences}"
    )

    print(
        f"🌐 Guilds Intent          : "
        f"{intents.guilds}"
    )

    print(
        f"💬 Messages Intent        : "
        f"{intents.messages}"
    )

    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    print(
        f"✅ Logged in as "
        f"{bot.user} "
        f"(ID: {bot.user.id})"
    )

    print(
        f"🌐 Connected to "
        f"{len(bot.guilds)} server(s)."
    )

    print(
        "🧠 AI message system is ready."
    )

    print(
        "🎭 Character system | ENABLED"
    )

    print(
        "✏️ Character ownership | ENABLED"
    )

    print(
        "🔒 Owner-only character editing | ENABLED"
    )

    print(
        "🗑️ Owner-only character deletion | ENABLED"
    )

    print(
        "🤖 Bot-to-Bot mode available."
    )

    print(
        "🛡️ Security Manager | ENABLED"
    )

    print(
        "🔐 Sensitive requests | TOP 3 ROLES"
    )

    print(
        "⚡ AI request protection | ENABLED"
    )

    print(
        "⏱️ AI timeout | "
        f"{AI_TIMEOUT}s"
    )

    print(
        f"🤖 Active AI Provider | "
        f"{PRIMARY_AI_PROVIDER}"
    )

    print(
        f"🧠 Active AI Model | "
        f"{GOOGLE_MODEL}"
    )

    print(
        "📩 AI DM system | ENABLED"
    )

    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )


# ==========================================================
# SLASH COMMAND ERROR
# ==========================================================

@bot.tree.error
async def on_app_command_error(
    interaction,
    error
):

    print(
        f"❌ Slash command error: {error}"
    )

    traceback.print_exception(
        type(error),
        error,
        error.__traceback__
    )

    if interaction.response.is_done():
        return

    try:

        await interaction.response.send_message(
            "❌ حدث خطأ أثناء تنفيذ الأمر.",
            ephemeral=True
        )

    except Exception:
        pass


# ==========================================================
# START
# ==========================================================

if __name__ == "__main__":

    if not TOKEN:

        raise RuntimeError(
            "DISCORD_TOKEN غير موجود في Environment Variables."
        )

    print(
        "🚀 Starting MyAI..."
    )

    print(
        f"📡 Message Content Intent configured: "
        f"{intents.message_content}"
    )

    bot.run(
        TOKEN
)
