import os
import re
import time
import traceback

import discord
from discord import app_commands
from discord.ext import commands

from database import Database
from ai_engine import AIEngine


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

AUTO_CHECK_MESSAGE_COUNT = 30
AUTO_COOLDOWN_SECONDS = 300

BOT_CHAT_MAX_REPLIES = 100
BOT_CHAT_COOLDOWN_SECONDS = 2

DEFAULT_PROVIDER = "google"
DEFAULT_MODEL = "gemini-3.5-flash-lite"


# =========================================================
# AI MODES / STYLES
# =========================================================

AI_MODES = {
    "normal": {
        "temperature": 0.7,
        "description": "ردود طبيعية ومتوازنة",
    },
    "friendly": {
        "temperature": 0.9,
        "description": "ردود ودية وحماسية",
    },
    "active": {
        "temperature": 1.0,
        "description": "ردود نشطة وتفاعلية",
    },
    "fun": {
        "temperature": 1.1,
        "description": "ردود مرحة",
    },
    "professional": {
        "temperature": 0.4,
        "description": "ردود رسمية",
    },
}


# =========================================================
# DISCORD INTENTS
# =========================================================

intents = discord.Intents.default()

intents.guilds = True
intents.messages = True
intents.message_content = True

# إضافية للتوافق والتشخيص
intents.members = True
intents.presences = True


# =========================================================
# DATABASE / AI
# =========================================================

db = Database()
ai = AIEngine(db)


# =========================================================
# RUNTIME STATE
# =========================================================

auto_message_counter = {}
auto_last_reply = {}

bot_chat_reply_count = {}
bot_chat_last_reply = {}

user_memory = {}


# =========================================================
# BOT CLASS
# =========================================================

class MyAIBot(commands.Bot):

    async def setup_hook(self):
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} slash commands.")
        except Exception:
            print("❌ Failed to sync slash commands.")
            traceback.print_exc()


bot = MyAIBot(
    command_prefix="!",
    intents=intents,
    help_command=None,
)


# =========================================================
# HELPERS
# =========================================================

def row_to_dict(row):
    if row is None:
        return None

    if isinstance(row, dict):
        return row

    try:
        return dict(row)
    except Exception:
        return row


def get_config(guild_id):
    try:
        config = db.get_guild_config(guild_id)

        if config is None:
            return {
                "enabled": False,
                "channel_id": None,
                "mode": "normal",
                "reply_type": "normal",
                "character_name": None,
                "permission_preset": "admin",
                "provider": DEFAULT_PROVIDER,
                "model": DEFAULT_MODEL,
            }

        config = row_to_dict(config)

        config.setdefault("enabled", False)
        config.setdefault("channel_id", None)
        config.setdefault("mode", "normal")
        config.setdefault("reply_type", "normal")
        config.setdefault("character_name", None)
        config.setdefault("permission_preset", "admin")
        config.setdefault("provider", DEFAULT_PROVIDER)
        config.setdefault("model", DEFAULT_MODEL)

        return config

    except Exception:
        print("❌ get_config() failed")
        traceback.print_exc()

        return {
            "enabled": False,
            "channel_id": None,
            "mode": "normal",
            "reply_type": "normal",
            "character_name": None,
            "permission_preset": "admin",
            "provider": DEFAULT_PROVIDER,
            "model": DEFAULT_MODEL,
        }


def save_config(guild_id, **kwargs):
    try:
        return db.update_guild_config(
            guild_id,
            **kwargs,
        )
    except Exception:
        print("❌ save_config() failed")
        traceback.print_exc()
        return None


def get_character(guild_id, character_id):
    try:
        return db.get_character_by_id(
            guild_id,
            int(character_id),
        )
    except Exception:
        print("❌ get_character() failed")
        traceback.print_exc()
        return None


def get_active_character(guild_id):
    try:
        return db.get_active_character(guild_id)
    except Exception:
        print("❌ get_active_character() failed")
        traceback.print_exc()
        return None


def normalize_channel_id(value):
    if value is None:
        return None

    try:
        return int(value)
    except Exception:
        return None


def channel_matches(message, config):
    configured_channel = normalize_channel_id(
        config.get("channel_id")
    )

    if configured_channel is None:
        return True

    return message.channel.id == configured_channel


def as_bool(value):
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value != 0

    if value is None:
        return False

    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
        "مفعل",
    }


def split_message(text, limit=1900):
    if not text:
        return []

    return [
        text[i:i + limit]
        for i in range(0, len(text), limit)
    ]


def clean_mentions(text):
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

    return text.strip()


def normalize_text(text):
    if not text:
        return ""

    return " ".join(
        text.strip().split()
    )


def is_directed_to_bot(message):
    if bot.user and message.author.id == bot.user.id:
        return True

    if bot.user and bot.user in message.mentions:
        return True

    content = message.content.lower().strip()

    if bot.user:
        bot_names = {
            bot.user.name.lower(),
            bot.user.display_name.lower(),
        }

        for name in bot_names:
            if name and name in content:
                return True

    return False


# =========================================================
# PERMISSIONS
# =========================================================

def has_management_permission(member):
    if member is None:
        return False

    try:
        permissions = member.guild_permissions

        return (
            permissions.administrator
            or permissions.manage_guild
        )

    except Exception:
        return False


def can_manage_ai(obj):
    """
    يدعم:
    - discord.Interaction
    - discord.Message
    """

    if isinstance(obj, discord.Interaction):
        member = obj.user

    elif isinstance(obj, discord.Message):
        member = obj.author

    else:
        return False

    if not isinstance(member, discord.Member):
        return False

    return has_management_permission(member)


# =========================================================
# AI RESPONSE
# =========================================================

async def generate_chat_reply(
    message,
    config,
    prompt=None,
):
    try:
        guild_id = message.guild.id if message.guild else None

        if guild_id is None:
            return None

        character = get_active_character(guild_id)

        character_name = None

        if character:
            character = row_to_dict(character)
            character_name = character.get("name")

        user_text = prompt

        if user_text is None:
            user_text = message.content

        user_text = clean_mentions(user_text)
        user_text = normalize_text(user_text)

        if not user_text:
            user_text = "مرحبا"

        mode = str(
            config.get(
                "mode",
                "normal",
            )
        ).lower().strip()

        mode_data = AI_MODES.get(
            mode,
            AI_MODES["normal"],
        )

        provider = config.get(
            "provider",
            DEFAULT_PROVIDER,
        )

        model = config.get(
            "model",
            DEFAULT_MODEL,
        )

        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("🧠 GENERATING AI RESPONSE")
        print(f"🏠 Guild     : {message.guild.name}")
        print(f"👤 User      : {message.author}")
        print(f"📝 Prompt    : {user_text}")
        print(f"🎭 Character : {character_name}")
        print(f"⚙️ Mode      : {mode}")
        print(f"🌡️ Temp      : {mode_data['temperature']}")
        print(f"🤖 Provider  : {provider}")
        print(f"🧠 Model     : {model}")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # محاولة التوقيع الكامل
        try:
            response = await ai.generate(
                guild_id=guild_id,
                user_id=message.author.id,
                prompt=user_text,
                character_name=character_name,
                mode=mode,
                temperature=mode_data["temperature"],
                provider=provider,
                model=model,
            )

        except TypeError:

            # توافق مع AIEngine الأقدم
            try:
                response = await ai.generate(
                    guild_id=guild_id,
                    user_id=message.author.id,
                    prompt=user_text,
                    character_name=character_name,
                    mode=mode,
                )

            except TypeError:

                # توافق مع أبسط نسخة
                response = await ai.generate(
                    prompt=user_text,
                )

        if response is None:
            print("⚠️ AI returned None")
            return None

        response = str(response).strip()

        # إزالة ALERT إذا رجعه AI
        response = re.sub(
            r"^\s*ALERT:\s*",
            "",
            response,
            flags=re.IGNORECASE,
        ).strip()

        print(f"✅ AI RESPONSE LENGTH: {len(response)}")

        return response

    except Exception:
        print("❌ generate_chat_reply() failed")
        traceback.print_exc()
        return None


async def send_ai_response(
    message,
    response,
):
    if not response:
        return

    chunks = split_message(response)

    for chunk in chunks:

        try:
            await message.channel.send(
                chunk
            )

        except Exception:
            print("❌ Failed to send AI response")
            traceback.print_exc()
            break


# =========================================================
# AUTO AI
# =========================================================

async def handle_auto_ai(message, config):

    guild_id = message.guild.id

    auto_message_counter[guild_id] = (
        auto_message_counter.get(
            guild_id,
            0,
        ) + 1
    )

    count = auto_message_counter[guild_id]

    now = time.time()

    last_reply = auto_last_reply.get(
        guild_id,
        0,
    )

    print(
        f"🤖 AUTO MODE | "
        f"messages={count}/{AUTO_CHECK_MESSAGE_COUNT}"
    )

    if count < AUTO_CHECK_MESSAGE_COUNT:
        return

    if now - last_reply < AUTO_COOLDOWN_SECONDS:
        print("⏳ Auto cooldown active")
        return

    auto_message_counter[guild_id] = 0
    auto_last_reply[guild_id] = now

    response = await generate_chat_reply(
        message,
        config,
    )

    if response:
        await send_ai_response(
            message,
            response,
        )


# =========================================================
# BOT CHAT
# =========================================================

async def handle_bot_chat(message, config):

    guild_id = message.guild.id

    now = time.time()

    last_reply = bot_chat_last_reply.get(
        guild_id,
        0,
    )

    if now - last_reply < BOT_CHAT_COOLDOWN_SECONDS:
        print("⏳ Bot Chat cooldown active")
        return

    count = bot_chat_reply_count.get(
        guild_id,
        0,
    )

    if count >= BOT_CHAT_MAX_REPLIES:
        print(
            f"🛑 Bot Chat limit reached "
            f"for guild {guild_id}"
        )
        return

    if not is_directed_to_bot(message):
        print(
            "⏭️ Other bot did not address MyAI"
        )
        return

    bot_chat_last_reply[guild_id] = now
    bot_chat_reply_count[guild_id] = count + 1

    response = await generate_chat_reply(
        message,
        config,
    )

    if response:
        await send_ai_response(
            message,
            response,
        )


# =========================================================
# CONNECTION EVENTS
# =========================================================

@bot.event
async def on_connect():

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🔌 DISCORD CONNECT EVENT")
    print(
        f"📡 Message Content Intent : "
        f"{bot.intents.message_content}"
    )
    print(
        f"👥 Members Intent         : "
        f"{bot.intents.members}"
    )
    print(
        f"🟢 Presence Intent        : "
        f"{bot.intents.presences}"
    )
    print(
        f"🌐 Guilds Intent          : "
        f"{bot.intents.guilds}"
    )
    print(
        f"💬 Messages Intent        : "
        f"{bot.intents.messages}"
    )
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


@bot.event
async def on_resumed():

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("♻️ DISCORD SESSION RESUMED")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


@bot.event
async def on_ready():

    print()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(
        f"✅ Logged in as {bot.user} "
        f"(ID: {bot.user.id})"
    )
    print(
        f"🌐 Connected to "
        f"{len(bot.guilds)} server(s)."
    )
    print("🧠 AI message system is ready.")
    print(
        f"📡 Message Content Intent: "
        f"{bot.intents.message_content}"
    )
    print("🤖 Bot-to-Bot mode available.")
    print(
        f"🛡️ Bot Chat Safety | "
        f"max={BOT_CHAT_MAX_REPLIES} | "
        f"cooldown={BOT_CHAT_COOLDOWN_SECONDS}s"
    )
    print(
        f"🤖 Active AI Provider | "
        f"{DEFAULT_PROVIDER}"
    )
    print(
        f"🧠 Active AI Model | "
        f"{DEFAULT_MODEL}"
    )
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()


# =========================================================
# RAW GATEWAY DIAGNOSTIC
# =========================================================

@bot.event
async def on_socket_raw_receive(msg):

    try:

        if '"t":"MESSAGE_CREATE"' in msg:

            print(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            print(
                "📡 RAW GATEWAY MESSAGE_CREATE RECEIVED"
            )
            print(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )

    except Exception:
        pass


# =========================================================
# MESSAGE EDIT
# =========================================================

@bot.event
async def on_message_edit(
    before,
    after,
):

    try:

        print(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        print("✏️ MESSAGE EDIT EVENT")
        print(f"👤 Author : {after.author}")
        print(f"🏠 Guild  : {after.guild}")
        print(f"📝 Before : {before.content!r}")
        print(f"📝 After  : {after.content!r}")
        print(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

    except Exception:
        traceback.print_exc()


# =========================================================
# MESSAGE DELETE
# =========================================================

@bot.event
async def on_raw_message_delete(
    payload,
):

    try:

        print(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        print("🗑️ MESSAGE DELETE EVENT")
        print(
            f"🆔 Message ID : "
            f"{payload.message_id}"
        )
        print(
            f"🆔 Channel ID : "
            f"{payload.channel_id}"
        )
        print(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

    except Exception:
        traceback.print_exc()


# =========================================================
# MAIN MESSAGE HANDLER
# =========================================================

@bot.event
async def on_message(message):

    try:

        print(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        print("📩 NEW MESSAGE EVENT RECEIVED")
        print(f"👤 Sender     : {message.author}")
        print(
            f"🆔 Author ID  : "
            f"{message.author.id}"
        )
        print(
            f"🤖 Is Bot     : "
            f"{message.author.bot}"
        )
        print(
            f"🏠 Server     : "
            f"{message.guild.name "
            if message.guild
            else 'None'}"
        )

        if message.guild:
            print(
                f"🆔 Guild ID   : "
                f"{message.guild.id}"
            )

        print(
            f"📍 Channel    : "
            f"{message.channel}"
        )
        print(
            f"🆔 Channel ID : "
            f"{message.channel.id}"
        )
        print(
            f"📝 Message    : "
            f"{message.content!r}"
        )

        print(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        # -------------------------------------------------
        # Ignore MyAI itself
        # -------------------------------------------------

        if bot.user and (
            message.author.id == bot.user.id
        ):

            print(
                "⏭️ Ignored MyAI own message"
            )
            return

        # -------------------------------------------------
        # DM
        # -------------------------------------------------

        if message.guild is None:

            print(
                "⏭️ Ignored DM message"
            )
            return

        # -------------------------------------------------
        # Config
        # -------------------------------------------------

        config = get_config(
            message.guild.id
        )

        print("⚙️ AI CONFIG")
        print(
            f"   enabled      = "
            f"{config.get('enabled')}"
        )
        print(
            f"   channel_id   = "
            f"{config.get('channel_id')}"
        )
        print(
            f"   mode         = "
            f"{config.get('mode')}"
        )
        print(
            f"   reply_type   = "
            f"{config.get('reply_type')}"
        )
        print(
            f"   character    = "
            f"{config.get('character_name')}"
        )
        print(
            f"   provider     = "
            f"{config.get('provider')}"
        )
        print(
            f"   model        = "
            f"{config.get('model')}"
        )

        # -------------------------------------------------
        # Disabled
        # -------------------------------------------------

        if not as_bool(
            config.get("enabled")
        ):

            print(
                "⏭️ AI system is disabled"
            )
            return

        # -------------------------------------------------
        # Channel filter
        # -------------------------------------------------

        if not channel_matches(
            message,
            config,
        ):

            print(
                "⏭️ Message is outside "
                "configured AI channel"
            )
            return

        # -------------------------------------------------
        # BOT MESSAGES
        # -------------------------------------------------

        if message.author.bot:

            print(
                "🤖 Message came from another bot"
            )

            mode = str(
                config.get(
                    "mode",
                    "",
                )
            ).lower().strip()

            if mode != "bot_chat":

                print(
                    "⏭️ Other bot ignored "
                    "(bot_chat is not enabled)"
                )
                return

            await handle_bot_chat(
                message,
                config,
            )

            return

        # -------------------------------------------------
        # USER MESSAGE
        # -------------------------------------------------

        mode = str(
            config.get(
                "mode",
                config.get(
                    "reply_type",
                    "normal",
                ),
            )
        ).lower().strip()

        print(
            f"🎯 Selected mode: {mode}"
        )

        # =================================================
        # STYLE MODES
        # =================================================
        #
        # هذه الأوضاع الآن تعمل كأوضاع رد فعلية.
        #
        # normal
        # friendly
        # active
        # fun
        # professional
        #
        # كلها تستجيب للرسالة مباشرة.
        # =================================================

        if mode in {
            "normal",
            "friendly",
            "active",
            "fun",
            "professional",
        }:

            print(
                f"💬 Style mode active: {mode}"
            )

            response = await generate_chat_reply(
                message,
                config,
            )

            if response:

                await send_ai_response(
                    message,
                    response,
                )

            return

        # =================================================
        # MENTION
        # =================================================

        if mode == "mention":

            if not is_directed_to_bot(
                message
            ):

                print(
                    "⏭️ Message does not mention "
                    "or directly address MyAI"
                )
                return

            response = await generate_chat_reply(
                message,
                config,
            )

            if response:

                await send_ai_response(
                    message,
                    response,
                )

            return

        # =================================================
        # DIRECT
        # =================================================

        if mode == "direct":

            if not is_directed_to_bot(
                message
            ):

                print(
                    "⏭️ Direct mode: "
                    "message is not directed "
                    "to MyAI"
                )
                return

            response = await generate_chat_reply(
                message,
                config,
            )

            if response:

                await send_ai_response(
                    message,
                    response,
                )

            return

        # =================================================
        # CHANNEL
        # =================================================

        if mode == "channel":

            response = await generate_chat_reply(
                message,
                config,
            )

            if response:

                await send_ai_response(
                    message,
                    response,
                )

            return

        # =================================================
        # AUTO
        # =================================================

        if mode == "auto":

            await handle_auto_ai(
                message,
                config,
            )

            return

        # =================================================
        # BOT CHAT
        # =================================================

        if mode == "bot_chat":

            if is_directed_to_bot(
                message
            ):

                response = await generate_chat_reply(
                    message,
                    config,
                )

                if response:

                    await send_ai_response(
                        message,
                        response,
                    )

            return

        # =================================================
        # UNKNOWN
        # =================================================

        print(
            f"⚠️ Unknown AI mode: {mode}"
        )

    except Exception:

        print(
            "❌ UNHANDLED ERROR IN on_message"
        )

        traceback.print_exc()


# =========================================================
# /ai
# =========================================================

@bot.tree.command(
    name="ai",
    description="عرض حالة نظام الذكاء الاصطناعي",
)
async def ai_command(
    interaction: discord.Interaction,
):

    try:

        if not can_manage_ai(
            interaction
        ):

            await interaction.response.send_message(
                "❌ تحتاج صلاحية Administrator "
                "أو Manage Server.",
                ephemeral=True,
            )
            return

        config = get_config(
            interaction.guild.id
        )

        enabled = as_bool(
            config.get("enabled")
        )

        mode = config.get(
            "mode",
            "normal",
        )

        channel_id = config.get(
            "channel_id"
        )

        provider = config.get(
            "provider",
            DEFAULT_PROVIDER,
        )

        model = config.get(
            "model",
            DEFAULT_MODEL,
        )

        character = config.get(
            "character_name"
        )

        text = (
            "🤖 **MyAI Status**\n\n"
            f"🟢 الحالة: "
            f"{'مفعل' if enabled else 'متوقف'}\n"
            f"⚙️ الوضع: `{mode}`\n"
            f"📍 الروم: "
            f"`{channel_id or 'كل الرومات'}`\n"
            f"🎭 الشخصية: "
            f"`{character or 'افتراضية'}`\n"
            f"🔌 Provider: `{provider}`\n"
            f"🧠 Model: `{model}`"
        )

        await interaction.response.send_message(
            text,
            ephemeral=True,
        )

    except Exception:

        traceback.print_exc()

        if not interaction.response.is_done():

            await interaction.response.send_message(
                "❌ حدث خطأ أثناء قراءة حالة AI.",
                ephemeral=True,
            )


# =========================================================
# AI SETUP SELECT
# =========================================================

class AISetupSelect(
    discord.ui.Select
):

    def __init__(self):

        options = [

            discord.SelectOption(
                label="Normal",
                description="رد طبيعي ومتوازن",
                value="normal",
            ),

            discord.SelectOption(
                label="Friendly",
                description="ردود ودية وحماسية",
                value="friendly",
            ),

            discord.SelectOption(
                label="Active",
                description="ردود نشطة وتفاعلية",
                value="active",
            ),

            discord.SelectOption(
                label="Fun",
                description="ردود مرحة",
                value="fun",
            ),

            discord.SelectOption(
                label="Professional",
                description="ردود رسمية",
                value="professional",
            ),

            discord.SelectOption(
                label="Mention",
                description="يرد عند منشن MyAI",
                value="mention",
            ),

            discord.SelectOption(
                label="Direct",
                description="يرد عند توجيه الكلام إلى MyAI",
                value="direct",
            ),

            discord.SelectOption(
                label="Channel",
                description="يرد على كل رسائل الروم",
                value="channel",
            ),

            discord.SelectOption(
                label="Auto",
                description="يرد تلقائيًا بعد عدد من الرسائل",
                value="auto",
            ),

            discord.SelectOption(
                label="Bot Chat",
                description="التفاعل مع البوتات الأخرى",
                value="bot_chat",
            ),
        ]

        super().__init__(
            placeholder="اختر وضع MyAI",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        try:

            if not can_manage_ai(
                interaction
            ):

                await interaction.response.send_message(
                    "❌ تحتاج صلاحية Administrator "
                    "أو Manage Server.",
                    ephemeral=True,
                )
                return

            mode = self.values[0]

            channel_id = interaction.channel.id

            save_config(
                interaction.guild.id,

                enabled=True,

                channel_id=channel_id,

                mode=mode,

                reply_type=mode,

                provider=DEFAULT_PROVIDER,

                model=DEFAULT_MODEL,
            )

            await interaction.response.send_message(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "✅ **تم تحديث نظام AI**\n\n"
                f"🟢 الحالة: **مفعل**\n"
                f"⚙️ الوضع: `{mode}`\n"
                f"📍 الروم: <#{channel_id}>\n"
                f"🤖 Provider: `{DEFAULT_PROVIDER}`\n"
                f"🧠 Model: `{DEFAULT_MODEL}`\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                ephemeral=True,
            )

        except Exception:

            traceback.print_exc()

            if not interaction.response.is_done():

                await interaction.response.send_message(
                    "❌ حدث خطأ أثناء إعداد AI.",
                    ephemeral=True,
                )


class AISetupView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=120
        )

        self.add_item(
            AISetupSelect()
        )


# =========================================================
# /ai_setup
# =========================================================

@bot.tree.command(
    name="ai_setup",
    description="إعداد نظام AI",
)
async def ai_setup(
    interaction: discord.Interaction,
):

    try:

        if not can_manage_ai(
            interaction
        ):

            await interaction.response.send_message(
                "❌ تحتاج صلاحية Administrator "
                "أو Manage Server.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "🤖 **إعداد MyAI**\n\n"
            "اختر طريقة/أسلوب تفاعل البوت:",
            view=AISetupView(),
            ephemeral=True,
        )

    except Exception:

        traceback.print_exc()

        if not interaction.response.is_done():

            await interaction.response.send_message(
                "❌ حدث خطأ أثناء فتح إعدادات AI.",
                ephemeral=True,
            )


# =========================================================
# /character_create
# =========================================================

@bot.tree.command(
    name="character_create",
    description="إنشاء شخصية AI",
)
@app_commands.describe(
    name="اسم الشخصية",
    prompt="تعليمات الشخصية",
)
async def character_create(
    interaction: discord.Interaction,
    name: str,
    prompt: str,
):

    try:

        if not can_manage_ai(
            interaction
        ):

            await interaction.response.send_message(
                "❌ تحتاج صلاحية Administrator "
                "أو Manage Server.",
                ephemeral=True,
            )
            return

        result = db.create_character(
            interaction.guild.id,
            name,
            prompt,
        )

        if result:

            await interaction.response.send_message(
                f"✅ تم إنشاء الشخصية **{name}**.",
                ephemeral=True,
            )

        else:

            await interaction.response.send_message(
                "❌ تعذر إنشاء الشخصية.",
                ephemeral=True,
            )

    except Exception:

        traceback.print_exc()

        if not interaction.response.is_done():

            await interaction.response.send_message(
                "❌ حدث خطأ أثناء إنشاء الشخصية.",
                ephemeral=True,
            )


# =========================================================
# /character_list
# =========================================================

@bot.tree.command(
    name="character_list",
    description="عرض شخصيات AI",
)
async def character_list(
    interaction: discord.Interaction,
):

    try:

        if not can_manage_ai(
            interaction
        ):

            await interaction.response.send_message(
                "❌ تحتاج صلاحية Administrator "
                "أو Manage Server.",
                ephemeral=True,
            )
            return

        characters = db.list_characters(
            interaction.guild.id
        )

        if not characters:

            await interaction.response.send_message(
                "📭 لا توجد شخصيات.",
                ephemeral=True,
            )
            return

        lines = []

        for character in characters:

            character = row_to_dict(
                character
            )

            lines.append(
                f"• `{character.get('id')}` — "
                f"**{character.get('name')}**"
            )

        await interaction.response.send_message(
            "🎭 **الشخصيات:**\n\n"
            + "\n".join(lines),
            ephemeral=True,
        )

    except Exception:

        traceback.print_exc()

        if not interaction.response.is_done():

            await interaction.response.send_message(
                "❌ حدث خطأ أثناء قراءة الشخصيات.",
                ephemeral=True,
            )


# =========================================================
# /character_use
# =========================================================

@bot.tree.command(
    name="character_use",
    description="تفعيل شخصية AI",
)
@app_commands.describe(
    character_id="رقم الشخصية",
)
async def character_use(
    interaction: discord.Interaction,
    character_id: int,
):

    try:

        if not can_manage_ai(
            interaction
        ):

            await interaction.response.send_message(
                "❌ تحتاج صلاحية Administrator "
                "أو Manage Server.",
                ephemeral=True,
            )
            return

        character = get_character(
            interaction.guild.id,
            character_id,
        )

        if not character:

            await interaction.response.send_message(
                "❌ لم يتم العثور على الشخصية.",
                ephemeral=True,
            )
            return

        character = row_to_dict(
            character
        )

        db.set_active_character(
            interaction.guild.id,
            character_id,
        )

        await interaction.response.send_message(
            f"🎭 تم تفعيل الشخصية "
            f"**{character.get('name')}**.",
            ephemeral=True,
        )

    except Exception:

        traceback.print_exc()

        if not interaction.response.is_done():

            await interaction.response.send_message(
                "❌ حدث خطأ أثناء تفعيل الشخصية.",
                ephemeral=True,
            )


# =========================================================
# /ai_status
# =========================================================

@bot.tree.command(
    name="ai_status",
    description="عرض حالة MyAI بالتفصيل",
)
async def ai_status(
    interaction: discord.Interaction,
):

    try:

        config = get_config(
            interaction.guild.id
        )

        enabled = as_bool(
            config.get("enabled")
        )

        channel_id = config.get(
            "channel_id"
        )

        mode = config.get(
            "mode",
            "normal",
        )

        provider = config.get(
            "provider",
            DEFAULT_PROVIDER,
        )

        model = config.get(
            "model",
            DEFAULT_MODEL,
        )

        await interaction.response.send_message(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🤖 **MYAI STATUS**\n\n"
            f"🟢 AI: "
            f"{'ON' if enabled else 'OFF'}\n"
            f"⚙️ Mode: `{mode}`\n"
            f"📍 Channel: "
            f"{f'<#{channel_id}>' if channel_id else 'All'}\n"
            f"🔌 Provider: `{provider}`\n"
            f"🧠 Model: `{model}`\n"
            f"🌐 Servers: `{len(bot.guilds)}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            ephemeral=True,
        )

    except Exception:

        traceback.print_exc()

        if not interaction.response.is_done():

            await interaction.response.send_message(
                "❌ تعذر الحصول على الحالة.",
                ephemeral=True,
            )


# =========================================================
# /ai_memory_clear
# =========================================================

@bot.tree.command(
    name="ai_memory_clear",
    description="مسح ذاكرة AI",
)
async def ai_memory_clear(
    interaction: discord.Interaction,
):

    try:

        if not can_manage_ai(
            interaction
        ):

            await interaction.response.send_message(
                "❌ تحتاج صلاحية Administrator "
                "أو Manage Server.",
                ephemeral=True,
            )
            return

        guild_id = interaction.guild.id

        user_memory.pop(
            guild_id,
            None,
        )

        try:

            if hasattr(
                db,
                "clear_messages",
            ):

                db.clear_messages(
                    guild_id
                )

        except Exception:

            traceback.print_exc()

        await interaction.response.send_message(
            "🧹 تم مسح ذاكرة MyAI.",
            ephemeral=True,
        )

    except Exception:

        traceback.print_exc()

        if not interaction.response.is_done():

            await interaction.response.send_message(
                "❌ حدث خطأ أثناء مسح الذاكرة.",
                ephemeral=True,
            )


# =========================================================
# GLOBAL SLASH COMMAND ERROR HANDLER
# =========================================================

@bot.tree.error
async def on_app_command_error(
    interaction,
    error,
):

    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    print("❌ SLASH COMMAND ERROR")
    print(
        f"Command : {interaction.command}"
    )
    print(
        f"Error   : {error}"
    )
    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

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


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    if not TOKEN:

        print(
            "❌ DISCORD_TOKEN غير موجود "
            "في Environment Variables."
        )

        raise SystemExit(1)

    print("🚀 Starting MyAI...")

    print(
        f"📡 Message Content Intent configured: "
        f"{intents.message_content}"
    )

    try:

        bot.run(TOKEN)

    except Exception:

        print("❌ BOT CRASHED")
        traceback.print_exc()
