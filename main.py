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
# AUTO MODE MEMORY
# =========================================================

auto_message_counters = {}
auto_last_check = {}


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
            print(f"Synced {len(synced)} slash commands.")

        except Exception:
            print("❌ Failed to sync slash commands:")
            traceback.print_exc()


bot = MyAIBot()


# =========================================================
# DATABASE HELPERS
# =========================================================

def get_config(guild_id):

    try:
        return db.get_ai_config(guild_id)

    except Exception:
        print("❌ Failed to load AI config:")
        traceback.print_exc()
        return None


def save_config(guild_id, **kwargs):

    try:
        return db.save_ai_config(
            guild_id,
            **kwargs
        )

    except Exception:
        print("❌ Failed to save AI config:")
        traceback.print_exc()
        return None


def get_character(guild_id, character_name):

    try:
        if character_name:
            return db.get_character(
                guild_id,
                character_name
            )

    except Exception:
        print("❌ Failed to get character:")
        traceback.print_exc()

    return None


def get_active_character(guild_id, config):

    character_name = config.get("character_name")

    character = get_character(
        guild_id,
        character_name
    )

    if character:
        return character

    try:
        characters = db.get_characters(guild_id)

        if characters:
            return characters[0]

    except Exception:
        print("❌ Failed to get guild characters:")
        traceback.print_exc()

    return None


# =========================================================
# MESSAGE HELPERS
# =========================================================

def split_message(text, limit=1900):

    if not text:
        return []

    text = str(text)

    chunks = []

    while len(text) > limit:

        split_at = text.rfind("\n", 0, limit)

        if split_at <= 0:
            split_at = text.rfind(" ", 0, limit)

        if split_at <= 0:
            split_at = limit

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()

    if text:
        chunks.append(text)

    return chunks


async def send_ai_response(message, response):

    if not response:
        return

    chunks = split_message(response)

    for chunk in chunks:

        try:
            await message.channel.send(chunk)

        except Exception:
            print("❌ Failed to send AI response:")
            traceback.print_exc()
            return


# =========================================================
# PERMISSIONS
# =========================================================

def has_management_permission(member: discord.Member):

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


def can_manage_ai(interaction: discord.Interaction):

    if not interaction.guild:
        return False

    member = interaction.user

    if not isinstance(member, discord.Member):
        return False

    return has_management_permission(member)


# =========================================================
# MENTION CLEANER
# =========================================================

def clean_bot_mention(content):

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

def normalize_text(text):

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

def is_directed_to_bot(message: discord.Message):

    if bot.user is None:
        return False

    # Real Discord mention
    if bot.user in message.mentions:
        return True

    content = normalize_text(
        message.content
    )

    if not content:
        return False

    names = []

    if bot.user.name:
        names.append(
            normalize_text(bot.user.name)
        )

    if bot.user.display_name:
        names.append(
            normalize_text(bot.user.display_name)
        )

    names = [
        name
        for name in set(names)
        if name
    ]

    for name in names:

        escaped = re.escape(name)

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

    provider = config.get("provider")
    model = config.get("model")
    mode = config.get("mode")

    print(
        "🧠 AI REQUEST | "
        f"provider={provider} | "
        f"model={model} | "
        f"mode={mode} | "
        f"character={character.get('name')}"
    )

    response = await ai.generate(
        guild_id=message.guild.id,
        channel_id=message.channel.id,
        user_id=message.author.id,
        character_name=character.get("name"),
        user_message=user_message,
        provider=provider,
        model=model,
        mode=mode
    )

    if not response:
        print("⚠️ AI returned an empty response.")
        return

    print(
        f"✅ AI RESPONSE RECEIVED | length={len(response)}"
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

    auto_message_counters[channel_id] = current_count

    print(
        f"🤖 AUTO COUNTER | "
        f"channel={channel_id} | "
        f"count={current_count}/{AUTO_CHECK_MESSAGE_COUNT}"
    )

    if current_count < AUTO_CHECK_MESSAGE_COUNT:
        return

    auto_message_counters[channel_id] = 0

    now = time.time()

    last_check = auto_last_check.get(
        channel_id,
        0
    )

    elapsed = now - last_check

    if elapsed < AUTO_COOLDOWN_SECONDS:

        remaining = int(
            AUTO_COOLDOWN_SECONDS - elapsed
        )

        print(
            f"⏳ AUTO COOLDOWN | "
            f"remaining={remaining}s"
        )

        return

    auto_last_check[channel_id] = now

    print("🤖 Running proactive AI check...")

    response = await ai.generate_proactive(
        guild_id=message.guild.id,
        channel_id=message.channel.id,
        character_name=character.get("name"),
        provider=config.get("provider"),
        model=config.get("model")
    )

    if not response:
        print("⚠️ Proactive AI returned nothing.")
        return

    response = str(response).strip()

    if response.upper() == "NO_ALERT":
        print("🤖 AI decided: NO_ALERT")
        return

    print(
        f"🚨 Proactive AI alert received | "
        f"length={len(response)}"
    )

    await send_ai_response(
        message,
        response
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
        f"🌐 Connected to {len(bot.guilds)} server(s)."
    )

    print("🧠 AI message system is ready.")

    print(
        "📡 Message Content Intent:",
        bot.intents.message_content
    )


# =========================================================
# ON MESSAGE
# =========================================================

@bot.event
async def on_message(message: discord.Message):

    # =====================================================
    # MESSAGE EVENT DEBUG
    # =====================================================

    print(
        f"📩 MESSAGE EVENT | "
        f"author={message.author} | "
        f"bot={message.author.bot} | "
        f"guild={message.guild} | "
        f"channel={message.channel} | "
        f"content={message.content!r}"
    )

    # =====================================================
    # IGNORE BOTS
    # =====================================================

    if message.author.bot:

        print(
            "⏭️ Ignored bot message."
        )

        return

    # =====================================================
    # PROCESS COMMANDS
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
    # IGNORE DMS
    # =====================================================

    if message.guild is None:

        print(
            "⏭️ Ignored DM message."
        )

        return

    guild_id = message.guild.id

    print(
        f"🏠 Guild detected: {guild_id}"
    )

    # =====================================================
    # LOAD CONFIG
    # =====================================================

    config = get_config(
        guild_id
    )

    if config is None:

        print(
            f"❌ No AI config for guild {guild_id}"
        )

        return

    print(
        "⚙️ Config loaded | "
        f"enabled={config.get('enabled')} | "
        f"reply_type={config.get('reply_type')} | "
        f"channel_id={config.get('channel_id')} | "
        f"character={config.get('character_name')} | "
        f"provider={config.get('provider')} | "
        f"model={config.get('model')}"
    )

    # =====================================================
    # ENABLED
    # =====================================================

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

    # =====================================================
    # CHARACTER
    # =====================================================

    character = get_active_character(
        guild_id,
        config
    )

    if character is None:

        print(
            f"❌ No AI character for guild {guild_id}"
        )

        return

    print(
        f"🧠 Character loaded: "
        f"{character.get('name')}"
    )

    # =====================================================
    # REPLY TYPE
    # =====================================================

    reply_type = str(
        config.get(
            "reply_type",
            "mention"
        )
    ).lower().strip()

    print(
        f"🎯 Reply type: {reply_type}"
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
                "⏭️ Message does not mention MyAI."
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

        print(
            "🚀 Sending mention message to AI: "
            f"{user_message!r}"
        )

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

        if not configured_channel:

            print(
                "❌ Channel mode selected "
                "but no channel configured."
            )

            return

        try:

            configured_channel = int(
                configured_channel
            )

        except Exception:

            print(
                "❌ Invalid channel_id."
            )

            return

        print(
            f"💬 Configured channel: "
            f"{configured_channel}"
        )

        if (
            message.channel.id
            != configured_channel
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

        print(
            "🚀 Sending channel message to AI: "
            f"{content!r}"
        )

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
            f"{directed}"
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

        print(
            "🚀 Sending direct message to AI: "
            f"{user_message!r}"
        )

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
    # UNKNOWN TYPE
    # =====================================================

    print(
        f"⚠️ Unknown reply_type: "
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

        response = await ai.generate(
            guild_id=guild_id,
            channel_id=interaction.channel.id,
            user_id=interaction.user.id,
            character_name=character.get("name"),
            user_message=message,
            provider=config.get("provider"),
            model=config.get("model"),
            mode=config.get("mode")
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
# /AI SETUP
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

        channel = self.values[0]

        save_config(
            interaction.guild.id,
            channel_id=channel.id
        )

        await interaction.response.send_message(
            f"✅ تم اختيار الروم: {channel.mention}",
            ephemeral=True
        )


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
                label="Mention",
                value="mention",
                description="يرد عندما يتم منشن البوت"
            ),

            discord.SelectOption(
                label="Channel",
                value="channel",
                description="يرد على كل رسالة في روم محدد"
            ),

            discord.SelectOption(
                label="Direct",
                value="direct",
                description="يرد عندما يتم توجيه الكلام إليه"
            ),

            discord.SelectOption(
                label="Auto",
                value="auto",
                description="يراقب المحادثة ويرسل تنبيهات ذكية"
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

        value = self.values[0]

        save_config(
            self.guild_id,
            reply_type=value,
            enabled=True
        )

        await interaction.response.send_message(
            f"✅ تم تفعيل نظام الرد: `{value}`",
            ephemeral=True
        )


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
            if bool(config.get("enabled", 0))
            else "🔴 معطّل"
        ),
        inline=True
    )

    embed.add_field(
        name="نوع الرد",
        value=str(
            config.get(
                "reply_type",
                "mention"
            )
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
        character_name=character.get("name")
    )

    await interaction.response.send_message(
        f"🧠 تم اختيار الشخصية **{character.get('name')}**."
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

    enabled = bool(
        config.get(
            "enabled",
            0
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
        value=str(
            config.get(
                "reply_type",
                "mention"
            )
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
        value=str(
            config.get(
                "provider",
                "default"
            )
        ),
        inline=True
    )

    embed.add_field(
        name="Model",
        value=str(
            config.get(
                "model",
                "default"
            )
        ),
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
            "❌ داخل السيرفر فقط.",
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
