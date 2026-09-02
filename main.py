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


# =========================================================
# AI CONFIG
# =========================================================

AI_PROVIDER = os.getenv(
    "PRIMARY_AI_PROVIDER",
    "google"
).lower().strip()

AI_MODEL = os.getenv(
    "GOOGLE_MODEL",
    "gemini-3.5-flash-lite"
).strip()


# =========================================================
# AI MODES
# =========================================================

AI_MODES = {
    "normal": {
        "name": "Normal",
        "temperature": 0.7,
    },

    "friendly": {
        "name": "Friendly",
        "temperature": 0.85,
    },

    "active": {
        "name": "Active",
        "temperature": 0.9,
    },

    "fun": {
        "name": "Fun",
        "temperature": 1.0,
    },

    "professional": {
        "name": "Professional",
        "temperature": 0.5,
    },
}


# =========================================================
# DISCORD INTENTS
# =========================================================

intents = discord.Intents.default()

intents.guilds = True
intents.messages = True
intents.message_content = True


# =========================================================
# DATABASE + AI
# =========================================================

db = Database()
ai = AIEngine(db)


# =========================================================
# MEMORY
# =========================================================

message_memory = {}

auto_message_counters = {}
auto_last_reply = {}

bot_chat_counters = {}
bot_chat_last_reply = {}


# =========================================================
# BOT CLASS
# =========================================================

class MyAIBot(commands.Bot):

    async def setup_hook(self):

        try:

            synced = await self.tree.sync()

            print(
                f"Synced {len(synced)} slash commands."
            )

        except Exception:

            traceback.print_exc()


bot = MyAIBot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# HELPERS
# =========================================================

def get_config(guild_id):

    try:

        config = db.get_guild_config(
            guild_id
        )

        if config is None:
            return {}

        return dict(config)

    except Exception:

        traceback.print_exc()

        return {}


def save_config(
    guild_id,
    **kwargs
):

    try:

        return db.update_guild_config(
            guild_id,
            **kwargs
        )

    except Exception:

        traceback.print_exc()

        return None


def row_to_dict(row):

    if row is None:
        return None

    if isinstance(row, dict):
        return row

    try:

        return dict(row)

    except Exception:

        return row


# =========================================================
# CHARACTER HELPER
# =========================================================

def get_character(
    guild_id,
    character_id
):

    try:

        # character_id from /character_use
        # is an integer database ID.

        character = db.get_character_by_id(
            guild_id,
            int(character_id)
        )

        return row_to_dict(
            character
        )

    except (
        TypeError,
        ValueError
    ):

        return None

    except Exception:

        traceback.print_exc()

        return None


def get_active_character(
    guild_id
):

    try:

        return row_to_dict(
            db.get_active_character(
                guild_id
            )
        )

    except Exception:

        traceback.print_exc()

        return None


def normalize_channel_id(value):

    if value is None:
        return None

    try:

        return int(value)

    except (
        TypeError,
        ValueError
    ):

        return None


def channel_matches(
    message,
    configured_channel
):

    configured_channel = normalize_channel_id(
        configured_channel
    )

    # No configured channel = all channels.

    if configured_channel is None:
        return True

    return (
        message.channel.id
        == configured_channel
    )


def as_bool(value):

    if isinstance(value, bool):
        return value

    if value is None:
        return False

    return str(
        value
    ).lower().strip() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def split_message(
    text,
    max_length=1900
):

    if not text:
        return []

    return [
        text[i:i + max_length]
        for i in range(
            0,
            len(text),
            max_length
        )
    ]


# =========================================================
# SEND AI RESPONSE
# =========================================================

async def send_ai_response(
    message,
    response,
    reply=True
):

    if not response:
        return

    chunks = split_message(
        response
    )

    for index, chunk in enumerate(chunks):

        try:

            if (
                reply
                and index == 0
            ):

                await message.reply(
                    chunk,
                    mention_author=False
                )

            else:

                await message.channel.send(
                    chunk
                )

        except discord.Forbidden:

            print(
                "❌ Missing permission "
                "to send messages."
            )

            return

        except discord.HTTPException:

            traceback.print_exc()

            return


# =========================================================
# PERMISSIONS
# =========================================================

def has_management_permission(
    member
):

    if member is None:
        return False

    try:

        permissions = (
            member.guild_permissions
        )

        return (
            permissions.administrator
            or permissions.manage_guild
        )

    except Exception:

        return False


def can_manage_ai(obj):
    """
    Supports both:

    discord.Interaction
    discord.Message
    """

    # -----------------------------------------------------
    # Slash command
    # -----------------------------------------------------

    if isinstance(
        obj,
        discord.Interaction
    ):

        member = obj.user

    # -----------------------------------------------------
    # Normal message
    # -----------------------------------------------------

    elif isinstance(
        obj,
        discord.Message
    ):

        member = obj.author

    else:

        return False

    # -----------------------------------------------------
    # Member check
    # -----------------------------------------------------

    if not isinstance(
        member,
        discord.Member
    ):

        return False

    return has_management_permission(
        member
    )


# =========================================================
# TEXT HELPERS
# =========================================================

def clean_mentions(text):

    if not text:
        return ""

    text = re.sub(
        r"<@!?\d+>",
        "",
        text
    )

    return text.strip()


def normalize_text(text):

    return " ".join(
        text.lower().strip().split()
    )


def is_directed_to_bot(
    message
):

    if bot.user is None:
        return False

    # -----------------------------------------------------
    # Discord mention
    # -----------------------------------------------------

    if bot.user in message.mentions:
        return True

    # -----------------------------------------------------
    # Text detection
    # -----------------------------------------------------

    content = normalize_text(
        clean_mentions(
            message.content
        )
    )

    bot_name = normalize_text(
        bot.user.name
    )

    if not content:
        return False

    return (
        content.startswith(
            bot_name
        )
        or content.startswith(
            f"@{bot_name}"
        )
    )


# =========================================================
# AI GENERATION
# =========================================================

async def generate_chat_reply(
    message,
    config
):

    try:

        guild_id = message.guild.id

        character = get_active_character(
            guild_id
        )

        mode = str(
            config.get(
                "mode",
                "normal"
            )
        ).lower().strip()

        if mode not in AI_MODES:

            mode = "normal"

        user_text = clean_mentions(
            message.content
        )

        if not user_text:

            return None

        history = message_memory.setdefault(
            message.channel.id,
            []
        )

        history.append({
            "role": "user",
            "content": user_text,
        })

        if len(history) > 20:

            del history[:-20]

        response = await ai.generate(
            prompt=user_text,
            guild_id=guild_id,
            channel_id=message.channel.id,
            user_id=message.author.id,
            character=character,
            mode=mode,
            history=history,
        )

        if response:

            history.append({
                "role": "assistant",
                "content": response,
            })

        return response

    except Exception:

        traceback.print_exc()

        return None


# =========================================================
# AUTO AI
# =========================================================

async def handle_auto_ai(
    message,
    config
):

    channel_id = message.channel.id

    auto_message_counters[
        channel_id
    ] = auto_message_counters.get(
        channel_id,
        0
    ) + 1

    count = auto_message_counters[
        channel_id
    ]

    print(
        f"🔄 Auto counter: "
        f"{count}/{AUTO_CHECK_MESSAGE_COUNT}"
    )

    if count < AUTO_CHECK_MESSAGE_COUNT:

        return

    now = time.time()

    last_reply = auto_last_reply.get(
        channel_id,
        0
    )

    if (
        now - last_reply
        < AUTO_COOLDOWN_SECONDS
    ):

        print(
            "⏳ Auto cooldown active."
        )

        return

    auto_message_counters[
        channel_id
    ] = 0

    auto_last_reply[
        channel_id
    ] = now

    try:

        character = get_active_character(
            message.guild.id
        )

        response = await ai.generate_proactive(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            character=character,
            mode=config.get(
                "mode",
                "normal"
            ),
        )

        if response:

            response = response.replace(
                "ALERT:",
                ""
            ).strip()

            await send_ai_response(
                message,
                response,
                reply=False
            )

    except Exception:

        traceback.print_exc()


# =========================================================
# BOT CHAT SAFETY
# =========================================================

def bot_chat_allowed(
    message
):

    channel_id = message.channel.id

    now = time.time()

    last = bot_chat_last_reply.get(
        channel_id,
        0
    )

    if (
        now - last
        < BOT_CHAT_COOLDOWN_SECONDS
    ):

        return False

    count = bot_chat_counters.get(
        channel_id,
        0
    )

    if count >= BOT_CHAT_MAX_REPLIES:

        return False

    return True


def register_bot_chat_reply(
    message
):

    channel_id = message.channel.id

    bot_chat_counters[
        channel_id
    ] = bot_chat_counters.get(
        channel_id,
        0
    ) + 1

    bot_chat_last_reply[
        channel_id
    ] = time.time()


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    print()

    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    print(
        f"✅ Logged in as {bot.user} "
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
        f"{bot.intents.message_content}"
    )

    print(
        "🤖 Bot-to-Bot mode available."
    )

    print(
        f"🛡️ Bot Chat Safety | "
        f"max={BOT_CHAT_MAX_REPLIES} | "
        f"cooldown={BOT_CHAT_COOLDOWN_SECONDS}s"
    )

    print(
        f"🤖 Active AI Provider | "
        f"{AI_PROVIDER}"
    )

    print(
        f"🧠 Active AI Model | "
        f"{AI_MODEL}"
    )

    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )


# =========================================================
# RAW GATEWAY DIAGNOSTIC
# =========================================================

@bot.event
async def on_socket_raw_receive(
    msg
):

    try:

        if '"MESSAGE_CREATE"' in msg:

            print()
            print(
                "🟢 RAW MESSAGE_CREATE RECEIVED"
            )

    except Exception:

        traceback.print_exc()


# =========================================================
# MESSAGE EDIT DIAGNOSTIC
# =========================================================

@bot.event
async def on_message_edit(
    before,
    after
):

    print()
    print(
        "🟡 MESSAGE EDIT EVENT RECEIVED"
    )

    try:

        print(
            f"👤 Author : "
            f"{after.author}"
        )

        print(
            f"🏠 Guild  : "
            f"{after.guild}"
        )

        print(
            f"📍 Channel: "
            f"#{after.channel}"
        )

        print(
            f"📝 Before : "
            f"{before.content!r}"
        )

        print(
            f"📝 After  : "
            f"{after.content!r}"
        )

    except Exception:

        traceback.print_exc()


# =========================================================
# MESSAGE DELETE DIAGNOSTIC
# =========================================================

@bot.event
async def on_raw_message_delete(
    payload
):

    print()
    print(
        "🔴 RAW MESSAGE DELETE EVENT RECEIVED"
    )

    print(
        f"🆔 Message ID : "
        f"{payload.message_id}"
    )

    print(
        f"📍 Channel ID : "
        f"{payload.channel_id}"
    )


# =========================================================
# MAIN MESSAGE EVENT
# =========================================================

@bot.event
async def on_message(
    message
):

    # =====================================================
    # VERY FIRST DEBUG
    # =====================================================

    print()

    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    print(
        "📩 NEW MESSAGE EVENT RECEIVED"
    )

    print(
        f"👤 Sender     : "
        f"{message.author}"
    )

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
        f"{message.guild}"
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

    # =====================================================
    # MYAI OWN MESSAGES
    # =====================================================

    if (
        bot.user is not None
        and message.author.id
        == bot.user.id
    ):

        print(
            "⏭️ Ignored MyAI own message."
        )

        return

    # =====================================================
    # DMS
    # =====================================================

    if message.guild is None:

        print(
            "⏭️ Ignored DM message."
        )

        return

    # =====================================================
    # GET CONFIG
    # =====================================================

    config = get_config(
        message.guild.id
    )

    if not config:

        print(
            "⚠️ No AI configuration found."
        )

        return

    # =====================================================
    # ENABLED
    # =====================================================

    enabled = as_bool(
        config.get(
            "enabled",
            False
        )
    )

    if not enabled:

        print(
            "⏭️ AI system is disabled."
        )

        return

    # =====================================================
    # MODE
    # =====================================================

    mode = str(
        config.get(
            "mode",
            "mention"
        )
    ).lower().strip()

    # =====================================================
    # CHANNEL
    # =====================================================

    configured_channel = (
        config.get(
            "channel_id"
        )
        or config.get(
            "channel"
        )
    )

    if not channel_matches(
        message,
        configured_channel
    ):

        print(
            "⏭️ Message is outside "
            "configured AI channel."
        )

        return

    # =====================================================
    # BOT MESSAGE
    # =====================================================

    if message.author.bot:

        if mode != "bot_chat":

            print(
                "⏭️ Ignored other bot."
            )

            return

        if not is_directed_to_bot(
            message
        ):

            print(
                "⏭️ Bot message is not "
                "directed to MyAI."
            )

            return

        if not bot_chat_allowed(
            message
        ):

            print(
                "🛡️ Bot chat safety limit."
            )

            return

        register_bot_chat_reply(
            message
        )

    # =====================================================
    # MENTION
    # =====================================================

    if mode == "mention":

        if not is_directed_to_bot(
            message
        ):

            print(
                "⏭️ Mention mode: "
                "message did not mention MyAI."
            )

            return

    # =====================================================
    # DIRECT
    # =====================================================

    elif mode == "direct":

        if not is_directed_to_bot(
            message
        ):

            print(
                "⏭️ Direct mode: "
                "message is not directed to MyAI."
            )

            return

    # =====================================================
    # CHANNEL
    # =====================================================

    elif mode == "channel":

        print(
            "📢 Channel mode active."
        )

    # =====================================================
    # AUTO
    # =====================================================

    elif mode == "auto":

        print(
            "🔄 Auto mode active."
        )

        await handle_auto_ai(
            message,
            config
        )

        return

    # =====================================================
    # BOT CHAT
    # =====================================================

    elif mode == "bot_chat":

        print(
            "🤖 Bot-to-Bot mode active."
        )

    # =====================================================
    # UNKNOWN
    # =====================================================

    else:

        print(
            f"⚠️ Unknown AI mode: "
            f"{mode}"
        )

        return

    # =====================================================
    # GENERATE
    # =====================================================

    print(
        "🧠 Generating AI response..."
    )

    response = await generate_chat_reply(
        message,
        config
    )

    if not response:

        print(
            "⚠️ AI returned no response."
        )

        return

    print(
        "✅ AI response generated."
    )

    # =====================================================
    # SEND
    # =====================================================

    await send_ai_response(
        message,
        response,
        reply=True
    )


# =========================================================
# /ai
# =========================================================

@bot.tree.command(
    name="ai",
    description="تشغيل أو إيقاف نظام MyAI"
)
@app_commands.describe(
    enabled="تشغيل أو إيقاف الذكاء الاصطناعي"
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
            "❌ تحتاج صلاحية إدارة السيرفر.",
            ephemeral=True
        )

        return

    result = save_config(
        interaction.guild.id,
        enabled=enabled
    )

    if result is None:

        await interaction.response.send_message(
            "❌ تعذر حفظ إعدادات AI.",
            ephemeral=True
        )

        return

    state = (
        "مفعل"
        if enabled
        else "متوقف"
    )

    await interaction.response.send_message(
        f"✅ تم تحديث نظام AI: **{state}**",
        ephemeral=True
    )


# =========================================================
# SETUP SELECT
# =========================================================

class AISetupSelect(
    discord.ui.Select
):

    def __init__(self):

        options = [

            discord.SelectOption(
                label="Mention",
                description=(
                    "يرد عند منشن MyAI"
                ),
                value="mention"
            ),

            discord.SelectOption(
                label="Direct",
                description=(
                    "يرد عند توجيه الرسالة له"
                ),
                value="direct"
            ),

            discord.SelectOption(
                label="Channel",
                description=(
                    "يرد في الروم المحدد"
                ),
                value="channel"
            ),

            discord.SelectOption(
                label="Auto",
                description=(
                    "يرد تلقائيًا بعد عدد من الرسائل"
                ),
                value="auto"
            ),

            discord.SelectOption(
                label="Bot Chat",
                description=(
                    "التفاعل مع البوتات"
                ),
                value="bot_chat"
            ),
        ]

        super().__init__(
            placeholder="اختر نظام الرد",
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                "❌ يجب استخدام هذا داخل السيرفر.",
                ephemeral=True
            )

            return

        if not can_manage_ai(
            interaction
        ):

            await interaction.response.send_message(
                "❌ تحتاج صلاحية إدارة السيرفر.",
                ephemeral=True
            )

            return

        selected = self.values[0]

        result = save_config(
            interaction.guild.id,
            enabled=True,
            mode=selected
        )

        if result is None:

            await interaction.response.send_message(
                "❌ تعذر حفظ الإعداد.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            f"✅ تم تفعيل نظام الرد: "
            f"`{self.values[0]}`",
            ephemeral=True
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
    description="إعداد نظام رد MyAI"
)
async def ai_setup(
    interaction: discord.Interaction
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ استخدم الأمر داخل السيرفر.",
            ephemeral=True
        )

        return

    if not can_manage_ai(
        interaction
    ):

        await interaction.response.send_message(
            "❌ تحتاج صلاحية إدارة السيرفر.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        "⚙️ اختر نظام الرد الذي تريده:",
        view=AISetupView(),
        ephemeral=True
    )


# =========================================================
# /character_create
# =========================================================

@bot.tree.command(
    name="character_create",
    description="إنشاء شخصية AI"
)
@app_commands.describe(
    name="اسم الشخصية",
    personality="شخصية وتعريف الشخصية"
)
async def character_create(
    interaction: discord.Interaction,
    name: str,
    personality: str
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ استخدم الأمر داخل السيرفر.",
            ephemeral=True
        )

        return

    if not can_manage_ai(
        interaction
    ):

        await interaction.response.send_message(
            "❌ تحتاج صلاحية إدارة السيرفر.",
            ephemeral=True
        )

        return

    try:

        character = db.create_character(
            guild_id=interaction.guild.id,
            name=name,
            personality=personality
        )

        character = row_to_dict(
            character
        )

        character_id = (
            character.get("id")
            if character
            else "?"
        )

        await interaction.response.send_message(
            f"✅ تم إنشاء الشخصية "
            f"**{name}**\n"
            f"🆔 ID: `{character_id}`",
            ephemeral=True
        )

    except ValueError as exc:

        await interaction.response.send_message(
            f"❌ {exc}",
            ephemeral=True
        )

    except Exception:

        traceback.print_exc()

        await interaction.response.send_message(
            "❌ حدث خطأ أثناء إنشاء الشخصية.",
            ephemeral=True
        )


# =========================================================
# /character_list
# =========================================================

@bot.tree.command(
    name="character_list",
    description="عرض شخصيات AI"
)
async def character_list(
    interaction: discord.Interaction
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ استخدم الأمر داخل السيرفر.",
            ephemeral=True
        )

        return

    try:

        characters = db.list_characters(
            interaction.guild.id
        )

        if not characters:

            await interaction.response.send_message(
                "📭 لا توجد شخصيات.",
                ephemeral=True
            )

            return

        lines = []

        for character in characters:

            character = row_to_dict(
                character
            )

            name = character.get(
                "name",
                "Unknown"
            )

            character_id = character.get(
                "id",
                "?"
            )

            lines.append(
                f"• `{character_id}` — "
                f"**{name}**"
            )

        await interaction.response.send_message(
            "🧠 **الشخصيات:**\n\n"
            + "\n".join(lines),
            ephemeral=True
        )

    except Exception:

        traceback.print_exc()

        await interaction.response.send_message(
            "❌ حدث خطأ.",
            ephemeral=True
        )


# =========================================================
# /character_use
# =========================================================

@bot.tree.command(
    name="character_use",
    description="اختيار شخصية AI"
)
@app_commands.describe(
    character_id="رقم الشخصية"
)
async def character_use(
    interaction: discord.Interaction,
    character_id: int
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ استخدم الأمر داخل السيرفر.",
            ephemeral=True
        )

        return

    if not can_manage_ai(
        interaction
    ):

        await interaction.response.send_message(
            "❌ تحتاج صلاحية إدارة السيرفر.",
            ephemeral=True
        )

        return

    try:

        character = get_character(
            interaction.guild.id,
            character_id
        )

        if not character:

            await interaction.response.send_message(
                "❌ الشخصية غير موجودة.",
                ephemeral=True
            )

            return

        # Database now supports both
        # integer IDs and character names.

        db.set_active_character(
            interaction.guild.id,
            character_id
        )

        await interaction.response.send_message(
            f"✅ تم اختيار الشخصية: "
            f"**{character.get('name', 'Unknown')}**",
            ephemeral=True
        )

    except Exception:

        traceback.print_exc()

        await interaction.response.send_message(
            "❌ حدث خطأ أثناء اختيار الشخصية.",
            ephemeral=True
        )


# =========================================================
# /ai_status
# =========================================================

@bot.tree.command(
    name="ai_status",
    description="عرض حالة MyAI"
)
async def ai_status(
    interaction: discord.Interaction
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ استخدم الأمر داخل السيرفر.",
            ephemeral=True
        )

        return

    config = get_config(
        interaction.guild.id
    )

    enabled = as_bool(
        config.get(
            "enabled",
            False
        )
    )

    mode = config.get(
        "mode",
        "unknown"
    )

    channel_id = (
        config.get(
            "channel_id"
        )
        or config.get(
            "channel"
        )
    )

    character = get_active_character(
        interaction.guild.id
    )

    character_name = (
        character.get("name")
        if character
        else "None"
    )

    provider = config.get(
        "provider",
        AI_PROVIDER
    )

    model = config.get(
        "model",
        AI_MODEL
    )

    embed = discord.Embed(
        title="🤖 MyAI Status",
        description=(
            "حالة نظام الذكاء الاصطناعي"
        )
    )

    embed.add_field(
        name="Status",
        value=(
            "🟢 Enabled"
            if enabled
            else "🔴 Disabled"
        ),
        inline=True
    )

    embed.add_field(
        name="Mode",
        value=str(mode),
        inline=True
    )

    embed.add_field(
        name="Channel",
        value=(
            f"<#{channel_id}>"
            if channel_id
            else "All"
        ),
        inline=True
    )

    embed.add_field(
        name="Character",
        value=character_name,
        inline=True
    )

    embed.add_field(
        name="Provider",
        value=str(provider),
        inline=True
    )

    embed.add_field(
        name="Model",
        value=str(model),
        inline=True
    )

    embed.add_field(
        name="Message Content Intent",
        value=str(
            bot.intents.message_content
        ),
        inline=True
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# =========================================================
# /ai_memory_clear
# =========================================================

@bot.tree.command(
    name="ai_memory_clear",
    description="مسح ذاكرة MyAI للروم"
)
async def ai_memory_clear(
    interaction: discord.Interaction
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ استخدم الأمر داخل السيرفر.",
            ephemeral=True
        )

        return

    if not can_manage_ai(
        interaction
    ):

        await interaction.response.send_message(
            "❌ تحتاج صلاحية إدارة السيرفر.",
            ephemeral=True
        )

        return

    if interaction.channel:

        message_memory.pop(
            interaction.channel.id,
            None
        )

    await interaction.response.send_message(
        "🧹 تم مسح ذاكرة MyAI لهذا الروم.",
        ephemeral=True
    )


# =========================================================
# GLOBAL ERROR HANDLER
# =========================================================

@bot.tree.error
async def on_app_command_error(
    interaction,
    error
):

    print()
    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    print(
        "❌ APP COMMAND ERROR"
    )

    print(
        f"Command: "
        f"{getattr(interaction.command, 'name', 'Unknown')}"
    )

    print(
        f"Error: "
        f"{error!r}"
    )

    traceback.print_exception(
        type(error),
        error,
        error.__traceback__
    )

    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    try:

        if interaction.response.is_done():

            await interaction.followup.send(
                "❌ حدث خطأ أثناء تنفيذ الأمر.",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "❌ حدث خطأ أثناء تنفيذ الأمر.",
                ephemeral=True
            )

    except Exception:

        pass


# =========================================================
# START
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "❌ DISCORD_TOKEN غير موجود "
        "في Environment Variables."
    )


print(
    f"🤖 AI CONFIG | "
    f"provider={AI_PROVIDER} | "
    f"model={AI_MODEL}"
)

print(
    f"📡 Message Content Intent configured: "
    f"{intents.message_content}"
)

print(
    "🚀 Starting MyAI..."
)


bot.run(
    TOKEN
        )
