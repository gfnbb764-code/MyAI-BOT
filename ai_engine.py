import os
import time
import traceback

import discord
from discord import app_commands
from discord.ext import commands

from database import Database
from ai_engine import AIEngine


# =========================================================
# إعدادات عامة
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

AUTO_CHECK_MESSAGE_COUNT = 30
AUTO_COOLDOWN_SECONDS = 300

# عدادات الوضع التلقائي لكل سيرفر
auto_message_counters = {}
auto_last_check = {}


# =========================================================
# قاعدة البيانات + محرك الذكاء الاصطناعي
# =========================================================

db = Database()
ai = AIEngine(db)


# =========================================================
# Discord Intents
# =========================================================

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True


# =========================================================
# Bot
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
# أدوات مساعدة
# =========================================================

def row_to_dict(row):
    """
    تحويل sqlite3.Row أو dict إلى dict عادي.
    """
    if row is None:
        return None

    if isinstance(row, dict):
        return row

    try:
        return dict(row)
    except Exception:
        return row


def get_config(guild_id: int):
    """
    جلب إعدادات السيرفر وتحويلها إلى dict.
    """
    config = db.get_config(guild_id)

    if config is None:
        return None

    return row_to_dict(config)


def get_character(guild_id: int, character_name=None):
    """
    جلب الشخصية وتحويلها إلى dict.
    """

    try:
        if character_name:
            character = db.get_character(
                guild_id,
                character_name
            )
        else:
            character = None
    except Exception:
        character = None

    if character is None:
        try:
            characters = db.list_characters(guild_id)

            if characters:
                character = characters[0]
        except Exception:
            character = None

    return row_to_dict(character)


def split_message(text: str, limit: int = 1900):
    """
    تقسيم رسالة طويلة حتى لا تتجاوز حد Discord.
    """

    if not text:
        return []

    text = str(text)

    if len(text) <= limit:
        return [text]

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


async def send_ai_response(
    destination,
    response: str,
    *,
    reply_to_message=None
):
    """
    إرسال رد الذكاء الاصطناعي على أجزاء.
    """

    if not response:
        return

    chunks = split_message(response)

    for index, chunk in enumerate(chunks):

        if reply_to_message is not None and index == 0:
            await reply_to_message.reply(
                chunk,
                mention_author=False
            )
        else:
            await destination.send(chunk)


# =========================================================
# صلاحيات أعلى 4 رتب
# =========================================================

def get_top_four_roles(guild: discord.Guild):
    """
    إرجاع أعلى 4 رتب في السيرفر حسب ترتيب Discord.
    @everyone لا تدخل ضمن الحساب.
    """

    roles = [
        role
        for role in guild.roles
        if role != guild.default_role
    ]

    roles.sort(
        key=lambda role: role.position,
        reverse=True
    )

    return roles[:4]


def has_top_four_role(member: discord.Member):
    """
    التحقق من أن العضو يملك واحدة من أعلى 4 رتب.
    """

    if not isinstance(member, discord.Member):
        return False

    top_four = get_top_four_roles(member.guild)

    top_four_ids = {
        role.id
        for role in top_four
    }

    return any(
        role.id in top_four_ids
        for role in member.roles
    )


def can_control_bot(member: discord.Member):
    """
    صلاحية التحكم بالبوت.
    أعلى 4 رتب فقط.
    """

    if not isinstance(member, discord.Member):
        return False

    # مالك السيرفر مسموح له دائماً
    if member.id == member.guild.owner_id:
        return True

    return has_top_four_role(member)


async def require_bot_control(interaction: discord.Interaction):
    """
    التحقق من صلاحية التحكم.
    """

    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )
        return False

    member = interaction.user

    if not can_control_bot(member):
        await interaction.response.send_message(
            "❌ ما عندك صلاحية للتحكم بالبوت.\n"
            "يجب أن تكون من أصحاب إحدى أعلى 4 رتب في السيرفر.",
            ephemeral=True
        )
        return False

    return True


# =========================================================
# تنظيف المنشن
# =========================================================

def clean_bot_mention(content: str):
    """
    إزالة منشن البوت من النص.
    """

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


# =========================================================
# اكتشاف الكلام الموجه للبوت
# =========================================================

def is_directed_to_bot(message: discord.Message):
    """
    اكتشاف إذا كان المستخدم يخاطب البوت مباشرة.
    """

    if bot.user is None:
        return False

    content = message.content.strip()

    # منشن مباشر
    if bot.user in message.mentions:
        return True

    lowered = content.lower()

    bot_name = bot.user.name.lower()

    patterns = [
        f"يا {bot_name}",
        f"يـا {bot_name}",
        f"{bot_name} ",
        f"{bot_name}:",
        f"{bot_name},",
    ]

    for pattern in patterns:
        if pattern in lowered:
            return True

    return False


# =========================================================
# الحصول على الشخصية النشطة
# =========================================================

def get_active_character(guild_id: int, config):
    """
    جلب الشخصية النشطة من الإعدادات.
    """

    character_name = None

    if config:
        character_name = config.get("active_character")

    character = get_character(
        guild_id,
        character_name
    )

    return character


# =========================================================
# الرد بالذكاء الاصطناعي
# =========================================================

async def generate_chat_reply(
    message: discord.Message,
    config,
    character,
    user_message: str
):
    """
    إنشاء رد AI عادي.
    """

    if not user_message:
        return

    guild_id = message.guild.id

    async with message.channel.typing():

        response = await ai.generate(
            guild_id=guild_id,
            user_id=message.author.id,
            character=character,
            user_message=user_message,
            mode=config.get("mode", "normal"),
            reply_type=config.get("reply_type", "mention")
        )

    if not response:
        return

    await send_ai_response(
        message.channel,
        response,
        reply_to_message=message
    )


# =========================================================
# الوضع التلقائي
# =========================================================

async def handle_auto_ai(
    message: discord.Message,
    config,
    character
):
    """
    الوضع التلقائي:
    - يحسب الرسائل
    - كل 30 رسالة تقريباً يفحص السيرفر
    - لا يفحص أكثر من مرة كل 5 دقائق
    """

    guild_id = message.guild.id
    channel_id = message.channel.id

    counter_key = (guild_id, channel_id)

    auto_message_counters[counter_key] = (
        auto_message_counters.get(counter_key, 0) + 1
    )

    current_count = auto_message_counters[counter_key]

    # لم يصل إلى عدد الرسائل المطلوب
    if current_count < AUTO_CHECK_MESSAGE_COUNT:
        return

    # تصفير العداد
    auto_message_counters[counter_key] = 0

    now = time.time()

    last_check = auto_last_check.get(
        counter_key,
        0
    )

    # Cooldown
    if now - last_check < AUTO_COOLDOWN_SECONDS:
        return

    auto_last_check[counter_key] = now

    try:

        async with message.channel.typing():

            response = await ai.generate_proactive(
                guild_id=guild_id,
                character=character,
                channel_id=channel_id
            )

        if not response:
            return

        await send_ai_response(
            message.channel,
            "🤖 **تنبيه ذكي للسيرفر**\n" + str(response)
        )

    except Exception:

        print(
            f"❌ Auto AI error in guild {guild_id}:"
        )

        traceback.print_exc()


# =========================================================
# on_ready
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


# =========================================================
# /ai
# =========================================================

@bot.tree.command(
    name="ai",
    description="التحدث مع الذكاء الاصطناعي"
)
@app_commands.describe(
    message="رسالتك للذكاء الاصطناعي"
)
async def ai_command(
    interaction: discord.Interaction,
    message: str
):

    if not await require_bot_control(interaction):
        return

    if interaction.guild is None:
        return

    guild_id = interaction.guild.id

    config = get_config(guild_id)

    if config is None:
        await interaction.response.send_message(
            "❌ لم يتم إعداد البوت لهذا السيرفر.",
            ephemeral=True
        )
        return

    character = get_active_character(
        guild_id,
        config
    )

    if character is None:
        await interaction.response.send_message(
            "❌ لا توجد شخصية AI متاحة.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    try:

        response = await ai.generate(
            guild_id=guild_id,
            user_id=interaction.user.id,
            character=character,
            user_message=message,
            mode=config.get("mode", "normal"),
            reply_type="command"
        )

        if not response:
            await interaction.followup.send(
                "⚠️ لم يرجع الذكاء الاصطناعي أي رد."
            )
            return

        chunks = split_message(response)

        for chunk in chunks:
            await interaction.followup.send(chunk)

    except Exception as error:

        print("❌ /ai error:")
        traceback.print_exc()

        await interaction.followup.send(
            "❌ حدث خطأ أثناء تشغيل الذكاء الاصطناعي."
        )


# =========================================================
# /ai_setup
# =========================================================

class SetupView(discord.ui.View):

    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id

    async def check_permission(
        self,
        interaction: discord.Interaction
    ):

        if interaction.guild is None:
            return False

        if not can_control_bot(interaction.user):
            await interaction.response.send_message(
                "❌ هذه الإعدادات متاحة فقط لأصحاب أعلى 4 رتب.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="تشغيل",
        style=discord.ButtonStyle.success
    )
    async def enable_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not await self.check_permission(interaction):
            return

        db.update_config(
            self.guild_id,
            enabled=True
        )

        await interaction.response.send_message(
            "✅ تم تشغيل الذكاء الاصطناعي.",
            ephemeral=True
        )

    @discord.ui.button(
        label="إيقاف",
        style=discord.ButtonStyle.danger
    )
    async def disable_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not await self.check_permission(interaction):
            return

        db.update_config(
            self.guild_id,
            enabled=False
        )

        await interaction.response.send_message(
            "⛔ تم إيقاف الذكاء الاصطناعي.",
            ephemeral=True
        )

    @discord.ui.select(
        placeholder="اختر نوع الرد",
        options=[
            discord.SelectOption(
                label="منشن البوت",
                description="يرد عندما تعمل منشن للبوت",
                value="mention"
            ),
            discord.SelectOption(
                label="القناة المحددة",
                description="يرد على الرسائل داخل قناة معينة",
                value="channel"
            ),
            discord.SelectOption(
                label="الرد المباشر",
                description="يتعرف عندما تخاطب البوت مباشرة",
                value="direct"
            ),
            discord.SelectOption(
                label="الوضع التلقائي",
                description="يراقب المحادثة ويقدم تنبيهات ذكية",
                value="auto"
            )
        ]
    )
    async def reply_type_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select
    ):

        if not await self.check_permission(interaction):
            return

        reply_type = select.values[0]

        db.update_config(
            self.guild_id,
            reply_type=reply_type
        )

        names = {
            "mention": "منشن البوت",
            "channel": "القناة المحددة",
            "direct": "الرد المباشر",
            "auto": "الوضع التلقائي"
        }

        await interaction.response.send_message(
            f"✅ تم اختيار نوع الرد: **{names.get(reply_type, reply_type)}**",
            ephemeral=True
        )


@bot.tree.command(
    name="ai_setup",
    description="إعداد الذكاء الاصطناعي"
)
async def ai_setup(
    interaction: discord.Interaction
):

    if not await require_bot_control(interaction):
        return

    guild_id = interaction.guild.id

    config = get_config(guild_id)

    if config is None:
        db.create_config(guild_id)
        config = get_config(guild_id)

    if config is None:
        await interaction.response.send_message(
            "❌ تعذر إنشاء إعدادات السيرفر.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="🤖 إعدادات MyAI",
        description="تحكم في طريقة عمل الذكاء الاصطناعي.",
        color=discord.Color.blurple()
    )

    enabled = config.get("enabled", False)

    embed.add_field(
        name="الحالة",
        value="🟢 يعمل" if enabled else "🔴 متوقف",
        inline=True
    )

    embed.add_field(
        name="الشخصية",
        value=str(
            config.get(
                "active_character",
                "MyAI"
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
        name="نوع الرد",
        value=str(
            config.get(
                "reply_type",
                "mention"
            )
        ),
        inline=True
    )

    channel_id = config.get("channel_id")

    if channel_id:
        channel_text = f"<#{channel_id}>"
    else:
        channel_text = "غير محددة"

    embed.add_field(
        name="القناة",
        value=channel_text,
        inline=True
    )

    embed.set_footer(
        text="التحكم متاح لأعلى 4 رتب في السيرفر."
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
    prompt="وصف الشخصية وسلوكها"
)
async def character_create(
    interaction: discord.Interaction,
    name: str,
    prompt: str
):

    if not await require_bot_control(interaction):
        return

    guild_id = interaction.guild.id

    try:

        db.create_character(
            guild_id,
            name,
            prompt
        )

        await interaction.response.send_message(
            f"✅ تم إنشاء الشخصية **{name}**.",
            ephemeral=True
        )

    except Exception:

        print("❌ character_create error:")
        traceback.print_exc()

        await interaction.response.send_message(
            "❌ تعذر إنشاء الشخصية.",
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

    if not await require_bot_control(interaction):
        return

    guild_id = interaction.guild.id

    try:

        characters = db.list_characters(guild_id)

        if not characters:
            await interaction.response.send_message(
                "📭 لا توجد شخصيات.",
                ephemeral=True
            )
            return

        lines = []

        for character in characters:

            character = row_to_dict(character)

            name = character.get(
                "name",
                "بدون اسم"
            )

            lines.append(
                f"• **{name}**"
            )

        await interaction.response.send_message(
            "🤖 **الشخصيات:**\n\n"
            + "\n".join(lines),
            ephemeral=True
        )

    except Exception:

        print("❌ character_list error:")
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
    interaction: discord.Interaction,
    name: str
):

    if not await require_bot_control(interaction):
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

    db.update_config(
        guild_id,
        active_character=name
    )

    await interaction.response.send_message(
        f"✅ أصبحت الشخصية **{name}** هي الشخصية النشطة.",
        ephemeral=True
    )


# =========================================================
# /ai_status
# =========================================================

@bot.tree.command(
    name="ai_status",
    description="عرض حالة الذكاء الاصطناعي"
)
async def ai_status(
    interaction: discord.Interaction
):

    if not await require_bot_control(interaction):
        return

    guild_id = interaction.guild.id

    config = get_config(guild_id)

    if config is None:
        await interaction.response.send_message(
            "❌ لا توجد إعدادات.",
            ephemeral=True
        )
        return

    enabled = config.get(
        "enabled",
        False
    )

    reply_type = config.get(
        "reply_type",
        "mention"
    )

    mode = config.get(
        "mode",
        "normal"
    )

    character = config.get(
        "active_character",
        "MyAI"
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
        value="🟢 يعمل" if enabled else "🔴 متوقف",
        inline=True
    )

    embed.add_field(
        name="الشخصية",
        value=str(character),
        inline=True
    )

    embed.add_field(
        name="النمط",
        value=str(mode),
        inline=True
    )

    embed.add_field(
        name="نوع الرد",
        value=str(reply_type),
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
    description="مسح ذاكرة المحادثة"
)
async def ai_memory_clear(
    interaction: discord.Interaction
):

    if not await require_bot_control(interaction):
        return

    guild_id = interaction.guild.id

    try:

        db.clear_history(guild_id)

        await interaction.response.send_message(
            "🧹 تم مسح ذاكرة الذكاء الاصطناعي.",
            ephemeral=True
        )

    except Exception:

        print("❌ ai_memory_clear error:")
        traceback.print_exc()

        await interaction.response.send_message(
            "❌ تعذر مسح الذاكرة.",
            ephemeral=True
        )


# =========================================================
# on_message
# =========================================================

@bot.event
async def on_message(message: discord.Message):

    # تجاهل البوتات
    if message.author.bot:
        return

    # تجاهل الرسائل الخاصة
    if message.guild is None:
        await bot.process_commands(message)
        return

    # مهم جداً:
    # نخلي أوامر prefix تشتغل أيضاً
    await bot.process_commands(message)

    guild_id = message.guild.id

    # -----------------------------------------------------
    # جلب الإعدادات
    # -----------------------------------------------------

    try:
        config = get_config(guild_id)
    except Exception:
        print("❌ Failed to load guild config:")
        traceback.print_exc()
        return

    if config is None:
        return

    # -----------------------------------------------------
    # إذا البوت متوقف
    # -----------------------------------------------------

    if not config.get("enabled", False):
        return

    # -----------------------------------------------------
    # نوع الرد
    # -----------------------------------------------------

    reply_type = str(
        config.get(
            "reply_type",
            "mention"
        )
    ).lower().strip()

    # دعم أسماء قديمة
    if reply_type == "command":
        reply_type = "mention"

    # -----------------------------------------------------
    # الشخصية
    # -----------------------------------------------------

    character = get_active_character(
        guild_id,
        config
    )

    if character is None:
        return

    # =====================================================
    # 1 — Mention
    # =====================================================

    if reply_type == "mention":

        if bot.user is None:
            return

        if bot.user not in message.mentions:
            return

        user_message = clean_bot_mention(
            message.content
        )

        # لو فقط منشن بدون كلام
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
    # 2 — Channel
    # =====================================================

    if reply_type == "channel":

        configured_channel_id = config.get(
            "channel_id"
        )

        if not configured_channel_id:
            return

        try:
            configured_channel_id = int(
                configured_channel_id
            )
        except Exception:
            return

        if message.channel.id != configured_channel_id:
            return

        if not message.content.strip():
            return

        try:

            await generate_chat_reply(
                message,
                config,
                character,
                message.content.strip()
            )

        except Exception:

            print(
                f"❌ Channel AI error "
                f"in guild {guild_id}:"
            )

            traceback.print_exc()

        return

    # =====================================================
    # 3 — Direct
    # =====================================================

    if reply_type == "direct":

        if not is_directed_to_bot(message):
            return

        user_message = clean_bot_mention(
            message.content
        )

        if not user_message:
            user_message = message.content.strip()

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
    # 4 — Auto
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
# معالجة أخطاء Slash Commands
# =========================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):

    print("❌ Slash command error:")
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
# تشغيل البوت
# =========================================================

if not TOKEN:
    raise RuntimeError(
        "❌ DISCORD_TOKEN غير موجود في Environment Variables."
    )


try:

    bot.run(TOKEN)

finally:

    try:
        db.close()
    except Exception:
        pass
