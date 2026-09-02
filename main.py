import os
import time

import discord
from discord import app_commands
from discord.ext import commands

from database import Database
from ai_engine import AIEngine


TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set")


db = Database()
ai = AIEngine(db)


# ============================================================
# إعدادات المراقبة التلقائية
# ============================================================

AUTO_CHECK_MESSAGE_COUNT = 30
AUTO_COOLDOWN_SECONDS = 300

auto_message_counter = {}
auto_last_check = {}


# ============================================================
# Intents
# ============================================================

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True


# ============================================================
# Bot
# ============================================================

class MyAIBot(commands.Bot):

    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents
        )

    async def setup_hook(self):
        synced = await self.tree.sync()
        print(f"Synced {len(synced)} slash commands.")


bot = MyAIBot()


# ============================================================
# صلاحيات أعلى 4 رتب
# ============================================================

def get_top_four_roles(guild: discord.Guild):
    """
    يرجع أعلى 4 رتب فعلية في السيرفر.
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


def has_top_four_role(member: discord.Member) -> bool:
    """
    يسمح فقط لمن يملك واحدة من أعلى 4 رتب.
    """

    top_four = get_top_four_roles(member.guild)

    return any(
        role in top_four
        for role in member.roles
    )


def can_control_bot(interaction: discord.Interaction) -> bool:
    """
    التحقق من أن المستخدم يملك واحدة من أعلى 4 رتب.
    """

    if not interaction.guild:
        return False

    member = interaction.user

    if not isinstance(member, discord.Member):
        return False

    return has_top_four_role(member)


async def require_bot_control(
    interaction: discord.Interaction
) -> bool:
    """
    حماية أوامر البوت.
    """

    if can_control_bot(interaction):
        return True

    message = (
        "❌ **ليس لديك صلاحية التحكم بالبوت.**\n\n"
        "🔐 التحكم بالبوت متاح فقط لأصحاب **أعلى 4 رتب** "
        "في السيرفر."
    )

    if interaction.response.is_done():
        await interaction.followup.send(
            message,
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            message,
            ephemeral=True
        )

    return False


# ============================================================
# Helpers
# ============================================================

def get_config(guild_id: int):
    return db.get_ai_config(guild_id)


def get_character(
    guild_id: int,
    character_name: str
):
    return db.get_character(
        guild_id,
        character_name
    )


def split_message(
    text: str,
    limit: int = 1900
):
    """
    تقسيم ردود Discord الطويلة.
    """

    if not text:
        return []

    chunks = []

    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)

        if cut <= 0:
            cut = text.rfind(" ", 0, limit)

        if cut <= 0:
            cut = limit

        chunks.append(text[:cut].strip())
        text = text[cut:].strip()

    if text:
        chunks.append(text)

    return chunks


async def send_ai_response(
    message: discord.Message,
    response: str
):
    if not response:
        return

    for chunk in split_message(response):

        await message.channel.send(
            chunk,
            allowed_mentions=discord.AllowedMentions.none()
        )


async def send_interaction_response(
    interaction: discord.Interaction,
    content: str,
    ephemeral: bool = True
):
    if interaction.response.is_done():
        await interaction.followup.send(
            content,
            ephemeral=ephemeral
        )
    else:
        await interaction.response.send_message(
            content,
            ephemeral=ephemeral
        )


# ============================================================
# /ai
# ============================================================

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

    if not interaction.guild:
        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )
        return

    if not await require_bot_control(interaction):
        return

    guild_id = interaction.guild.id

    config = get_config(guild_id)

    character_name = config.get(
        "character_name",
        "MyAI"
    )

    character = get_character(
        guild_id,
        character_name
    )

    if not character:
        characters = db.get_characters(guild_id)

        if not characters:
            await interaction.response.send_message(
                "❌ لا توجد شخصية AI في السيرفر.",
                ephemeral=True
            )
            return

        character_name = characters[0]["name"]

        db.set_active_character(
            guild_id,
            character_name
        )

    await interaction.response.defer(
        ephemeral=False
    )

    try:

        response = await ai.generate(
            guild_id=guild_id,
            channel_id=interaction.channel.id,
            user_id=interaction.user.id,
            character_name=character_name,
            user_message=message,
            provider=config.get("provider"),
            model=config.get("model"),
            mode=config.get("mode")
        )

        if not response:
            response = "❌ ما قدرت أطلع رد."

        for chunk in split_message(response):

            await interaction.followup.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none()
            )

    except Exception as e:

        print(f"/ai error: {e}")

        await interaction.followup.send(
            "❌ حصل خطأ أثناء معالجة طلبك.",
            ephemeral=True
        )


# ============================================================
# /ai_setup
# ============================================================

@bot.tree.command(
    name="ai_setup",
    description="إعداد نظام الذكاء الاصطناعي"
)
async def ai_setup(
    interaction: discord.Interaction
):

    if not interaction.guild:
        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )
        return

    if not await require_bot_control(interaction):
        return

    guild_id = interaction.guild.id

    config = get_config(guild_id)

    character_name = config.get(
        "character_name",
        "MyAI"
    )

    mode = config.get(
        "mode",
        "normal"
    )

    reply_type = config.get(
        "reply_type",
        "mention"
    )

    channel_id = config.get(
        "channel_id"
    )

    channel_text = "غير محددة"

    if channel_id:
        channel = interaction.guild.get_channel(
            int(channel_id)
        )

        if channel:
            channel_text = channel.mention

    reply_names = {
        "mention": "1️⃣ منشن البوت + كتابة الرسالة",
        "channel": "2️⃣ مباشرة داخل القناة المحددة",
        "direct": "3️⃣ يرد إذا كان الكلام موجهًا له",
        "auto": "4️⃣ تلقائي ذكي + تنبيهات ونصائح"
    }

    mode_names = {
        "normal": "🤖 عادي",
        "friendly": "😎 اجتماعي",
        "active": "🔥 نشيط",
        "fun": "😂 كوميدي",
        "professional": "🧠 احترافي"
    }

    embed = discord.Embed(
        title="🤖 AI Setup",
        description=(
            "تحكم كامل بنظام الذكاء الاصطناعي."
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="الحالة",
        value=(
            "🟢 يعمل"
            if config.get("enabled")
            else "🔴 متوقف"
        ),
        inline=True
    )

    embed.add_field(
        name="الشخصية",
        value=character_name,
        inline=True
    )

    embed.add_field(
        name="الوضع",
        value=mode_names.get(
            mode,
            mode
        ),
        inline=True
    )

    embed.add_field(
        name="نوع الرد",
        value=reply_names.get(
            reply_type,
            reply_type
        ),
        inline=False
    )

    embed.add_field(
        name="القناة",
        value=channel_text,
        inline=False
    )

    embed.add_field(
        name="التحكم",
        value="🔐 أعلى 4 رتب فقط",
        inline=False
    )

    view = SetupView(
        guild_id=guild_id
    )

    await interaction.response.send_message(
        embed=embed,
        view=view,
        ephemeral=True
    )


# ============================================================
# /character_create
# ============================================================

@bot.tree.command(
    name="character_create",
    description="إنشاء شخصية AI"
)
@app_commands.describe(
    name="اسم الشخصية",
    personality="شخصية وتعليمات الشخصية"
)
async def character_create(
    interaction: discord.Interaction,
    name: str,
    personality: str
):

    if not interaction.guild:
        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )
        return

    if not await require_bot_control(interaction):
        return

    try:

        db.create_character(
            guild_id=interaction.guild.id,
            name=name,
            personality=personality,
            provider="google",
            model="gemini-3.6-flash",
            created_by=interaction.user.id
        )

        await interaction.response.send_message(
            f"✅ تم إنشاء الشخصية **{name}** بنجاح.",
            ephemeral=True
        )

    except Exception as e:

        await interaction.response.send_message(
            f"❌ تعذر إنشاء الشخصية: {e}",
            ephemeral=True
        )


# ============================================================
# /character_list
# ============================================================

@bot.tree.command(
    name="character_list",
    description="عرض شخصيات AI"
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

    if not await require_bot_control(interaction):
        return

    characters = db.get_characters(
        interaction.guild.id
    )

    if not characters:
        await interaction.response.send_message(
            "❌ لا توجد شخصيات.",
            ephemeral=True
        )
        return

    config = get_config(
        interaction.guild.id
    )

    active = config.get(
        "character_name"
    )

    lines = []

    for character in characters:

        prefix = (
            "🟢"
            if character["name"] == active
            else "⚪"
        )

        lines.append(
            f"{prefix} **{character['name']}**"
        )

    embed = discord.Embed(
        title="🤖 الشخصيات",
        description="\n".join(lines),
        color=discord.Color.blurple()
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ============================================================
# /character_use
# ============================================================

@bot.tree.command(
    name="character_use",
    description="تفعيل شخصية AI"
)
@app_commands.describe(
    name="اسم الشخصية"
)
async def character_use(
    interaction: discord.Interaction,
    name: str
):

    if not interaction.guild:
        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )
        return

    if not await require_bot_control(interaction):
        return

    try:

        success = db.set_active_character(
            interaction.guild.id,
            name
        )

        if not success:
            await interaction.response.send_message(
                "❌ الشخصية غير موجودة.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ تم تفعيل الشخصية **{name}**.",
            ephemeral=True
        )

    except Exception as e:

        await interaction.response.send_message(
            f"❌ حدث خطأ: {e}",
            ephemeral=True
        )


# ============================================================
# /ai_status
# ============================================================

@bot.tree.command(
    name="ai_status",
    description="عرض حالة نظام AI"
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

    if not await require_bot_control(interaction):
        return

    guild_id = interaction.guild.id

    config = get_config(guild_id)
    stats = db.get_stats(guild_id)

    reply_names = {
        "mention": "1️⃣ منشن + رسالة",
        "channel": "2️⃣ مباشرة في القناة",
        "direct": "3️⃣ كلام موجه للبوت",
        "auto": "4️⃣ تلقائي ذكي"
    }

    embed = discord.Embed(
        title="📊 حالة AI",
        color=discord.Color.green()
    )

    embed.add_field(
        name="الحالة",
        value=(
            "🟢 يعمل"
            if config.get("enabled")
            else "🔴 متوقف"
        ),
        inline=True
    )

    embed.add_field(
        name="الشخصية",
        value=config.get(
            "character_name",
            "MyAI"
        ),
        inline=True
    )

    embed.add_field(
        name="نوع الرد",
        value=reply_names.get(
            config.get("reply_type"),
            config.get("reply_type")
        ),
        inline=False
    )

    embed.add_field(
        name="القناة",
        value=str(
            config.get("channel_id")
            or "غير محددة"
        ),
        inline=False
    )

    embed.add_field(
        name="الرسائل",
        value=str(
            stats.get("message_count", 0)
        ),
        inline=True
    )

    embed.add_field(
        name="الشخصيات",
        value=str(
            stats.get("character_count", 0)
        ),
        inline=True
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ============================================================
# /ai_memory_clear
# ============================================================

@bot.tree.command(
    name="ai_memory_clear",
    description="مسح ذاكرة AI للقناة الحالية"
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

    if not await require_bot_control(interaction):
        return

    try:

        config = get_config(
            interaction.guild.id
        )

        character_name = config.get(
            "character_name"
        )

        db.clear_history(
            guild_id=interaction.guild.id,
            channel_id=interaction.channel.id,
            character_name=character_name
        )

        await interaction.response.send_message(
            "🧹 تم مسح ذاكرة AI للقناة الحالية.",
            ephemeral=True
        )

    except Exception as e:

        await interaction.response.send_message(
            f"❌ حدث خطأ: {e}",
            ephemeral=True
        )


# ============================================================
# Setup View
# ============================================================

class SetupView(discord.ui.View):

    def __init__(
        self,
        guild_id: int
    ):
        super().__init__(
            timeout=300
        )

        self.guild_id = guild_id

        # ----------------------------------------------------
        # Channel Select
        # ----------------------------------------------------

        self.channel_selector = discord.ui.ChannelSelect(
            channel_types=[
                discord.ChannelType.text
            ],
            placeholder="📢 اختر قناة AI",
            min_values=1,
            max_values=1,
            row=3
        )

        self.channel_selector.callback = (
            self.channel_selected
        )

        self.add_item(
            self.channel_selector
        )

        # ----------------------------------------------------
        # Reply Type Select
        # ----------------------------------------------------

        self.reply_type_select = discord.ui.Select(
            placeholder="💬 اختر نوع الرد",
            min_values=1,
            max_values=1,
            row=1,
            options=[
                discord.SelectOption(
                    label="1️⃣ منشن البوت + كتابة الرسالة",
                    value="mention",
                    description="يرد فقط عند منشن البوت"
                ),
                discord.SelectOption(
                    label="2️⃣ مباشرة داخل القناة المحددة",
                    value="channel",
                    description="يرد على الرسائل داخل قناة AI"
                ),
                discord.SelectOption(
                    label="3️⃣ يرد إذا كان الكلام موجهًا له",
                    value="direct",
                    description="يحاول معرفة الكلام الموجه للبوت"
                ),
                discord.SelectOption(
                    label="4️⃣ تلقائي ذكي + تنبيهات ونصائح",
                    value="auto",
                    description="يراقب القناة ويعطي تنبيهات مفيدة"
                )
            ]
        )

        self.reply_type_select.callback = (
            self.reply_type_selected
        )

        self.add_item(
            self.reply_type_select
        )

        # ----------------------------------------------------
        # Mode Select
        # ----------------------------------------------------

        self.mode_select = discord.ui.Select(
            placeholder="🎭 اختر وضع AI",
            min_values=1,
            max_values=1,
            row=2,
            options=[
                discord.SelectOption(
                    label="🤖 عادي",
                    value="normal"
                ),
                discord.SelectOption(
                    label="😎 اجتماعي",
                    value="friendly"
                ),
                discord.SelectOption(
                    label="🔥 نشيط",
                    value="active"
                ),
                discord.SelectOption(
                    label="😂 كوميدي",
                    value="fun"
                ),
                discord.SelectOption(
                    label="🧠 احترافي",
                    value="professional"
                )
            ]
        )

        self.mode_select.callback = (
            self.mode_selected
        )

        self.add_item(
            self.mode_select
        )

    # ========================================================
    # Permission helper
    # ========================================================

    async def check_permission(
        self,
        interaction: discord.Interaction
    ) -> bool:

        return await require_bot_control(
            interaction
        )

    # ========================================================
    # Enable
    # ========================================================

    @discord.ui.button(
        label="تشغيل AI",
        emoji="🟢",
        style=discord.ButtonStyle.success,
        row=0
    )
    async def enable_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not await self.check_permission(interaction):
            return

        await interaction.response.defer(
            ephemeral=True
        )

        db.set_ai_enabled(
            self.guild_id,
            True
        )

        await interaction.followup.send(
            "🟢 تم تشغيل AI.",
            ephemeral=True
        )

    # ========================================================
    # Disable
    # ========================================================

    @discord.ui.button(
        label="إيقاف AI",
        emoji="🔴",
        style=discord.ButtonStyle.danger,
        row=0
    )
    async def disable_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not await self.check_permission(interaction):
            return

        await interaction.response.defer(
            ephemeral=True
        )

        db.set_ai_enabled(
            self.guild_id,
            False
        )

        await interaction.followup.send(
            "🔴 تم إيقاف AI.",
            ephemeral=True
        )

    # ========================================================
    # Reply Type
    # ========================================================

    async def reply_type_selected(
        self,
        interaction: discord.Interaction
    ):

        if not await self.check_permission(interaction):
            return

        value = self.reply_type_select.values[0]

        db.set_reply_type(
            self.guild_id,
            value
        )

        names = {
            "mention":
                "1️⃣ منشن البوت + كتابة الرسالة",

            "channel":
                "2️⃣ مباشرة داخل القناة المحددة",

            "direct":
                "3️⃣ يرد إذا كان الكلام موجهًا له",

            "auto":
                "4️⃣ تلقائي ذكي + تنبيهات ونصائح"
        }

        await interaction.response.send_message(
            f"✅ تم اختيار:\n**{names[value]}**",
            ephemeral=True
        )

    # ========================================================
    # Mode
    # ========================================================

    async def mode_selected(
        self,
        interaction: discord.Interaction
    ):

        if not await self.check_permission(interaction):
            return

        value = self.mode_select.values[0]

        db.set_ai_mode(
            self.guild_id,
            value
        )

        names = {
            "normal": "🤖 عادي",
            "friendly": "😎 اجتماعي",
            "active": "🔥 نشيط",
            "fun": "😂 كوميدي",
            "professional": "🧠 احترافي"
        }

        await interaction.response.send_message(
            f"✅ تم اختيار الوضع **{names[value]}**.",
            ephemeral=True
        )

    # ========================================================
    # Channel
    # ========================================================

    async def channel_selected(
        self,
        interaction: discord.Interaction
    ):

        if not await self.check_permission(interaction):
            return

        channel = self.channel_selector.values[0]

        db.set_ai_channel(
            self.guild_id,
            channel.id
        )

        await interaction.response.send_message(
            f"📢 تم تحديد قناة AI: {channel.mention}",
            ephemeral=True
        )


# ============================================================
# Mention detector
# ============================================================

def clean_bot_mention(
    content: str
) -> str:

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
) -> bool:

    if not bot.user:
        return False

    content = message.content.lower().strip()

    if bot.user.mentioned_in(message):
        return True

    bot_names = [
        bot.user.name.lower(),
        "بوت",
        "يا بوت",
        "البوت",
        "ai",
        "ذكاء اصطناعي"
    ]

    for name in bot_names:
        if name and name in content:
            return True

    return False


# ============================================================
# Automatic AI
# ============================================================

async def handle_auto_ai(
    message: discord.Message,
    config: dict
):

    guild_id = message.guild.id

    configured_channel = config.get(
        "channel_id"
    )

    if configured_channel:

        if message.channel.id != int(
            configured_channel
        ):
            return

    auto_message_counter[guild_id] = (
        auto_message_counter.get(
            guild_id,
            0
        ) + 1
    )

    now = time.time()

    last_check = auto_last_check.get(
        guild_id,
        0
    )

    if (
        auto_message_counter[guild_id]
        < AUTO_CHECK_MESSAGE_COUNT
    ):
        return

    if (
        now - last_check
        < AUTO_COOLDOWN_SECONDS
    ):
        return

    auto_message_counter[guild_id] = 0
    auto_last_check[guild_id] = now

    character_name = config.get(
        "character_name",
        "MyAI"
    )

    try:

        async with message.channel.typing():

            response = await ai.generate_proactive(
                guild_id=guild_id,
                channel_id=message.channel.id,
                character_name=character_name,
                provider=config.get("provider"),
                model=config.get("model")
            )

        if not response:
            return

        for chunk in split_message(
            f"🤖 **تنبيه ذكي للسيرفر**\n\n{response}"
        ):

            await message.channel.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none()
            )

    except Exception as e:

        print(
            f"Auto AI error in guild "
            f"{guild_id}: {e}"
        )


# ============================================================
# on_message
# ============================================================

@bot.event
async def on_message(
    message: discord.Message
):

    if message.author.bot:
        return

    if not message.guild:
        return

    config = get_config(
        message.guild.id
    )

    if not config.get(
        "enabled",
        False
    ):
        await bot.process_commands(message)
        return

    character_name = config.get(
        "character_name",
        "MyAI"
    )

    character = get_character(
        message.guild.id,
        character_name
    )

    if not character:
        await bot.process_commands(message)
        return

    reply_type = config.get(
        "reply_type",
        "mention"
    )

    # ========================================================
    # 1️⃣ Mention
    # ========================================================

    if reply_type == "mention":

        if not bot.user.mentioned_in(message):
            await bot.process_commands(message)
            return

        content = clean_bot_mention(
            message.content
        )

        if not content:

            await message.channel.send(
                "👋 هلا! وش تبي تسألني؟"
            )

            await bot.process_commands(message)
            return

        try:

            async with message.channel.typing():

                response = await ai.generate(
                    guild_id=message.guild.id,
                    channel_id=message.channel.id,
                    user_id=message.author.id,
                    character_name=character_name,
                    user_message=content,
                    provider=config.get("provider"),
                    model=config.get("model"),
                    mode=config.get("mode")
                )

            await send_ai_response(
                message,
                response
            )

        except Exception as e:

            print(f"Mention AI error: {e}")

            await message.channel.send(
                "❌ حصل خطأ وأنا أحاول أرد عليك."
            )

        await bot.process_commands(message)
        return

    # ========================================================
    # 2️⃣ Channel
    # ========================================================

    if reply_type == "channel":

        configured_channel = config.get(
            "channel_id"
        )

        if not configured_channel:
            await bot.process_commands(message)
            return

        if message.channel.id != int(
            configured_channel
        ):
            await bot.process_commands(message)
            return

        content = message.content.strip()

        if not content:
            await bot.process_commands(message)
            return

        try:

            async with message.channel.typing():

                response = await ai.generate(
                    guild_id=message.guild.id,
                    channel_id=message.channel.id,
                    user_id=message.author.id,
                    character_name=character_name,
                    user_message=content,
                    provider=config.get("provider"),
                    model=config.get("model"),
                    mode=config.get("mode")
                )

            await send_ai_response(
                message,
                response
            )

        except Exception as e:

            print(f"Channel AI error: {e}")

            await message.channel.send(
                "❌ حصل خطأ وأنا أحاول أرد عليك."
            )

        await bot.process_commands(message)
        return

    # ========================================================
    # 3️⃣ Direct
    # ========================================================

    if reply_type == "direct":

        if not is_directed_to_bot(message):
            await bot.process_commands(message)
            return

        content = clean_bot_mention(
            message.content
        )

        if not content:
            content = "هلا! وش تبي؟"

        try:

            async with message.channel.typing():

                response = await ai.generate(
                    guild_id=message.guild.id,
                    channel_id=message.channel.id,
                    user_id=message.author.id,
                    character_name=character_name,
                    user_message=content,
                    provider=config.get("provider"),
                    model=config.get("model"),
                    mode=config.get("mode")
                )

            await send_ai_response(
                message,
                response
            )

        except Exception as e:

            print(f"Direct AI error: {e}")

            await message.channel.send(
                "❌ حصل خطأ وأنا أحاول أرد عليك."
            )

        await bot.process_commands(message)
        return

    # ========================================================
    # 4️⃣ Automatic AI
    # ========================================================

    if reply_type == "auto":

        await handle_auto_ai(
            message,
            config
        )

        await bot.process_commands(message)
        return

    # ========================================================
    # Commands
    # ========================================================

    await bot.process_commands(message)


# ============================================================
# Tree Error Handler
# ============================================================

@bot.tree.error
async def on_tree_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):

    print(f"Slash command error: {error}")

    try:

        await send_interaction_response(
            interaction,
            "❌ حصل خطأ أثناء تنفيذ الأمر.",
            ephemeral=True
        )

    except Exception as e:

        print(
            f"Could not send command error: {e}"
        )


# ============================================================
# Start
# ============================================================

try:

    bot.run(TOKEN)

finally:

    db.close()
