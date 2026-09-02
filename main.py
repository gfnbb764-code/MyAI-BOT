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

if AI_PROVIDER not in {
    "openai",
    "google",
    "anthropic"
}:
    AI_PROVIDER = "google"

    AI_MODEL = os.getenv(
        "GOOGLE_MODEL",
        "gemini-3.5-flash-lite"
    ).strip()

print(
    f"🤖 AI CONFIG | provider={AI_PROVIDER} | model={AI_MODEL}"
)


# =========================================================
# AI MODES
# =========================================================

AI_MODES = {
    "normal",
    "friendly",
    "active",
    "fun",
    "professional",
}


def get_ai_mode(config):

    mode = str(
        config.get(
            "mode",
            "normal"
        )
    ).lower().strip()

    if mode not in AI_MODES:
        mode = "normal"

    return mode


# =========================================================
# BOOLEAN HELPER
# =========================================================

def as_bool(value):

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    if value is None:
        return False

    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled"
    }


# =========================================================
# INTENTS
# =========================================================

intents = discord.Intents.default()

intents.guilds = True
intents.messages = True
intents.message_content = True


# =========================================================
# DATABASE / AI
# =========================================================

db = Database()
ai = AIEngine(db)


# =========================================================
# MEMORY
# =========================================================

auto_message_counters = {}
auto_last_check = {}

bot_chat_reply_counts = {}
bot_chat_last_reply = {}


# =========================================================
# BOT
# =========================================================

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

        except Exception:

            print(
                "❌ Failed to sync slash commands:"
            )

            traceback.print_exc()


bot = MyAIBot()


# =========================================================
# DATABASE HELPERS
# =========================================================

def get_config(guild_id):

    try:

        return db.get_ai_config(
            guild_id
        )

    except Exception:

        print(
            "❌ Failed to load AI config:"
        )

        traceback.print_exc()

        return None


def save_config(
    guild_id,
    **kwargs
):

    try:

        return db.save_ai_config(
            guild_id,
            **kwargs
        )

    except Exception:

        print(
            "❌ Failed to save AI config:"
        )

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

        try:

            return {
                key: row[key]
                for key in row.keys()
            }

        except Exception:

            return row


def get_character(
    guild_id,
    character_name
):

    try:

        if not character_name:
            return None

        character = db.get_character(
            guild_id,
            character_name
        )

        return row_to_dict(
            character
        )

    except Exception:

        print(
            "❌ Failed to get character:"
        )

        traceback.print_exc()

        return None


def get_active_character(
    guild_id,
    config
):

    character_name = config.get(
        "character_name"
    )

    character = get_character(
        guild_id,
        character_name
    )

    if character:
        return character

    try:

        characters = db.get_characters(
            guild_id
        )

        if characters:

            return row_to_dict(
                characters[0]
            )

    except Exception:

        print(
            "❌ Failed to get guild characters:"
        )

        traceback.print_exc()

    return None


# =========================================================
# CHANNEL
# =========================================================

def normalize_channel_id(
    channel_id
):

    if channel_id is None:
        return None

    try:

        return int(
            str(channel_id).strip()
        )

    except (
        TypeError,
        ValueError
    ):

        return None


def channel_matches(
    message,
    configured_channel_id
):

    current = normalize_channel_id(
        message.channel.id
    )

    configured = normalize_channel_id(
        configured_channel_id
    )

    result = (
        current is not None
        and configured is not None
        and current == configured
    )

    print(
        "📍 CHANNEL CHECK | "
        f"current={current} | "
        f"configured={configured} | "
        f"match={result}"
    )

    return result


# =========================================================
# MESSAGE SPLITTER
# =========================================================

def split_message(
    text,
    limit=1900
):

    if not text:
        return []

    text = str(text)

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
            text[:split_at]
        )

        text = text[
            split_at:
        ].lstrip()

    if text:
        chunks.append(
            text
        )

    return chunks


# =========================================================
# SEND AI RESPONSE
# =========================================================

async def send_ai_response(
    message,
    response
):

    if not response:
        return False

    chunks = split_message(
        response
    )

    if not chunks:
        return False

    try:

        await message.reply(
            chunks[0],
            mention_author=False
        )

        print(
            "↩️🔥 AI REPLIED TO ORIGINAL MESSAGE"
        )

    except discord.Forbidden:

        print(
            "❌ Discord Forbidden: "
            "MyAI cannot send/reply in this channel."
        )

        return False

    except discord.HTTPException:

        print(
            "❌ Discord HTTP error while replying:"
        )

        traceback.print_exc()

        return False

    except Exception:

        print(
            "❌ Failed to reply:"
        )

        traceback.print_exc()

        return False

    for chunk in chunks[1:]:

        try:

            await message.channel.send(
                chunk
            )

        except Exception:

            print(
                "❌ Failed to send extra chunk:"
            )

            traceback.print_exc()

            return False

    return True


# =========================================================
# PERMISSIONS
# =========================================================

def has_management_permission(
    member: discord.Member
):

    if member.guild.owner_id == member.id:
        return True

    if member.guild_permissions.administrator:
        return True

    roles = sorted(
        member.roles,
        key=lambda role: role.position,
        reverse=True
    )

    top_roles = [
        role
        for role in member.guild.roles
        if not role.is_default()
    ]

    top_roles = sorted(
        top_roles,
        key=lambda role: role.position,
        reverse=True
    )[:4]

    return any(
        role in top_roles
        for role in roles
    )


def can_manage_ai(
    interaction: discord.Interaction
):

    if not interaction.guild:
        return False

    member = interaction.user

    if not isinstance(
        member,
        discord.Member
    ):
        return False

    return has_management_permission(
        member
    )


# =========================================================
# MENTION CLEANER
# =========================================================

def clean_bot_mention(
    content
):

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


# =========================================================
# TEXT NORMALIZATION
# =========================================================

def normalize_text(
    text
):

    if not text:
        return ""

    text = str(text).lower()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# =========================================================
# DIRECT DETECTION
# =========================================================

def is_directed_to_bot(
    message: discord.Message
):

    if bot.user is None:
        return False

    if any(
        user.id == bot.user.id
        for user in message.mentions
    ):
        return True

    reference = getattr(
        message,
        "reference",
        None
    )

    if reference:

        resolved = getattr(
            reference,
            "resolved",
            None
        )

        if resolved:

            author = getattr(
                resolved,
                "author",
                None
            )

            if (
                author
                and author.id == bot.user.id
            ):
                return True

    content = normalize_text(
        message.content
    )

    if not content:
        return False

    names = {
        normalize_text(
            bot.user.name
        ),
        normalize_text(
            bot.user.display_name
        ),
        "myai",
        "my ai"
    }

    names = {
        name
        for name in names
        if name
    }

    for name in names:

        escaped = re.escape(
            name
        )

        patterns = [

            rf"^{escaped}$",

            rf"^{escaped}\s+",

            rf"^{escaped}\s*[:،,]",

            rf"^يا\s+{escaped}\b",

            rf"^hey\s+{escaped}\b",

            rf"^hello\s+{escaped}\b",
        ]

        for pattern in patterns:

            if re.search(
                pattern,
                content,
                re.IGNORECASE
            ):
                return True

    return False


# =========================================================
# AI CHAT
# =========================================================

async def generate_chat_reply(
    message,
    config,
    character,
    user_message
):

    provider = AI_PROVIDER
    model = AI_MODEL
    mode = get_ai_mode(config)

    character_name = character.get(
        "name"
    )

    print(
        "🧠 AI REQUEST | "
        f"provider={provider} | "
        f"model={model} | "
        f"mode={mode} | "
        f"character={character_name}"
    )

    response = await ai.generate(
        guild_id=message.guild.id,
        channel_id=message.channel.id,
        user_id=message.author.id,
        character_name=character_name,
        user_message=user_message,
        provider=provider,
        model=model,
        mode=mode
    )

    if not response:

        print(
            "⚠️ AI returned empty response."
        )

        return False

    print(
        f"✅ AI RESPONSE RECEIVED | "
        f"length={len(response)}"
    )

    return await send_ai_response(
        message,
        response
    )


# =========================================================
# AUTO AI
# =========================================================

async def handle_auto_ai(
    message,
    config,
    character
):

    channel_id = message.channel.id

    count = (
        auto_message_counters.get(
            channel_id,
            0
        )
        + 1
    )

    auto_message_counters[
        channel_id
    ] = count

    print(
        "🤖 AUTO COUNTER | "
        f"channel={channel_id} | "
        f"count={count}/{AUTO_CHECK_MESSAGE_COUNT}"
    )

    if count < AUTO_CHECK_MESSAGE_COUNT:
        return

    auto_message_counters[
        channel_id
    ] = 0

    now = time.time()

    last = auto_last_check.get(
        channel_id,
        0
    )

    elapsed = now - last

    if elapsed < AUTO_COOLDOWN_SECONDS:

        remaining = int(
            AUTO_COOLDOWN_SECONDS - elapsed
        )

        print(
            f"⏳ AUTO COOLDOWN | "
            f"remaining={remaining}s"
        )

        return

    auto_last_check[
        channel_id
    ] = now

    print(
        "🤖 Running proactive AI check..."
    )

    response = await ai.generate_proactive(
        guild_id=message.guild.id,
        channel_id=message.channel.id,
        character_name=character.get(
            "name"
        ),
        provider=AI_PROVIDER,
        model=AI_MODEL
    )

    if not response:
        return

    response = str(
        response
    ).strip()

    if response.upper() == "NO_ALERT":

        print(
            "🤖 AI decided: NO_ALERT"
        )

        return

    if response.upper().startswith(
        "ALERT:"
    ):

        response = response[
            len("ALERT:"):
        ].strip()

    if not response:
        return

    await send_ai_response(
        message,
        response
    )


# =========================================================
# BOT CHAT SAFETY
# =========================================================

def bot_chat_allowed(
    channel_id
):

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

    count = bot_chat_reply_counts.get(
        channel_id,
        0
    )

    if count >= BOT_CHAT_MAX_REPLIES:

        return False

    return True


def register_bot_chat_reply(
    channel_id
):

    bot_chat_reply_counts[
        channel_id
    ] = (
        bot_chat_reply_counts.get(
            channel_id,
            0
        ) + 1
    )

    bot_chat_last_reply[
        channel_id
    ] = time.time()


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

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


# =========================================================
# TEMP DEBUG - MESSAGE EDIT
# =========================================================

@bot.event
async def on_message_edit(
    before: discord.Message,
    after: discord.Message
):

    try:

        print(
            "\n"
            "🟡 MESSAGE EDIT EVENT RECEIVED\n"
            f"👤 Author     : {after.author}\n"
            f"🤖 Is Bot     : {after.author.bot}\n"
            f"🏠 Server     : "
            f"{after.guild.name if after.guild else 'DM'}\n"
            f"💬 Channel    : "
            f"{getattr(after.channel, 'name', after.channel)}\n"
            f"🆔 Channel ID : {after.channel.id}\n"
            f"📝 Before     : {before.content!r}\n"
            f"📝 After      : {after.content!r}\n"
        )

    except Exception:

        print(
            "❌ Message edit debug error:"
        )

        traceback.print_exc()


# =========================================================
# TEMP DEBUG - RAW MESSAGE DELETE
# =========================================================

@bot.event
async def on_raw_message_delete(
    payload
):

    try:

        print(
            "\n"
            "🔴 RAW MESSAGE DELETE EVENT RECEIVED\n"
            f"🆔 Message ID : {payload.message_id}\n"
            f"🆔 Channel ID : {payload.channel_id}\n"
            f"🆔 Guild ID   : {payload.guild_id}\n"
        )

    except Exception:

        print(
            "❌ Message delete debug error:"
        )

        traceback.print_exc()


# =========================================================
# ON MESSAGE
# =========================================================

@bot.event
async def on_message(
    message: discord.Message
):

    # =====================================================
    # DEBUG: EVENT RECEIVED
    # =====================================================

    print(
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📩 NEW MESSAGE EVENT RECEIVED\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    try:

        print(
            f"👤 Sender     : {message.author}"
        )

        print(
            f"🆔 Sender ID  : {message.author.id}"
        )

        print(
            f"🤖 Is Bot     : {message.author.bot}"
        )

        print(
            f"🏠 Server     : "
            f"{message.guild.name if message.guild else 'DM'}"
        )

        print(
            f"🆔 Server ID  : "
            f"{message.guild.id if message.guild else None}"
        )

        print(
            f"💬 Channel    : "
            f"{getattr(message.channel, 'name', message.channel)}"
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
            f"🏷️ Mentions   : "
            f"{[f'{u} ({u.id})' for u in message.mentions]}"
        )

        print(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

    except Exception:

        print(
            "❌ Message logging error:"
        )

        traceback.print_exc()

    # =====================================================
    # DM
    # =====================================================

    if message.guild is None:

        print(
            "⏭️ Ignored DM message."
        )

        return

    # =====================================================
    # ONLY IGNORE MYAI ITSELF
    # =====================================================

    if (
        bot.user is not None
        and message.author.id == bot.user.id
    ):

        print(
            "⏭️ Ignored MyAI own message."
        )

        return

    # =====================================================
    # LOAD CONFIG
    # =====================================================

    guild_id = message.guild.id

    config = get_config(
        guild_id
    )

    if config is None:

        print(
            "❌ No AI config."
        )

        return

    config = row_to_dict(
        config
    )

    enabled = as_bool(
        config.get(
            "enabled",
            0
        )
    )

    reply_type = str(
        config.get(
            "reply_type",
            "mention"
        )
    ).lower().strip()

    print(
        "⚙️ CONFIG | "
        f"enabled={enabled} | "
        f"type={reply_type} | "
        f"channel={config.get('channel_id')} | "
        f"character={config.get('character_name')}"
    )

    # =====================================================
    # COMMANDS
    # =====================================================

    try:

        await bot.process_commands(
            message
        )

    except Exception:

        print(
            "❌ process_commands error:"
        )

        traceback.print_exc()

    # =====================================================
    # DISABLED
    # =====================================================

    if not enabled:

        print(
            "⏭️ AI disabled."
        )

        return

    # =====================================================
    # OTHER BOT FILTER
    # =====================================================

    if (
        message.author.bot
        and reply_type != "bot_chat"
    ):

        print(
            "⏭️ Ignored another bot message."
        )

        return

    # =====================================================
    # CHARACTER
    # =====================================================

    character = get_active_character(
        guild_id,
        config
    )

    if character is None:

        print(
            "❌ No character."
        )

        return

    print(
        f"🧠 Character loaded: "
        f"{character.get('name')}"
    )

    # =====================================================
    # MENTION
    # =====================================================

    if reply_type == "mention":

        print(
            "🎯 MODE = MENTION"
        )

        configured_channel = normalize_channel_id(
            config.get("channel_id")
        )

        if configured_channel is not None:

            if not channel_matches(
                message,
                configured_channel
            ):

                print(
                    "⏭️ Mention outside configured channel."
                )

                return

        mentioned = any(
            user.id == bot.user.id
            for user in message.mentions
        )

        print(
            f"🔎 MyAI mentioned = {mentioned}"
        )

        if not mentioned:

            print(
                "⏭️ MyAI was not mentioned."
            )

            return

        print(
            "🏷️🔥 MYAI MENTION DETECTED!"
        )

        user_message = clean_bot_mention(
            message.content
        )

        if not user_message:

            user_message = "السلام عليكم"

        print(
            f"💬 User message = "
            f"{user_message!r}"
        )

        try:

            success = await generate_chat_reply(
                message,
                config,
                character,
                user_message
            )

            if success:

                print(
                    "✅🔥 MENTION RESPONSE SENT!"
                )

        except Exception:

            print(
                "❌ Mention AI error:"
            )

            traceback.print_exc()

        return

    # =====================================================
    # CHANNEL
    # =====================================================

    if reply_type == "channel":

        print(
            "📢 MODE = CHANNEL"
        )

        configured_channel = normalize_channel_id(
            config.get("channel_id")
        )

        if configured_channel is None:

            print(
                "❌ No configured channel."
            )

            return

        if not channel_matches(
            message,
            configured_channel
        ):

            print(
                "⏭️ Outside AI channel."
            )

            return

        content = (
            message.content or ""
        ).strip()

        if not content:

            return

        try:

            success = await generate_chat_reply(
                message,
                config,
                character,
                content
            )

            if success:

                print(
                    "✅📢 CHANNEL RESPONSE SENT!"
                )

        except Exception:

            print(
                "❌ Channel AI error:"
            )

            traceback.print_exc()

        return

    # =====================================================
    # DIRECT
    # =====================================================

    if reply_type == "direct":

        print(
            "🎯 MODE = DIRECT"
        )

        configured_channel = normalize_channel_id(
            config.get("channel_id")
        )

        if configured_channel is not None:

            if not channel_matches(
                message,
                configured_channel
            ):

                print(
                    "⏭️ Direct message outside configured channel."
                )

                return

        if not is_directed_to_bot(
            message
        ):

            print(
                "⏭️ Message not directed to MyAI."
            )

            return

        user_message = clean_bot_mention(
            message.content
        )

        if not user_message:

            user_message = (
                message.content or ""
            ).strip()

        if not user_message:

            user_message = "السلام عليكم"

        try:

            await generate_chat_reply(
                message,
                config,
                character,
                user_message
            )

        except Exception:

            print(
                "❌ Direct AI error:"
            )

            traceback.print_exc()

        return

    # =====================================================
    # AUTO
    # =====================================================

    if reply_type == "auto":

        print(
            "🤖 MODE = AUTO"
        )

        configured_channel = normalize_channel_id(
            config.get("channel_id")
        )

        if configured_channel is not None:

            if not channel_matches(
                message,
                configured_channel
            ):

                print(
                    "⏭️ Auto message outside configured channel."
                )

                return

        try:

            await handle_auto_ai(
                message,
                config,
                character
            )

        except Exception:

            print(
                "❌ Auto AI error:"
            )

            traceback.print_exc()

        return

    # =====================================================
    # BOT CHAT
    # =====================================================

    if reply_type == "bot_chat":

        print(
            "🤖 MODE = BOT CHAT"
        )

        configured_channel = normalize_channel_id(
            config.get("channel_id")
        )

        if configured_channel is not None:

            if not channel_matches(
                message,
                configured_channel
            ):

                print(
                    "⏭️ Bot Chat message outside configured channel."
                )

                return

        if not bot_chat_allowed(
            message.channel.id
        ):

            print(
                "⏭️ Bot Chat safety blocked."
            )

            return

        directed = is_directed_to_bot(
            message
        )

        if not directed:

            print(
                "⏭️ Message not directed to MyAI."
            )

            return

        user_message = clean_bot_mention(
            message.content
        )

        if not user_message:

            user_message = (
                message.content or ""
            ).strip()

        if not user_message:

            user_message = "السلام عليكم"

        try:

            success = await generate_chat_reply(
                message,
                config,
                character,
                user_message
            )

            if success:

                register_bot_chat_reply(
                    message.channel.id
                )

                print(
                    "✅🤖 BOT CHAT RESPONSE SENT!"
                )

        except Exception:

            print(
                "❌ Bot Chat AI error:"
            )

            traceback.print_exc()

        return

    # =====================================================
    # UNKNOWN TYPE
    # =====================================================

    print(
        f"⚠️ Unknown reply type: "
        f"{reply_type!r}"
    )


# =========================================================
# /AI
# =========================================================

@bot.tree.command(
    name="ai",
    description="تحدث مع الذكاء الاصطناعي"
)
@app_commands.describe(
    message="رسالتك للذكاء الاصطناعي"
)
async def ai_command(
    interaction: discord.Interaction,
    message: str
):

    await interaction.response.defer()

    if interaction.guild is None:

        await interaction.followup.send(
            "❌ هذا الأمر يعمل داخل السيرفر فقط."
        )

        return

    guild_id = interaction.guild.id

    config = get_config(
        guild_id
    )

    if config is None:

        await interaction.followup.send(
            "❌ تعذر تحميل إعدادات الذكاء الاصطناعي."
        )

        return

    config = row_to_dict(
        config
    )

    character = get_active_character(
        guild_id,
        config
    )

    if character is None:

        await interaction.followup.send(
            "❌ لا توجد شخصية AI."
        )

        return

    try:

        response = await ai.generate(
            guild_id=guild_id,
            channel_id=interaction.channel.id,
            user_id=interaction.user.id,
            character_name=character.get(
                "name"
            ),
            user_message=message,
            provider=AI_PROVIDER,
            model=AI_MODEL,
            mode=get_ai_mode(config)
        )

        if not response:

            await interaction.followup.send(
                "⚠️ الذكاء الاصطناعي لم يرجع ردًا."
            )

            return

        chunks = split_message(
            response
        )

        for chunk in chunks:

            await interaction.followup.send(
                chunk
            )

    except Exception:

        print(
            "❌ /ai error:"
        )

        traceback.print_exc()

        await interaction.followup.send(
            "❌ حدث خطأ أثناء تشغيل الذكاء الاصطناعي."
        )


# =========================================================
# SETUP CHANNEL
# =========================================================

class SetupChannelSelect(
    discord.ui.ChannelSelect
):

    def __init__(self):

        super().__init__(
            placeholder="اختر روم الذكاء الاصطناعي",
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

        if not interaction.guild:

            await interaction.response.send_message(
                "❌ داخل السيرفر فقط.",
                ephemeral=True
            )

            return

        if not can_manage_ai(
            interaction
        ):

            await interaction.response.send_message(
                "❌ ما عندك صلاحية.",
                ephemeral=True
            )

            return

        channel = self.values[0]

        save_config(
            interaction.guild.id,
            channel_id=normalize_channel_id(
                channel.id
            ),
            enabled=True
        )

        await interaction.response.send_message(
            f"✅ تم اختيار الروم: "
            f"{channel.mention}\n"
            "🟢 تم تفعيل نظام الذكاء الاصطناعي.",
            ephemeral=True
        )


# =========================================================
# SETUP REPLY TYPE
# =========================================================

class SetupReplyTypeSelect(
    discord.ui.Select
):

    def __init__(
        self,
        guild_id
    ):

        self.guild_id = guild_id

        options = [

            discord.SelectOption(
                label="1 - Mention",
                value="mention",
                description="يرد عند منشن MyAI"
            ),

            discord.SelectOption(
                label="2 - Channel",
                value="channel",
                description="يرد على كل رسالة في الروم المحدد"
            ),

            discord.SelectOption(
                label="3 - Direct",
                value="direct",
                description="يرد عندما يكون الكلام موجهًا إليه"
            ),

            discord.SelectOption(
                label="4 - Auto",
                value="auto",
                description="يتابع المحادثة ويرسل ردودًا استباقية"
            ),

            discord.SelectOption(
                label="5 - Bot Chat",
                value="bot_chat",
                description="محادثة MyAI مع البوتات"
            ),
        ]

        super().__init__(
            placeholder="اختر نوع الرد",
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        if not can_manage_ai(
            interaction
        ):

            await interaction.response.send_message(
                "❌ ما عندك صلاحية.",
                ephemeral=True
            )

            return

        value = self.values[0]

        save_config(
            self.guild_id,
            reply_type=value,
            enabled=True
        )

        names = {
            "mention": "Mention",
            "channel": "Channel",
            "direct": "Direct",
            "auto": "Auto",
            "bot_chat": "Bot Chat"
        }

        await interaction.response.send_message(
            f"✅ تم تفعيل نظام الرد: "
            f"`{names.get(value, value)}`",
            ephemeral=True
        )


# =========================================================
# SETUP VIEW
# =========================================================

class SetupView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id
    ):

        super().__init__(
            timeout=300
        )

        self.guild_id = guild_id

        self.add_item(
            SetupChannelSelect()
        )

        self.add_item(
            SetupReplyTypeSelect(
                guild_id
            )
        )

    @discord.ui.button(
        label="تفعيل",
        style=discord.ButtonStyle.success
    )
    async def enable_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not can_manage_ai(
            interaction
        ):

            await interaction.response.send_message(
                "❌ ما عندك صلاحية.",
                ephemeral=True
            )

            return

        save_config(
            self.guild_id,
            enabled=True
        )

        await interaction.response.send_message(
            "🟢 تم تفعيل الذكاء الاصطناعي.",
            ephemeral=True
        )

    @discord.ui.button(
        label="تعطيل",
        style=discord.ButtonStyle.danger
    )
    async def disable_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not can_manage_ai(
            interaction
        ):

            await interaction.response.send_message(
                "❌ ما عندك صلاحية.",
                ephemeral=True
            )

            return

        save_config(
            self.guild_id,
            enabled=False
        )

        await interaction.response.send_message(
            "🔴 تم تعطيل الذكاء الاصطناعي.",
            ephemeral=True
        )


# =========================================================
# /AI SETUP
# =========================================================

@bot.tree.command(
    name="ai_setup",
    description="إعداد نظام الذكاء الاصطناعي"
)
async def ai_setup(
    interaction: discord.Interaction
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    if not can_manage_ai(
        interaction
    ):

        await interaction.response.send_message(
            "❌ ما عندك صلاحية.",
            ephemeral=True
        )

        return

    config = get_config(
        interaction.guild.id
    )

    if config is None:

        await interaction.response.send_message(
            "❌ تعذر تحميل الإعدادات.",
            ephemeral=True
        )

        return

    config = row_to_dict(
        config
    )

    reply_type = str(
        config.get(
            "reply_type",
            "mention"
        )
    )

    reply_names = {
        "mention": "1 - Mention",
        "channel": "2 - Channel",
        "direct": "3 - Direct",
        "auto": "4 - Auto",
        "bot_chat": "5 - Bot Chat"
    }

    embed = discord.Embed(
        title="🤖 إعداد MyAI",
        description=(
            "اختر الروم ونوع الرد.\n\n"
            "اختيار نوع الرد يفعّله مباشرة."
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="الحالة",
        value=(
            "🟢 مفعّل"
            if as_bool(config.get("enabled", 0))
            else "🔴 معطّل"
        ),
        inline=True
    )

    embed.add_field(
        name="نوع الرد",
        value=reply_names.get(
            reply_type,
            reply_type
        ),
        inline=True
    )

    embed.add_field(
        name="الشخصية",
        value=str(
            config.get(
                "character_name",
                "غير محددة"
            )
        ),
        inline=True
    )

    channel_id = normalize_channel_id(
        config.get("channel_id")
    )

    embed.add_field(
        name="الروم",
        value=(
            f"<#{channel_id}>"
            if channel_id
            else "غير محدد"
        ),
        inline=True
    )

    embed.add_field(
        name="Provider",
        value=AI_PROVIDER.title(),
        inline=True
    )

    embed.add_field(
        name="Model",
        value=AI_MODEL,
        inline=True
    )

    embed.add_field(
        name="Mode",
        value=get_ai_mode(config),
        inline=True
    )

    await interaction.response.send_message(
        embed=embed,
        view=SetupView(
            interaction.guild.id
        )
    )


# =========================================================
# CHARACTER CREATE
# =========================================================

@bot.tree.command(
    name="character_create",
    description="إنشاء شخصية AI"
)
@app_commands.describe(
    name="اسم الشخصية",
    personality="وصف شخصية الذكاء الاصطناعي"
)
async def character_create(
    interaction: discord.Interaction,
    name: str,
    personality: str
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    if not can_manage_ai(
        interaction
    ):

        await interaction.response.send_message(
            "❌ ما عندك صلاحية.",
            ephemeral=True
        )

        return

    try:

        db.create_character(
            interaction.guild.id,
            name,
            personality
        )

        await interaction.response.send_message(
            f"✅ تم إنشاء الشخصية **{name}**."
        )

    except Exception:

        print(
            "❌ character_create error:"
        )

        traceback.print_exc()

        await interaction.response.send_message(
            "❌ تعذر إنشاء الشخصية.",
            ephemeral=True
        )


# =========================================================
# CHARACTER LIST
# =========================================================

@bot.tree.command(
    name="character_list",
    description="عرض شخصيات AI"
)
async def character_list(
    interaction: discord.Interaction
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    try:

        characters = db.get_characters(
            interaction.guild.id
        )

        if not characters:

            await interaction.response.send_message(
                "📭 لا توجد شخصيات."
            )

            return

        lines = []

        for character in characters:

            character = row_to_dict(
                character
            )

            lines.append(
                f"• **{character.get('name')}** — "
                f"{character.get('personality', 'بدون وصف')}"
            )

        embed = discord.Embed(
            title="🧠 شخصيات MyAI",
            description="\n".join(lines),
            color=discord.Color.blurple()
        )

        await interaction.response.send_message(
            embed=embed
        )

    except Exception:

        print(
            "❌ character_list error:"
        )

        traceback.print_exc()

        await interaction.response.send_message(
            "❌ تعذر تحميل الشخصيات.",
            ephemeral=True
        )


# =========================================================
# CHARACTER USE
# =========================================================

@bot.tree.command(
    name="character_use",
    description="تحديد شخصية AI الحالية"
)
@app_commands.describe(
    name="اسم الشخصية"
)
async def character_use(
    interaction: discord.Interaction,
    name: str
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    if not can_manage_ai(
        interaction
    ):

        await interaction.response.send_message(
            "❌ ما عندك صلاحية.",
            ephemeral=True
        )

        return

    character = get_character(
        interaction.guild.id,
        name
    )

    if character is None:

        await interaction.response.send_message(
            "❌ هذه الشخصية غير موجودة.",
            ephemeral=True
        )

        return

    save_config(
        interaction.guild.id,
        character_name=character.get(
            "name"
        )
    )

    await interaction.response.send_message(
        f"🧠 تم اختيار الشخصية "
        f"**{character.get('name')}**."
    )


# =========================================================
# AI STATUS
# =========================================================

@bot.tree.command(
    name="ai_status",
    description="عرض حالة نظام الذكاء الاصطناعي"
)
async def ai_status(
    interaction: discord.Interaction
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    config = get_config(
        interaction.guild.id
    )

    if config is None:

        await interaction.response.send_message(
            "❌ تعذر تحميل الحالة.",
            ephemeral=True
        )

        return

    config = row_to_dict(
        config
    )

    enabled = as_bool(
        config.get(
            "enabled",
            0
        )
    )

    channel_id = normalize_channel_id(
        config.get(
            "channel_id"
        )
    )

    reply_type = str(
        config.get(
            "reply_type",
            "mention"
        )
    )

    embed = discord.Embed(
        title="🤖 حالة MyAI",
        color=(
            discord.Color.green()
            if enabled
            else discord.Color.red()
        )
    )

    embed.add_field(
        name="الحالة",
        value=(
            "🟢 مفعّل"
            if enabled
            else "🔴 معطّل"
        ),
        inline=True
    )

    embed.add_field(
        name="نوع الرد",
        value=reply_type,
        inline=True
    )

    embed.add_field(
        name="الروم",
        value=(
            f"<#{channel_id}>"
            if channel_id
            else "غير محدد"
        ),
        inline=True
    )

    embed.add_field(
        name="الشخصية",
        value=str(
            config.get(
                "character_name",
                "غير محددة"
            )
        ),
        inline=True
    )

    embed.add_field(
        name="Provider",
        value=AI_PROVIDER.title(),
        inline=True
    )

    embed.add_field(
        name="Model",
        value=AI_MODEL,
        inline=True
    )

    embed.add_field(
        name="Mode",
        value=get_ai_mode(config),
        inline=True
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# AI MEMORY CLEAR
# =========================================================

@bot.tree.command(
    name="ai_memory_clear",
    description="مسح ذاكرة محادثة الذكاء الاصطناعي"
)
async def ai_memory_clear(
    interaction: discord.Interaction
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    if not can_manage_ai(
        interaction
    ):

        await interaction.response.send_message(
            "❌ ما عندك صلاحية.",
            ephemeral=True
        )

        return

    try:

        db.clear_history(
            interaction.guild.id,
            interaction.channel.id
        )

        await interaction.response.send_message(
            "🧹 تم مسح ذاكرة المحادثة."
        )

    except Exception:

        print(
            "❌ ai_memory_clear error:"
        )

        traceback.print_exc()

        await interaction.response.send_message(
            "❌ تعذر مسح الذاكرة.",
            ephemeral=True
        )


# =========================================================
# START
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "❌ DISCORD_TOKEN environment variable is missing."
    )


bot.run(TOKEN)
