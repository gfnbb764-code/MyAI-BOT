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

# حماية Bot-to-Bot
BOT_CHAT_MAX_REPLIES = 100
BOT_CHAT_COOLDOWN_SECONDS = 2


# =========================================================
# AI PROVIDER CONFIG
# =========================================================

AI_PROVIDER = os.getenv(
    "PRIMARY_AI_PROVIDER",
    "google",
).lower().strip()

AI_MODEL = os.getenv(
    "GOOGLE_MODEL",
    "gemini-2.5-flash-lite",
).strip()

if AI_PROVIDER not in {
    "openai",
    "google",
    "anthropic",
}:

    AI_PROVIDER = "google"

    AI_MODEL = os.getenv(
        "GOOGLE_MODEL",
        "gemini-2.5-flash-lite",
    ).strip()

print(
    "🤖 AI CONFIG | "
    f"provider={AI_PROVIDER} | "
    f"model={AI_MODEL}"
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
            "normal",
        )
    ).lower().strip()

    if mode not in AI_MODES:
        mode = "normal"

    return mode


# =========================================================
# INTENTS
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
            intents=intents,
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
# CHANNEL ID
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

    current_channel_id = normalize_channel_id(
        message.channel.id
    )

    saved_channel_id = normalize_channel_id(
        configured_channel_id
    )

    matches = (
        current_channel_id is not None
        and saved_channel_id is not None
        and current_channel_id == saved_channel_id
    )

    print(
        "📍 CHANNEL CHECK | "
        f"current={current_channel_id} | "
        f"configured={saved_channel_id} | "
        f"match={matches}"
    )

    return matches


# =========================================================
# MESSAGE HELPERS
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


async def send_ai_response(
    message,
    response
):

    if not response:
        return

    chunks = split_message(
        response
    )

    if not chunks:
        return

    try:

        await message.reply(
            chunks[0],
            mention_author=False
        )

        print(
            "↩️ AI replied to original message."
        )

    except Exception:

        print(
            "❌ Failed to reply to original message:"
        )

        traceback.print_exc()

        return

    for chunk in chunks[1:]:

        try:

            await message.channel.send(
                chunk
            )

        except Exception:

            print(
                "❌ Failed to send additional AI chunk:"
            )

            traceback.print_exc()

            return


# =========================================================
# PERMISSIONS
# =========================================================

def has_management_permission(
    member: discord.Member
):

    if member.guild.owner_id == member.id:
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
# DIRECT BOT DETECTION
# =========================================================

def is_directed_to_bot(
    message: discord.Message
):

    if bot.user is None:
        return False

    if bot.user in message.mentions:
        return True

    referenced_message = getattr(
        message,
        "reference",
        None
    )

    if referenced_message is not None:

        resolved = getattr(
            referenced_message,
            "resolved",
            None
        )

        if resolved is not None:

            resolved_author = getattr(
                resolved,
                "author",
                None
            )

            if (
                resolved_author is not None
                and resolved_author.id == bot.user.id
            ):

                return True

    content = normalize_text(
        message.content
    )

    if not content:
        return False

    names = []

    if bot.user.name:

        names.append(
            normalize_text(
                bot.user.name
            )
        )

    if bot.user.display_name:

        names.append(
            normalize_text(
                bot.user.display_name
            )
        )

    names.extend([
        "myai",
        "my ai"
    ])

    names = list({
        name
        for name in names
        if name
    })

    for name in names:

        escaped = re.escape(
            name
        )

        patterns = [

            rf"^{escaped}$",

            rf"^{escaped}\s*[:،,]",

            rf"^{escaped}\s+",

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
            "⚠️ AI returned an empty response."
        )

        return

    print(
        "✅ AI RESPONSE RECEIVED | "
        f"length={len(response)}"
    )

    await send_ai_response(
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

    current_count = (
        auto_message_counters.get(
            channel_id,
            0
        )
        + 1
    )

    auto_message_counters[
        channel_id
    ] = current_count

    print(
        "🤖 AUTO COUNTER | "
        f"channel={channel_id} | "
        f"count={current_count}/"
        f"{AUTO_CHECK_MESSAGE_COUNT}"
    )

    if current_count < AUTO_CHECK_MESSAGE_COUNT:
        return

    auto_message_counters[
        channel_id
    ] = 0

    now = time.time()

    last_check = auto_last_check.get(
        channel_id,
        0
    )

    elapsed = now - last_check

    if elapsed < AUTO_COOLDOWN_SECONDS:

        remaining = int(
            AUTO_COOLDOWN_SECONDS
            - elapsed
        )

        print(
            "⏳ AUTO COOLDOWN | "
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

        print(
            "⚠️ Proactive AI returned nothing."
        )

        return

    response = str(
        response
    ).strip()

    if response.upper() == "NO_ALERT":

        print(
            "🤖 AI decided: NO_ALERT"
        )

        return

    print(
        "🚨 Proactive AI alert received | "
        f"length={len(response)}"
    )

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

    last_reply = bot_chat_last_reply.get(
        channel_id,
        0
    )

    elapsed = now - last_reply

    if elapsed < BOT_CHAT_COOLDOWN_SECONDS:

        remaining = int(
            BOT_CHAT_COOLDOWN_SECONDS
            - elapsed
        )

        print(
            "⏳ BOT CHAT COOLDOWN | "
            f"remaining={remaining}s"
        )

        return False

    count = bot_chat_reply_counts.get(
        channel_id,
        0
    )

    if count >= BOT_CHAT_MAX_REPLIES:

        print(
            "🛑 BOT CHAT LIMIT REACHED | "
            f"count={count}/"
            f"{BOT_CHAT_MAX_REPLIES}"
        )

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
        )
        + 1
    )

    bot_chat_last_reply[
        channel_id
    ] = time.time()

    print(
        "🤖 BOT CHAT REPLY COUNT | "
        f"channel={channel_id} | "
        f"count={bot_chat_reply_counts[channel_id]}/"
        f"{BOT_CHAT_MAX_REPLIES}"
    )


def reset_bot_chat_session(
    channel_id
):

    bot_chat_reply_counts[
        channel_id
    ] = 0

    bot_chat_last_reply.pop(
        channel_id,
        None
    )


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
        "📡 Message Content Intent:",
        bot.intents.message_content
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
        "🤖 Active AI Provider | "
        f"{AI_PROVIDER}"
    )

    print(
        "🧠 Active AI Model | "
        f"{AI_MODEL}"
    )


# =========================================================
# ON MESSAGE
# =========================================================

@bot.event
async def on_message(
    message: discord.Message
):

    try:

        author_name = str(
            message.author
        )

        author_id = getattr(
            message.author,
            "id",
            "unknown"
        )

        is_bot = getattr(
            message.author,
            "bot",
            False
        )

        guild_name = (
            message.guild.name
            if message.guild
            else "DM"
        )

        guild_id = (
            message.guild.id
            if message.guild
            else None
        )

        channel_name = getattr(
            message.channel,
            "name",
            str(message.channel)
        )

        channel_id = getattr(
            message.channel,
            "id",
            "unknown"
        )

        content = (
            message.content
            or ""
        )

        print(
            "\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📩 NEW MESSAGE\n"
            f"👤 Sender     : {author_name}\n"
            f"🆔 Sender ID  : {author_id}\n"
            f"🤖 Is Bot     : {is_bot}\n"
            f"🏠 Server     : {guild_name}\n"
            f"🆔 Server ID  : {guild_id}\n"
            f"💬 Channel    : #{channel_name}\n"
            f"🆔 Channel ID : {channel_id}\n"
            f"📝 Message    : {content!r}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

    except Exception as e:

        print(
            f"⚠️ Message logger error: {e}"
        )

    if message.guild is None:

        print(
            "⏭️ Ignored DM message."
        )

        return

    guild_id = message.guild.id

    config = get_config(
        guild_id
    )

    if config is None:

        print(
            f"❌ No AI config "
            f"for guild {guild_id}"
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
    ).lower().strip()

    if (
        bot.user is not None
        and message.author.id == bot.user.id
    ):

        print(
            "⏭️ Ignored MyAI's own message."
        )

        return

    try:

        await bot.process_commands(
            message
        )

    except Exception:

        print(
            "❌ process_commands error:"
        )

        traceback.print_exc()

    print(
        f"🏠 Guild detected: {guild_id}"
    )

    print(
        "⚙️ Config loaded | "
        f"enabled={config.get('enabled')} | "
        f"reply_type={reply_type} | "
        f"channel_id={config.get('channel_id')} | "
        f"character={config.get('character_name')} | "
        f"provider={AI_PROVIDER} | "
        f"model={AI_MODEL} | "
        f"mode={config.get('mode', 'normal')}"
    )

    if not bool(
        config.get(
            "enabled",
            0
        )
    ):

        print(
            "⏭️ AI is disabled."
        )

        return

    print(
        "🟢 AI is enabled."
    )

    character = get_active_character(
        guild_id,
        config
    )

    if character is None:

        print(
            f"❌ No AI character "
            f"for guild {guild_id}"
        )

        return

    print(
        "🧠 Character loaded: "
        f"{character.get('name')}"
    )

    print(
        f"🎯 Reply type: {reply_type}"
    )

    is_bot_message = getattr(
        message.author,
        "bot",
        False
    )

    # =====================================================
    # 1. MENTION
    # =====================================================

    if reply_type == "mention":

        if bot.user is None:

            print(
                "❌ bot.user is None."
            )

            return

        if bot.user not in message.mentions:

            print(
                "⏭️ Message does not "
                "mention MyAI."
            )

            return

        print(
            "🏷️ MyAI mention detected."
        )

        user_message = clean_bot_mention(
            message.content
        )

        if not user_message:

            user_message = "السلام عليكم"

        try:

            await generate_chat_reply(
                message,
                config,
                character,
                user_message
            )

            print(
                "✅ Mention AI response sent."
            )

        except Exception:

            print(
                f"❌ Mention AI error "
                f"in guild {guild_id}:"
            )

            traceback.print_exc()

        return

    # =====================================================
    # 2. CHANNEL
    # =====================================================

    if reply_type == "channel":

        configured_channel = config.get(
            "channel_id"
        )

        print(
            "🔎 CHANNEL MODE | "
            f"message_channel={message.channel.id} | "
            f"saved_channel={configured_channel!r} | "
            f"is_bot={is_bot_message}"
        )

        if configured_channel is None:

            print(
                "❌ Channel mode selected "
                "but no channel configured."
            )

            return

        configured_channel = normalize_channel_id(
            configured_channel
        )

        if configured_channel is None:

            print(
                "❌ Invalid saved channel_id."
            )

            return

        if not channel_matches(
            message,
            configured_channel
        ):

            print(
                "⏭️ Message is outside "
                "the configured channel."
            )

            return

        content = message.content.strip()

        if not content:

            print(
                "⏭️ Empty message."
            )

            return

        try:

            await generate_chat_reply(
                message,
                config,
                character,
                content
            )

            print(
                "✅ Channel AI response sent."
            )

        except Exception:

            print(
                f"❌ Channel AI error "
                f"in guild {guild_id}:"
            )

            traceback.print_exc()

        return

    # =====================================================
    # 3. DIRECT
    # =====================================================

    if reply_type == "direct":

        directed = is_directed_to_bot(
            message
        )

        print(
            f"🎯 Direct detection: "
            f"{directed} | "
            f"is_bot={is_bot_message}"
        )

        if not directed:

            print(
                "⏭️ Message is not directed "
                "to MyAI."
            )

            return

        user_message = clean_bot_mention(
            message.content
        )

        if not user_message:

            user_message = (
                message.content.strip()
            )

        if not user_message:

            print(
                "⏭️ Empty direct message."
            )

            return

        try:

            await generate_chat_reply(
                message,
                config,
                character,
                user_message
            )

            print(
                "✅ Direct AI response sent."
            )

        except Exception:

            print(
                f"❌ Direct AI error "
                f"in guild {guild_id}:"
            )

            traceback.print_exc()

        return

    # =====================================================
    # 4. AUTO
    # =====================================================

    if reply_type == "auto":

        if is_bot_message:

            print(
                "⏭️ AUTO MODE | "
                "other bot ignored."
            )

            return

        print(
            "🤖 Auto mode message detected."
        )

        try:

            await handle_auto_ai(
                message,
                config,
                character
            )

            print(
                "✅ Auto handler completed."
            )

        except Exception:

            print(
                f"❌ Auto handler error "
                f"in guild {guild_id}:"
            )

            traceback.print_exc()

        return

    # =====================================================
    # 5. BOT CHAT
    # =====================================================

    if reply_type == "bot_chat":

        if is_bot_message:

            print(
                "🤖 BOT CHAT | "
                "OTHER BOT MESSAGE ALLOWED"
            )

            if not bot_chat_allowed(
                message.channel.id
            ):

                return

            user_message = (
                message.content
                or ""
            ).strip()

            if not user_message:

                print(
                    "⏭️ Other bot message is empty."
                )

                return

            try:

                await generate_chat_reply(
                    message,
                    config,
                    character,
                    user_message
                )

                register_bot_chat_reply(
                    message.channel.id
                )

                print(
                    "✅ MyAI replied to another bot."
                )

            except Exception:

                print(
                    "❌ Bot-to-Bot AI error:"
                )

                traceback.print_exc()

            return

        print(
            "👤 BOT CHAT | "
            "HUMAN MESSAGE"
        )

        directed = is_directed_to_bot(
            message
        )

        print(
            f"🎯 Bot Chat human detection: "
            f"{directed}"
        )

        if not directed:

            print(
                "⏭️ Human message is not "
                "directed to MyAI."
            )

            return

        user_message = clean_bot_mention(
            message.content
        )

        if not user_message:

            user_message = (
                message.content.strip()
            )

        if not user_message:

            print(
                "⏭️ Empty Bot Chat human message."
            )

            return

        try:

            await generate_chat_reply(
                message,
                config,
                character,
                user_message
            )

            print(
                "✅ Bot Chat human response sent."
            )

        except Exception:

            print(
                f"❌ Bot Chat human AI error "
                f"in guild {guild_id}:"
            )

            traceback.print_exc()

        return

    print(
        "⚠️ Unknown reply_type: "
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
            "❌ لا توجد شخصية AI لهذا السيرفر."
        )

        return

    try:

        character_name = character.get(
            "name"
        )

        provider = AI_PROVIDER
        model = AI_MODEL
        mode = get_ai_mode(config)

        print(
            "🧠 /ai REQUEST | "
            f"character={character_name} | "
            f"provider={provider} | "
            f"model={model} | "
            f"mode={mode}"
        )

        response = await ai.generate(
            guild_id=guild_id,
            channel_id=interaction.channel.id,
            user_id=interaction.user.id,
            character_name=character_name,
            user_message=message,
            provider=provider,
            model=model,
            mode=mode
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

    except Exception as error:

        print(
            "❌ /ai error:"
        )

        traceback.print_exc()

        error_text = str(
            error
        ).lower()

        if (
            "quota" in error_text
            or "credit_balance_exhausted" in error_text
            or "insufficient_quota" in error_text
        ):

            await interaction.followup.send(
                "⚠️ رصيد مزود الذكاء الاصطناعي غير متاح حاليًا."
            )

            return

        if (
            "gemini_api_key" in error_text
            or "google_api_key" in error_text
            or "not configured" in error_text
        ):

            await interaction.followup.send(
                "⚠️ مفتاح Gemini API غير مضبوط في إعدادات الاستضافة."
            )

            return

        await interaction.followup.send(
            "❌ حدث خطأ أثناء تشغيل الذكاء الاصطناعي."
        )


# =========================================================
# SETUP CHANNEL SELECT
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
                "❌ هذا الخيار داخل السيرفر فقط.",
                ephemeral=True
            )

            return

        if not can_manage_ai(
            interaction
        ):

            await interaction.response.send_message(
                "❌ ما عندك صلاحية إدارة الذكاء الاصطناعي.",
                ephemeral=True
            )

            return

        channel = self.values[0]

        channel_id = normalize_channel_id(
            channel.id
        )

        save_config(
            interaction.guild.id,
            channel_id=channel_id,
            enabled=True
        )

        print(
            "💾 CHANNEL SAVED | "
            f"guild={interaction.guild.id} | "
            f"channel={channel_id}"
        )

        await interaction.response.send_message(
            f"✅ تم اختيار الروم: {channel.mention}\n"
            f"🟢 تم تفعيل نظام الذكاء الاصطناعي.",
            ephemeral=True
        )


# =========================================================
# SETUP REPLY TYPE SELECT
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
                description="يرد عندما يتم منشن البوت"
            ),

            discord.SelectOption(
                label="2 - Channel",
                value="channel",
                description="يرد على كل رسالة في روم محدد"
            ),

            discord.SelectOption(
                label="3 - Direct",
                value="direct",
                description="يرد عندما يتم توجيه الكلام إليه"
            ),

            discord.SelectOption(
                label="4 - Auto",
                value="auto",
                description="يراقب المحادثة ويرسل تنبيهات ذكية"
            ),

            discord.SelectOption(
                label="5 - التحدث مع البوتات الأخرى",
                value="bot_chat",
                description="يتحدث MyAI مع البوتات الأخرى 🤖"
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
                "❌ ما عندك صلاحية إدارة الذكاء الاصطناعي.",
                ephemeral=True
            )

            return

        value = self.values[0]

        save_config(
            self.guild_id,
            reply_type=value,
            enabled=True
        )

        print(
            "💾 REPLY TYPE SAVED | "
            f"guild={self.guild_id} | "
            f"type={value}"
        )

        names = {
            "mention": "Mention",
            "channel": "Channel",
            "direct": "Direct",
            "auto": "Auto",
            "bot_chat": "التحدث مع البوتات الأخرى 🤖"
        }

        display_name = names.get(
            value,
            value
        )

        await interaction.response.send_message(
            f"✅ تم تفعيل نظام الرد: `{display_name}`",
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
                "❌ ما عندك صلاحية إدارة الذكاء الاصطناعي.",
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
                "❌ ما عندك صلاحية إدارة الذكاء الاصطناعي.",
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
            "❌ هذا الأمر داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    if not can_manage_ai(
        interaction
    ):

        await interaction.response.send_message(
            "❌ ما عندك صلاحية استخدام إعدادات الذكاء الاصطناعي.",
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
        "bot_chat": "5 - التحدث مع البوتات الأخرى 🤖"
    }

    embed = discord.Embed(
        title="🤖 إعداد MyAI",
        description=(
            "اختر الروم ونوع الرد.\n\n"
            "اختيار نوع الرد يقوم بتفعيله مباشرة."
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="الحالة",
        value=(
            "🟢 مفعّل"
            if bool(
                config.get(
                    "enabled",
                    0
                )
            )
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
        config.get(
            "channel_id"
        )
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
# /CHARACTER CREATE
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
            "❌ ما عندك صلاحية إنشاء الشخصيات.",
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
# /CHARACTER LIST
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
# /CHARACTER USE
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
            "❌ ما عندك صلاحية تغيير الشخصية.",
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
        "🧠 تم اختيار الشخصية "
        f"**{character.get('name')}**."
    )


# =========================================================
# /AI STATUS
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
            "❌ هذا الأمر داخل السيرفر فقط.",
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

    enabled = bool(
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

    reply_names = {
        "mention": "1 - Mention",
        "channel": "2 - Channel",
        "direct": "3 - Direct",
        "auto": "4 - Auto",
        "bot_chat": "5 - التحدث مع البوتات الأخرى 🤖"
    }

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
        value=reply_names.get(
            reply_type,
            reply_type
        ),
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
# /AI MEMORY CLEAR
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
            "❌ هذا الأمر داخل السيرفر فقط.",
            ephemeral=True
        )

        return

    if not can_manage_ai(
        interaction
    ):

        await interaction.response.send_message(
            "❌ ما عندك صلاحية مسح الذاكرة.",
            ephemeral=True
        )

        return

    try:

        db.clear_history(
            interaction.guild.id,
            interaction.channel.id
        )

        await interaction.response.send_message(
            "🧹 تم مسح ذاكرة محادثة هذا الروم."
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
# START BOT
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "❌ DISCORD_TOKEN environment variable is missing."
    )


bot.run(TOKEN)
