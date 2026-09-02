import os
import re
import asyncio
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
)

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


REPLY_TYPES = {
    "mention",
    "direct",
    "channel",
    "auto",
    "bot_chat"
}


# ==========================================================
# SENSITIVE SECURITY
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
    "ban",
    "kick",
    "timeout",
    "manage_guild"
}


SENSITIVE_KEYWORDS = (
    "احذف الرتبة",
    "حذف الرتبة",
    "أنشئ رتبة",
    "انشئ رتبة",
    "عدل الرتبة",
    "غيّر صلاحيات",
    "غير صلاحيات",
    "صلاحيات الرتبة",
    "صلاحيات الروم",
    "صلاحيات القناة",
    "احذف الروم",
    "حذف الروم",
    "أنشئ روم",
    "انشئ روم",
    "عدل الروم",
    "غيّر اسم الروم",
    "غير اسم الروم",
    "بان",
    "طرد",
    "تايم اوت",
    "timeout",
    "ban",
    "kick",
    "delete role",
    "create role",
    "manage roles",
    "manage channels",
    "permissions"
)


# ==========================================================
# INTENTS
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
# HELPERS
# ==========================================================

def row_to_dict(row):

    if row is None:
        return None

    if isinstance(row, dict):
        return row

    return dict(row)


def get_config(guild_id):

    return db.get_ai_config(guild_id)


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


def get_active_character(guild_id):

    return row_to_dict(
        db.get_active_character(
            guild_id
        )
    )


def as_bool(value):

    return bool(value)


def normalize_text(text):

    return re.sub(
        r"\s+",
        " ",
        str(text or "")
    ).strip()


def clean_mentions(
    text,
    bot_user
):

    if bot_user:

        text = text.replace(
            f"<@{bot_user.id}>",
            ""
        )

        text = text.replace(
            f"<@!{bot_user.id}>",
            ""
        )

    return normalize_text(text)


def split_message(
    text,
    limit=1900
):

    text = str(text)

    return [
        text[i:i + limit]
        for i in range(
            0,
            len(text),
            limit
        )
    ]


def normalize_channel_id(value):

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

    return message.channel.id == configured


def is_directed_to_bot(message):

    if not bot.user:
        return False

    return (
        bot.user in message.mentions
        or message.content.lower().startswith(
            bot.user.name.lower()
        )
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

    if member.guild.owner_id == member.id:
        return True

    permissions = member.guild_permissions

    return (
        permissions.administrator
        or permissions.manage_guild
        or permissions.manage_channels
        or permissions.manage_roles
    )


def can_manage_ai(obj):

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
# TOP 3 ROLES SECURITY
# ==========================================================

def get_top_three_roles(
    guild
):

    roles = [
        role
        for role in guild.roles
        if role != guild.default_role
    ]

    roles.sort(
        key=lambda role: role.position,
        reverse=True
    )

    return roles[:3]


def member_has_top_three_role(
    member
):

    if not isinstance(
        member,
        discord.Member
    ):
        return False

    top_roles = get_top_three_roles(
        member.guild
    )

    top_role_ids = {
        role.id
        for role in top_roles
    }

    return any(
        role.id in top_role_ids
        for role in member.roles
    )


def is_sensitive_request(
    text
):

    normalized = normalize_text(
        text
    ).lower()

    return any(
        keyword.lower() in normalized
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
        return False, "عضو غير صالح."

    # Server owner gets the highest authority.
    if member.guild.owner_id == member.id:
        return True, "server_owner"

    if not member_has_top_three_role(member):
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

    return True, "authorized"


def bot_can_manage_role(
    guild,
    role
):

    me = guild.me

    if me is None:
        return False

    if role == guild.default_role:
        return False

    return role < me.top_role


def bot_can_manage_member(
    guild,
    member
):

    me = guild.me

    if me is None:
        return False

    return member.top_role < me.top_role


# ==========================================================
# AI GENERATION
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

    print("🧠 GENERATING AI RESPONSE")

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

    response = await ai.generate(
        guild_id=message.guild.id,
        channel_id=message.channel.id,
        user_id=message.author.id,
        character_name=character_name,
        prompt=user_text,
        mode=ai_mode,
        provider=provider,
        model=model
    )

    return response


async def generate_dm_reply(
    message
):

    character_name = (
        db.DM_CHARACTER_NAME
    )

    response = await ai.generate(
        guild_id=db.DM_GUILD_ID,
        channel_id=message.channel.id,
        user_id=message.author.id,
        character_name=character_name,
        prompt=message.content,
        mode="friendly",
        provider="google",
        model=GOOGLE_MODEL
    )

    return response


# ==========================================================
# SEND
# ==========================================================

async def send_ai_response(
    message,
    response
):

    if not response:
        return

    response = str(response).strip()

    for part in split_message(response):

        if not part:
            continue

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
# DM COMMAND
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

    db.set_dm_enabled(
        interaction.user.id,
        enabled
    )

    if enabled:

        await interaction.response.send_message(
            "✅ تم تفعيل MyAI في الخاص.\n"
            "الآن إذا أرسلت لي رسالة في DM سأرد عليك 🤖💬",
            ephemeral=True
        )

    else:

        await interaction.response.send_message(
            "🔕 تم تعطيل MyAI في الخاص.",
            ephemeral=True
        )


# ==========================================================
# MESSAGE EVENT
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

    print(
        f"📝 Message    : {message.content!r}"
    )

    # ------------------------------------------------------
    # Ignore MyAI itself
    # ------------------------------------------------------

    if bot.user and message.author.id == bot.user.id:

        print(
            "⏭️ Ignored MyAI own message"
        )

        return

    # ------------------------------------------------------
    # DM
    # ------------------------------------------------------

    if message.guild is None:

        enabled = db.get_dm_enabled(
            message.author.id
        )

        if not enabled:

            print(
                "⏭️ DM disabled for this user"
            )

            return

        print(
            "📩 DM AI enabled"
        )

        try:

            response = await generate_dm_reply(
                message
            )

            await send_ai_response(
                message,
                response
            )

        except Exception as e:

            print(
                f"❌ DM AI error: {e}"
            )

        return

    # ------------------------------------------------------
    # BOT USERS
    # ------------------------------------------------------

    if message.author.bot:

        print(
            "⏭️ Ignored another bot"
        )

        return

    # ------------------------------------------------------
    # CONFIG
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
    # CHANNEL
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
    # SECURITY
    # ------------------------------------------------------

    if is_sensitive_request(
        message.content
    ):

        authorized, reason = security_check(
            message.author
        )

        if not authorized:

            print(
                f"🛡️ BLOCKED SENSITIVE REQUEST: {reason}"
            )

            await message.reply(
                "🛡️ **تم رفض الطلب**\n\n"
                "هذا الإجراء يعتبر حساسًا لإدارة السيرفر، "
                "ومسموح فقط لأعلى 3 رتب في السيرفر.\n\n"
                f"السبب: {reason}",
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
    # CHANNEL / AUTO
    # ------------------------------------------------------

    elif reply_type in {
        "channel",
        "auto"
    }:

        pass

    # ------------------------------------------------------
    # BOT CHAT
    # ------------------------------------------------------

    elif reply_type == "bot_chat":

        pass

    # ------------------------------------------------------
    # STYLE MODES
    # ------------------------------------------------------

    if mode not in AI_MODES:

        print(
            f"⚠️ Unknown AI mode: {mode}"
        )

        mode = "normal"

    print(
        f"🎯 Selected mode: {reply_type}"
    )

    try:

        response = await generate_chat_reply(
            message,
            config
        )

        await send_ai_response(
            message,
            response
        )

    except Exception as e:

        print(
            f"❌ AI generation error: {e}"
        )

    # ------------------------------------------------------
    # PROCESS COMMANDS
    # ------------------------------------------------------

    await bot.process_commands(
        message
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

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

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
        f"📡 Message Content Intent: "
        f"{intents.message_content}"
    )

    print(
        "🤖 Bot-to-Bot mode available."
    )

    print(
        "🛡️ Security Manager: ENABLED"
    )

    print(
        "🔐 Sensitive actions: TOP 3 ROLES"
    )

    print(
        f"🤖 Active AI Provider | "
        f"{PRIMARY_AI_PROVIDER}"
    )

    print(
        f"🧠 Active AI Model | "
        f"{GOOGLE_MODEL}"
    )


# ==========================================================
# GLOBAL SLASH ERROR
# ==========================================================

@bot.tree.error
async def on_app_command_error(
    interaction,
    error
):

    print(
        f"❌ Slash command error: {error}"
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

    print("🚀 Starting MyAI...")

    print(
        f"📡 Message Content Intent configured: "
        f"{intents.message_content}"
    )

    bot.run(
        TOKEN
    )
