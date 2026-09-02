import os
import asyncio
import discord

from discord import app_commands
from discord.ext import commands

from database import Database
from ai_engine import AIEngine


# ==========================================================
# CONFIG
# ==========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN غير موجود في Environment Variables."
    )


# ==========================================================
# DATABASE + AI
# ==========================================================

db = Database()
ai = AIEngine(db)


# ==========================================================
# DISCORD INTENTS
# ==========================================================

intents = discord.Intents.default()

intents.guilds = True
intents.messages = True
intents.message_content = True


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
                f"✅ تم مزامنة {len(synced)} أمر Slash."
            )

        except Exception as e:

            print(
                f"❌ فشل مزامنة الأوامر: {e}"
            )


bot = MyAIBot()


# ==========================================================
# READY
# ==========================================================

@bot.event
async def on_ready():

    print("=" * 60)

    print(
        "🤖 MyAI اشتغل بنجاح!"
    )

    print(
        f"👤 الحساب: {bot.user}"
    )

    print(
        f"🆔 ID: {bot.user.id}"
    )

    print(
        f"🌐 السيرفرات: {len(bot.guilds)}"
    )

    print("=" * 60)


# ==========================================================
# HELPERS
# ==========================================================

def get_config(guild_id):

    return db.get_ai_config(
        guild_id
    )


def get_character(
    guild_id,
    character_name
):

    if not character_name:
        return None

    return db.get_character(
        guild_id,
        character_name
    )


def split_message(
    text,
    limit=1900
):

    text = str(text)

    if len(text) <= limit:
        return [text]

    chunks = []

    while text:

        chunks.append(
            text[:limit]
        )

        text = text[limit:]

    return chunks


async def send_ai_response(
    message,
    response
):

    chunks = split_message(
        response
    )

    for chunk in chunks:

        await message.channel.send(
            chunk,
            allowed_mentions=discord.AllowedMentions.none()
        )


# ==========================================================
# AI COMMAND
# ==========================================================

@bot.tree.command(
    name="ai",
    description="تحدث مع MyAI"
)
@app_commands.describe(
    message="رسالتك إلى الذكاء الاصطناعي"
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

    guild_id = interaction.guild.id
    channel_id = interaction.channel.id

    config = get_config(
        guild_id
    )

    character_name = (
        config.get("character_name")
        or "MyAI"
    )

    character = get_character(
        guild_id,
        character_name
    )

    if not character:

        characters = db.get_characters(
            guild_id
        )

        if not characters:

            await interaction.response.send_message(
                "❌ لا توجد شخصية AI في هذا السيرفر.\n"
                "استخدم `/character_create` لإنشاء شخصية.",
                ephemeral=True
            )

            return

        character = characters[0]
        character_name = character["name"]

        db.set_active_character(
            guild_id,
            character_name
        )

    await interaction.response.defer(
        thinking=True
    )

    try:

        response = await ai.generate(
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=interaction.user.id,
            character_name=character_name,
            user_message=message,
            provider=config.get(
                "provider",
                "google"
            ),
            model=config.get(
                "model",
                "gemini-3.6-flash"
            ),
            mode=config.get(
                "mode",
                "normal"
            )
        )

        chunks = split_message(
            response,
            1900
        )

        await interaction.followup.send(
            chunks[0],
            allowed_mentions=discord.AllowedMentions.none()
        )

        for chunk in chunks[1:]:

            await interaction.followup.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none()
            )

    except Exception as e:

        print(
            f"❌ AI ERROR: {repr(e)}"
        )

        await interaction.followup.send(
            "❌ حصل خطأ أثناء تشغيل الذكاء الاصطناعي.\n"
            f"```{str(e)[:1500]}```",
            ephemeral=True
        )


# ==========================================================
# AI SETUP
# ==========================================================

@bot.tree.command(
    name="ai_setup",
    description="إعداد MyAI في السيرفر"
)
@app_commands.checks.has_permissions(
    manage_guild=True
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

    guild_id = interaction.guild.id

    config = get_config(
        guild_id
    )

    character_name = (
        config.get("character_name")
        or "غير محددة"
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

    enabled = bool(
        config.get(
            "enabled",
            0
        )
    )

    channel_text = (
        f"<#{channel_id}>"
        if channel_id
        else "غير محددة"
    )

    mode_info = ai.get_mode(
        mode
    )

    reply_info = ai.get_reply_type(
        reply_type
    )

    embed = discord.Embed(
        title="🤖 MyAI BOT — لوحة التحكم",
        description=(
            "أهلًا بك في إعدادات MyAI.\n\n"
            "اختر الإعداد الذي تريده من الأزرار بالأسفل."
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="الحالة",
        value=(
            "🟢 مفعّل"
            if enabled
            else "🔴 متوقف"
        ),
        inline=True
    )

    embed.add_field(
        name="الشخصية",
        value=f"🧠 {character_name}",
        inline=True
    )

    embed.add_field(
        name="النمط",
        value=mode_info["name"],
        inline=True
    )

    embed.add_field(
        name="نوع الرد",
        value=reply_info["name"],
        inline=True
    )

    embed.add_field(
        name="القناة",
        value=channel_text,
        inline=True
    )

    embed.add_field(
        name="الموديل",
        value="Gemini 3.6 Flash",
        inline=True
    )

    embed.set_footer(
        text="MyAI • AI Discord Assistant"
    )

    view = SetupView(
        guild_id
    )

    await interaction.response.send_message(
        embed=embed,
        view=view,
        ephemeral=True
    )


# ==========================================================
# CHARACTER CREATE
# ==========================================================

@bot.tree.command(
    name="character_create",
    description="إنشاء شخصية AI جديدة"
)
@app_commands.describe(
    name="اسم الشخصية",
    personality="وصف الشخصية وطريقة تصرفها"
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

    try:

        character = db.create_character(
            guild_id=interaction.guild.id,
            name=name,
            personality=personality,
            provider="google",
            model="gemini-3.6-flash",
            created_by=interaction.user.id
        )

        await interaction.response.send_message(
            "✅ تم إنشاء الشخصية بنجاح!\n\n"
            f"🧠 **الاسم:** {character['name']}\n"
            f"📝 **الشخصية:** {character['personality']}\n"
            "🤖 **الموديل:** Gemini 3.6 Flash",
            ephemeral=True
        )

    except Exception as e:

        await interaction.response.send_message(
            f"❌ {e}",
            ephemeral=True
        )


# ==========================================================
# CHARACTER LIST
# ==========================================================

@bot.tree.command(
    name="character_list",
    description="عرض شخصيات AI في السيرفر"
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
            "📭 لا توجد شخصيات حاليًا.",
            ephemeral=True
        )

        return

    lines = []

    config = get_config(
        interaction.guild.id
    )

    active = config.get(
        "character_name"
    )

    for character in characters:

        marker = (
            " 🟢"
            if character["name"] == active
            else ""
        )

        lines.append(
            f"🧠 **{character['name']}**{marker}\n"
            f"└ {character['personality'][:150]}"
        )

    embed = discord.Embed(
        title="🧠 شخصيات MyAI",
        description="\n\n".join(lines),
        color=discord.Color.blurple()
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ==========================================================
# CHARACTER USE
# ==========================================================

@bot.tree.command(
    name="character_use",
    description="اختيار شخصية AI الحالية"
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

    try:

        db.set_active_character(
            interaction.guild.id,
            name
        )

        await interaction.response.send_message(
            f"✅ تم اختيار الشخصية **{name}**.",
            ephemeral=True
        )

    except Exception as e:

        await interaction.response.send_message(
            f"❌ {e}",
            ephemeral=True
        )


# ==========================================================
# AI STATUS
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

    guild_id = interaction.guild.id

    config = get_config(
        guild_id
    )

    stats = db.get_stats(
        guild_id
    )

    channel_id = config.get(
        "channel_id"
    )

    channel_text = (
        f"<#{channel_id}>"
        if channel_id
        else "غير محددة"
    )

    embed = discord.Embed(
        title="📊 حالة MyAI",
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
        name="الموديل",
        value="Gemini 3.6 Flash",
        inline=True
    )

    embed.add_field(
        name="القناة",
        value=channel_text,
        inline=True
    )

    embed.add_field(
        name="الشخصية",
        value=(
            config.get(
                "character_name"
            )
            or "غير محددة"
        ),
        inline=True
    )

    embed.add_field(
        name="الرسائل",
        value=str(
            stats["messages"]
        ),
        inline=True
    )

    embed.add_field(
        name="الشخصيات",
        value=str(
            stats["characters"]
        ),
        inline=True
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ==========================================================
# MEMORY CLEAR
# ==========================================================

@bot.tree.command(
    name="ai_memory_clear",
    description="مسح ذاكرة محادثة MyAI"
)
@app_commands.checks.has_permissions(
    manage_guild=True
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

    db.clear_history(
        interaction.guild.id,
        channel_id=interaction.channel.id
    )

    await interaction.response.send_message(
        "🧹 تم مسح ذاكرة MyAI في هذه القناة.",
        ephemeral=True
    )


# ==========================================================
# SETUP VIEW
# ==========================================================

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

    # ------------------------------------------------------
    # ENABLE
    # ------------------------------------------------------

    @discord.ui.button(
        label="تشغيل AI",
        emoji="🟢",
        style=discord.ButtonStyle.success,
        row=0
    )
    async def enable(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not interaction.user.guild_permissions.manage_guild:

            await interaction.response.send_message(
                "❌ تحتاج صلاحية إدارة السيرفر.",
                ephemeral=True
            )

            return

        db.set_ai_enabled(
            self.guild_id,
            True
        )

        await interaction.response.send_message(
            "🟢 تم تشغيل MyAI.",
            ephemeral=True
        )

    # ------------------------------------------------------
    # DISABLE
    # ------------------------------------------------------

    @discord.ui.button(
        label="إيقاف AI",
        emoji="🔴",
        style=discord.ButtonStyle.danger,
        row=0
    )
    async def disable(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not interaction.user.guild_permissions.manage_guild:

            await interaction.response.send_message(
                "❌ تحتاج صلاحية إدارة السيرفر.",
                ephemeral=True
            )

            return

        db.set_ai_enabled(
            self.guild_id,
            False
        )

        await interaction.response.send_message(
            "🔴 تم إيقاف MyAI.",
            ephemeral=True
        )

    # ------------------------------------------------------
    # MODE
    # ------------------------------------------------------

    @discord.ui.select(
        placeholder="🎛️ اختر نمط AI",
        row=1,
        options=[
            discord.SelectOption(
                label="عادي",
                value="normal",
                emoji="🤖"
            ),
            discord.SelectOption(
                label="اجتماعي",
                value="friendly",
                emoji="😎"
            ),
            discord.SelectOption(
                label="نشيط",
                value="active",
                emoji="🔥"
            ),
            discord.SelectOption(
                label="كوميدي",
                value="fun",
                emoji="😂"
            ),
            discord.SelectOption(
                label="احترافي",
                value="professional",
                emoji="🧠"
            )
        ]
    )
    async def mode_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select
    ):

        if not interaction.user.guild_permissions.manage_guild:

            await interaction.response.send_message(
                "❌ تحتاج صلاحية إدارة السيرفر.",
                ephemeral=True
            )

            return

        mode = select.values[0]

        db.set_ai_mode(
            self.guild_id,
            mode
        )

        await interaction.response.send_message(
            f"✅ تم تغيير النمط إلى "
            f"**{ai.get_mode(mode)['name']}**.",
            ephemeral=True
        )

    # ------------------------------------------------------
    # REPLY TYPE
    # ------------------------------------------------------

    @discord.ui.select(
        placeholder="💬 اختر طريقة الرد",
        row=2,
        options=[
            discord.SelectOption(
                label="عند المنشن",
                value="mention",
                emoji="📌"
            ),
            discord.SelectOption(
                label="داخل القناة",
                value="channel",
                emoji="💬"
            ),
            discord.SelectOption(
                label="بالأمر فقط",
                value="command",
                emoji="⌨️"
            )
        ]
    )
    async def reply_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select
    ):

        if not interaction.user.guild_permissions.manage_guild:

            await interaction.response.send_message(
                "❌ تحتاج صلاحية إدارة السيرفر.",
                ephemeral=True
            )

            return

        reply_type = select.values[0]

        db.set_reply_type(
            self.guild_id,
            reply_type
        )

        await interaction.response.send_message(
            f"✅ تم تغيير طريقة الرد إلى "
            f"**{ai.get_reply_type(reply_type)['name']}**.",
            ephemeral=True
        )

    # ------------------------------------------------------
    # CHANNEL SELECT
    # ------------------------------------------------------

    @discord.ui.channel_select(
        placeholder="📺 اختر قناة AI",
        channel_types=[
            discord.ChannelType.text
        ],
        row=3
    )
    async def channel_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.ChannelSelect
    ):

        if not interaction.user.guild_permissions.manage_guild:

            await interaction.response.send_message(
                "❌ تحتاج صلاحية إدارة السيرفر.",
                ephemeral=True
            )

            return

        channel = select.values[0]

        db.set_ai_channel(
            self.guild_id,
            channel.id
        )

        await interaction.response.send_message(
            f"✅ تم اختيار {channel.mention} كقناة AI.",
            ephemeral=True
        )


# ==========================================================
# MESSAGE LISTENER
# ==========================================================

@bot.event
async def on_message(
    message: discord.Message
):

    # تجاهل البوتات
    if message.author.bot:
        return

    # تجاهل الخاص
    if not message.guild:
        return

    guild_id = message.guild.id

    config = get_config(
        guild_id
    )

    # AI غير مفعّل
    if not config.get("enabled"):
        await bot.process_commands(message)
        return

    reply_type = config.get(
        "reply_type",
        "mention"
    )

    # بالأمر فقط
    if reply_type == "command":

        await bot.process_commands(
            message
        )

        return

    # ------------------------------------------------------
    # CHARACTER
    # ------------------------------------------------------

    character_name = (
        config.get(
            "character_name"
        )
        or "MyAI"
    )

    character = db.get_character(
        guild_id,
        character_name
    )

    if not character:

        await bot.process_commands(
            message
        )

        return

    # ------------------------------------------------------
    # CHANNEL MODE
    # ------------------------------------------------------

    if reply_type == "channel":

        configured_channel = config.get(
            "channel_id"
        )

        if not configured_channel:
            await bot.process_commands(
                message
            )
            return

        if message.channel.id != configured_channel:

            await bot.process_commands(
                message
            )

            return

        user_text = message.content.strip()

    # ------------------------------------------------------
    # MENTION MODE
    # ------------------------------------------------------

    elif reply_type == "mention":

        if bot.user not in message.mentions:

            await bot.process_commands(
                message
            )

            return

        user_text = message.content

        user_text = user_text.replace(
            f"<@{bot.user.id}>",
            ""
        )

        user_text = user_text.replace(
            f"<@!{bot.user.id}>",
            ""
        )

        user_text = user_text.strip()

        if not user_text:

            await message.reply(
                "👋 هلا! وش تبي تسألني؟",
                mention_author=False
            )

            await bot.process_commands(
                message
            )

            return

    else:

        await bot.process_commands(
            message
        )

        return

    # ------------------------------------------------------
    # TYPING
    # ------------------------------------------------------

    try:

        async with message.channel.typing():

            response = await ai.generate(
                guild_id=guild_id,
                channel_id=message.channel.id,
                user_id=message.author.id,
                character_name=character_name,
                user_message=user_text,
                provider=config.get(
                    "provider",
                    "google"
                ),
                model=config.get(
                    "model",
                    "gemini-3.6-flash"
                ),
                mode=config.get(
                    "mode",
                    "normal"
                )
            )

        await send_ai_response(
            message,
            response
        )

    except Exception as e:

        print(
            f"❌ AUTO AI ERROR: {repr(e)}"
        )

        await message.reply(
            "❌ حصل خطأ أثناء تشغيل الذكاء الاصطناعي.",
            mention_author=False
        )

    await bot.process_commands(
        message
    )


# ==========================================================
# COMMAND ERROR HANDLER
# ==========================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):

        message = (
            "❌ ما عندك الصلاحية المطلوبة "
            "لاستخدام هذا الأمر."
        )

    else:

        print(
            f"❌ COMMAND ERROR: {repr(error)}"
        )

        message = (
            "❌ حدث خطأ أثناء تنفيذ الأمر."
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


# ==========================================================
# START
# ==========================================================

try:

    bot.run(
        TOKEN
    )

finally:

    try:
        db.close()
    except Exception:
        pass
