import os
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

auto_message_counters = {}
auto_last_check = {}


# =========================================================
# DATABASE / AI
# =========================================================

db = Database()
ai = AIEngine(db)


# =========================================================
# INTENTS
# =========================================================

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True


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

def get_config(guild_id: int):

    try:
        config = db.get_ai_config(guild_id)

        if config is None:
            return None

        return dict(config)

    except Exception:
        traceback.print_exc()
        return None


def save_config(guild_id: int, **kwargs):

    return db.save_ai_config(
        guild_id,
        **kwargs
    )


def get_character(
    guild_id: int,
    name: str = None
):

    if name:

        character = db.get_character(
            guild_id,
            name
        )

        if character:
            return dict(character)

    return None


def get_active_character(
    guild_id: int,
    config
):

    character_name = config.get(
        "character_name"
    )

    if character_name:

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
            return dict(characters[0])

    except Exception:

        traceback.print_exc()

    return None


# =========================================================
# MESSAGE SPLITTER
# =========================================================

def split_message(
    text: str,
    limit: int = 1900
):

    if not text:
        return []

    text = str(text)

    if len(text) <= limit:
        return [text]

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
        chunks.append(text)

    return chunks


async def send_ai_response(
    channel,
    response,
    reply_to=None
):

    if not response:
        return

    chunks = split_message(
        response
    )

    for index, chunk in enumerate(chunks):

        if (
            reply_to is not None
            and index == 0
        ):

            await reply_to.reply(
                chunk,
                mention_author=False
            )

        else:

            await channel.send(
                chunk
            )


# =========================================================
# PERMISSIONS
# =========================================================

def get_top_four_roles(
    guild: discord.Guild
):

    roles = [
        role
        for role in guild.roles
        if role != guild.default_role
        and not role.managed
    ]

    roles.sort(
        key=lambda role: role.position,
        reverse=True
    )

    return roles[:4]


def has_top_four_role(
    member: discord.Member
):

    if not isinstance(
        member,
        discord.Member
    ):
        return False

    top_four = get_top_four_roles(
        member.guild
    )

    top_ids = {
        role.id
        for role in top_four
    }

    return any(
        role.id in top_ids
        for role in member.roles
    )


def can_control_bot(
    member: discord.Member
):

    if not isinstance(
        member,
        discord.Member
    ):
        return False

    if (
        member.id
        == member.guild.owner_id
    ):
        return True

    return has_top_four_role(
        member
    )


async def require_bot_control(
    interaction: discord.Interaction
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )

        return False

    if not can_control_bot(
        interaction.user
    ):

        await interaction.response.send_message(
            "❌ ما عندك صلاحية للتحكم بالبوت.\n"
            "لازم تكون من أصحاب إحدى أعلى 4 رتب في السيرفر.",
            ephemeral=True
        )

        return False

    return True


# =========================================================
# BOT MENTION
# =========================================================

def clean_bot_mention(
    content: str
):

    if not content:
        return ""

    if bot.user is None:
        return content.strip()

    content = content.replace(
        f"<@{bot.user.id}>",
        ""
    )

    content = content.replace(
        f"<@!{bot.user.id}>",
        ""
    )

    return content.strip()


def is_directed_to_bot(
    message: discord.Message
):

    if bot.user is None:
        return False

    if bot.user in message.mentions:
        return True

    content = message.content.strip()

    if not content:
        return False

    lowered = content.lower()
    bot_name = bot.user.name.lower()

    patterns = [
        f"يا {bot_name}",
        f"يـا {bot_name}",
        f"{bot_name} ",
        f"{bot_name}:",
        f"{bot_name},",
        f"hey {bot_name}",
        f"hello {bot_name}",
    ]

    return any(
        pattern in lowered
        for pattern in patterns
    )


# =========================================================
# NORMAL AI REPLY
# =========================================================

async def generate_chat_reply(
    message,
    config,
    character,
    user_message
):

    if not user_message:
        return

    character_name = character.get(
        "name"
    )

    if not character_name:

        raise ValueError(
            "الشخصية لا تحتوي على اسم."
        )

    async with message.channel.typing():

        response = await ai.generate(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            user_id=message.author.id,
            character_name=character_name,
            user_message=user_message,
            mode=config.get(
                "mode",
                "normal"
            )
        )

    if not response:
        return

    await send_ai_response(
        message.channel,
        response,
        reply_to=message
    )


# =========================================================
# AUTO AI
# =========================================================

async def handle_auto_ai(
    message,
    config,
    character
):

    guild_id = message.guild.id
    channel_id = message.channel.id

    character_name = character.get(
        "name"
    )

    if not character_name:
        return

    key = (
        guild_id,
        channel_id
    )

    auto_message_counters[key] = (
        auto_message_counters.get(
            key,
            0
        ) + 1
    )

    count = auto_message_counters[key]

    if count < AUTO_CHECK_MESSAGE_COUNT:
        return

    auto_message_counters[key] = 0

    now = time.time()

    last_check = auto_last_check.get(
        key,
        0
    )

    if (
        now - last_check
        < AUTO_COOLDOWN_SECONDS
    ):
        return

    auto_last_check[key] = now

    try:

        async with message.channel.typing():

            response = await ai.generate_proactive(
                guild_id=guild_id,
                channel_id=channel_id,
                character_name=character_name
            )

        if not response:
            return

        await send_ai_response(
            message.channel,
            "🤖 **تنبيه ذكي للسيرفر**\n"
            + str(response)
        )

    except Exception:

        print(
            f"❌ Auto AI error "
            f"in guild {guild_id}"
        )

        traceback.print_exc()


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


# =========================================================
# /ai
# =========================================================

@bot.tree.command(
    name="ai",
    description="التحدث مع الذكاء الاصطناعي"
)
@app_commands.describe(
    message="رسالتك"
)
async def ai_command(
    interaction: discord.Interaction,
    message: str
):

    if not await require_bot_control(
        interaction
    ):
        return

    guild_id = interaction.guild.id

    config = get_config(
        guild_id
    )

    if config is None:

        await interaction.response.send_message(
            "❌ تعذر تحميل إعدادات البوت.",
            ephemeral=True
        )

        return

    character = get_active_character(
        guild_id,
        config
    )

    if character is None:

        await interaction.response.send_message(
            "❌ لا توجد شخصية AI.\n"
            "أنشئ شخصية أولاً باستخدام "
            "`/character_create`.",
            ephemeral=True
        )

        return

    character_name = character.get(
        "name"
    )

    if not character_name:

        await interaction.response.send_message(
            "❌ الشخصية الحالية غير صالحة.",
            ephemeral=True
        )

        return

    await interaction.response.defer()

    try:

        response = await ai.generate(
            guild_id=guild_id,
            channel_id=interaction.channel.id,
            user_id=interaction.user.id,
            character_name=character_name,
            user_message=message,
            mode=config.get(
                "mode",
                "normal"
            )
        )

        if not response:

            await interaction.followup.send(
                "⚠️ لم يرجع الذكاء الاصطناعي أي رد."
            )

            return

        for chunk in split_message(
            response
        ):

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
# SETUP CHANNEL SELECT
# =========================================================

class SetupChannelSelect(
    discord.ui.ChannelSelect
):

    def __init__(self):

        super().__init__(
            placeholder="اختر قناة الرد...",
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

        if interaction.guild is None:
            return

        if not can_control_bot(
            interaction.user
        ):

            await interaction.response.send_message(
                "❌ هذه الإعدادات لأعلى 4 رتب فقط.",
                ephemeral=True
            )

            return

        channel = self.values[0]

        save_config(
            interaction.guild.id,
            channel_id=channel.id
        )

        await interaction.response.send_message(
            f"✅ تم تحديد قناة الرد: "
            f"{channel.mention}",
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
            timeout=600
        )

        self.guild_id = guild_id

        self.add_item(
            SetupChannelSelect()
        )

    async def permission_check(
        self,
        interaction
    ):

        if interaction.guild is None:
            return False

        if not can_control_bot(
            interaction.user
        ):

            await interaction.response.send_message(
                "❌ هذه الإعدادات لأعلى 4 رتب فقط.",
                ephemeral=True
            )

            return False

        return True

    # -----------------------------------------------------
    # ENABLE
    # -----------------------------------------------------

    @discord.ui.button(
        label="تشغيل",
        style=discord.ButtonStyle.success,
        emoji="🟢"
    )
    async def enable(
        self,
        interaction,
        button
    ):

        if not await self.permission_check(
            interaction
        ):
            return

        save_config(
            self.guild_id,
            enabled=True
        )

        await interaction.response.send_message(
            "🟢 تم تشغيل MyAI.",
            ephemeral=True
        )

    # -----------------------------------------------------
    # DISABLE
    # -----------------------------------------------------

    @discord.ui.button(
        label="إيقاف",
        style=discord.ButtonStyle.danger,
        emoji="🔴"
    )
    async def disable(
        self,
        interaction,
        button
    ):

        if not await self.permission_check(
            interaction
        ):
            return

        save_config(
            self.guild_id,
            enabled=False
        )

        await interaction.response.send_message(
            "🔴 تم إيقاف MyAI.",
            ephemeral=True
        )

    # -----------------------------------------------------
    # REPLY TYPE
    # -----------------------------------------------------

    @discord.ui.select(
        placeholder="اختر نوع الرد...",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(
                label="منشن البوت",
                description="يرد فقط عندما تعمل منشن للبوت",
                value="mention",
                emoji="🏷️"
            ),
            discord.SelectOption(
                label="القناة المحددة",
                description="يرد على كل رسالة في قناة محددة",
                value="channel",
                emoji="💬"
            ),
            discord.SelectOption(
                label="الرد المباشر",
                description="يرد عندما تخاطبه مباشرة",
                value="direct",
                emoji="🎯"
            ),
            discord.SelectOption(
                label="الوضع التلقائي",
                description="يراقب المحادثة ويقدم تنبيهات",
                value="auto",
                emoji="🤖"
            )
        ]
    )
    async def reply_type(
        self,
        interaction,
        select
    ):

        if not await self.permission_check(
            interaction
        ):
            return

        value = select.values[0]

        save_config(
            self.guild_id,
            reply_type=value
        )

        names = {
            "mention": "🏷️ منشن البوت",
            "channel": "💬 القناة المحددة",
            "direct": "🎯 الرد المباشر",
            "auto": "🤖 الوضع التلقائي"
        }

        await interaction.response.send_message(
            f"✅ تم اختيار: **{names[value]}**",
            ephemeral=True
        )


# =========================================================
# /ai_setup
# =========================================================

@bot.tree.command(
    name="ai_setup",
    description="إعداد MyAI"
)
async def ai_setup(
    interaction: discord.Interaction
):

    if not await require_bot_control(
        interaction
    ):
        return

    guild_id = interaction.guild.id

    config = get_config(
        guild_id
    )

    if config is None:

        await interaction.response.send_message(
            "❌ تعذر تحميل إعدادات البوت.",
            ephemeral=True
        )

        return

    reply_type = config.get(
        "reply_type",
        "mention"
    )

    reply_names = {
        "mention": "🏷️ منشن البوت",
        "channel": "💬 القناة المحددة",
        "direct": "🎯 الرد المباشر",
        "auto": "🤖 الوضع التلقائي"
    }

    enabled = bool(
        config.get(
            "enabled",
            0
        )
    )

    channel_id = config.get(
        "channel_id"
    )

    if channel_id:
        channel_text = f"<#{channel_id}>"
    else:
        channel_text = "غير محددة"

    character_name = config.get(
        "character_name"
    )

    if not character_name:
        character_name = "تلقائي"

    embed = discord.Embed(
        title="🤖 MyAI — لوحة الإعدادات",
        description=(
            "تحكم في طريقة عمل الذكاء الاصطناعي "
            "داخل السيرفر."
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="الحالة",
        value=(
            "🟢 يعمل"
            if enabled
            else "🔴 متوقف"
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
        name="النمط",
        value=str(
            config.get(
                "mode",
                "normal"
            )
        ),
        inline=True
    )

    embed.add_field(
        name="الشخصية",
        value=str(
            character_name
        ),
        inline=True
    )

    embed.add_field(
        name="القناة",
        value=channel_text,
        inline=True
    )

    embed.add_field(
        name="الصلاحيات",
        value="أعلى 4 رتب",
        inline=True
    )

    embed.set_footer(
        text="MyAI"
    )

    await interaction.response.send_message(
        embed=embed,
        view=SetupView(guild_id),
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
    prompt="شخصية وسلوك الذكاء الاصطناعي"
)
async def character_create(
    interaction,
    name: str,
    prompt: str
):

    if not await require_bot_control(
        interaction
    ):
        return

    try:

        db.create_character(
            interaction.guild.id,
            name,
            prompt,
            created_by=interaction.user.id
        )

        await interaction.response.send_message(
            f"✅ تم إنشاء الشخصية **{name}**.",
            ephemeral=True
        )

    except Exception as error:

        print(
            "❌ character_create error:"
        )

        traceback.print_exc()

        await interaction.response.send_message(
            f"❌ تعذر إنشاء الشخصية: {error}",
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
    interaction
):

    if not await require_bot_control(
        interaction
    ):
        return

    try:

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

        config = get_config(
            interaction.guild.id
        )

        active = (
            config.get(
                "character_name"
            )
            if config
            else None
        )

        for character in characters:

            character = dict(
                character
            )

            name = character.get(
                "name",
                "بدون اسم"
            )

            if name == active:

                lines.append(
                    f"🟢 **{name}** — نشطة"
                )

            else:

                lines.append(
                    f"⚪ **{name}**"
                )

        await interaction.response.send_message(
            "🤖 **الشخصيات:**\n\n"
            + "\n".join(lines),
            ephemeral=True
        )

    except Exception:

        print(
            "❌ character_list error:"
        )

        traceback.print_exc()

        await interaction.response.send_message(
            "❌ تعذر عرض الشخصيات.",
            ephemeral=True
        )


# =========================================================
# /character_use
# =========================================================

@bot.tree.command(
    name="character_use",
    description="اختيار الشخصية النشطة"
)
@app_commands.describe(
    name="اسم الشخصية"
)
async def character_use(
    interaction,
    name: str
):

    if not await require_bot_control(
        interaction
    ):
        return

    guild_id = interaction.guild.id

    character = get_character(
        guild_id,
        name
    )

    if character is None:

        await interaction.response.send_message(
            f"❌ الشخصية **{name}** غير موجودة.",
            ephemeral=True
        )

        return

    try:

        save_config(
            guild_id,
            character_name=name
        )

        await interaction.response.send_message(
            f"✅ أصبحت **{name}** الشخصية النشطة.",
            ephemeral=True
        )

    except Exception:

        print(
            "❌ character_use error:"
        )

        traceback.print_exc()

        await interaction.response.send_message(
            "❌ تعذر اختيار الشخصية.",
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
    interaction
):

    if not await require_bot_control(
        interaction
    ):
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
            "🟢 يعمل"
            if enabled
            else "🔴 متوقف"
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
        name="النمط",
        value=str(
            config.get(
                "mode",
                "normal"
            )
        ),
        inline=True
    )

    embed.add_field(
        name="الشخصية",
        value=str(
            config.get(
                "character_name"
            )
            or "تلقائي"
        ),
        inline=True
    )

    channel_id = config.get(
        "channel_id"
    )

    embed.add_field(
        name="القناة",
        value=(
            f"<#{channel_id}>"
            if channel_id
            else "غير محددة"
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
    description="مسح ذاكرة AI"
)
async def ai_memory_clear(
    interaction
):

    if not await require_bot_control(
        interaction
    ):
        return

    try:

        db.clear_history(
            interaction.guild.id
        )

        await interaction.response.send_message(
            "🧹 تم مسح ذاكرة المحادثة.",
            ephemeral=True
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
# ON MESSAGE
# =========================================================

@bot.event
async def on_message(
    message: discord.Message
):

    # تجاهل البوتات
    if message.author.bot:
        return

    # أوامر prefix
    await bot.process_commands(
        message
    )

    # الرسائل الخاصة
    if message.guild is None:
        return

    guild_id = message.guild.id

    # =====================================================
    # LOAD CONFIG
    # =====================================================

    config = get_config(
        guild_id
    )

    if config is None:
        return

    # =====================================================
    # ENABLED
    # =====================================================

    if not bool(
        config.get(
            "enabled",
            0
        )
    ):
        return

    # =====================================================
    # CHARACTER
    # =====================================================

    character = get_active_character(
        guild_id,
        config
    )

    if character is None:
        return

    # =====================================================
    # REPLY TYPE
    # =====================================================

    reply_type = str(
        config.get(
            "reply_type",
            "mention"
        )
    ).lower().strip()

    # =====================================================
    # 1. MENTION
    # =====================================================

    if reply_type == "mention":

        if bot.user is None:
            return

        if bot.user not in message.mentions:
            return

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
            return

        try:

            configured_channel = int(
                configured_channel
            )

        except Exception:

            return

        if (
            message.channel.id
            != configured_channel
        ):
            return

        content = message.content.strip()

        if not content:
            return

        try:

            await generate_chat_reply(
                message,
                config,
                character,
                content
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

        if not is_directed_to_bot(
            message
        ):
            return

        user_message = clean_bot_mention(
            message.content
        )

        if not user_message:

            user_message = (
                message.content.strip()
            )

        if not user_message:
            return

        try:

            await generate_chat_reply(
                message,
                config,
                character,
                user_message
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

        try:

            await handle_auto_ai(
                message,
                config,
                character
            )

        except Exception:

            print(
                f"❌ Auto handler error "
                f"in guild {guild_id}:"
            )

            traceback.print_exc()

        return


# =========================================================
# SLASH COMMAND ERROR
# =========================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):

    print(
        "❌ Slash command error:"
    )

    traceback.print_exception(
        type(error),
        error,
        error.__traceback__
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


try:

    bot.run(TOKEN)

finally:

    try:
        db.close()

    except Exception:
        pass
