import os
import discord
from discord.ext import commands
from discord import app_commands

from database import Database
from ai_engine import AIEngine


# ============================================================
# BOT
# ============================================================

intents = discord.Intents.default()

intents.message_content = True

intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

db = Database()

ai = AIEngine(db)


# ============================================================
# SERVER CONFIG MEMORY
# ============================================================

SERVER_CONFIG = {}


def get_config(guild_id):

    if guild_id not in SERVER_CONFIG:

        SERVER_CONFIG[guild_id] = {

            "enabled": False,

            "channel_id": None,

            "mode": "normal",

            "reply_type": "mention",

            "character": None,

            "permissions": "chat"
        }

    return SERVER_CONFIG[guild_id]


# ============================================================
# EMBED
# ============================================================

def setup_embed(guild):

    config = get_config(
        guild.id
    )

    mode = ai.get_mode(
        config["mode"]
    )

    reply = ai.get_reply_type(
        config["reply_type"]
    )

    channel = (
        f"<#{config['channel_id']}>"
        if config["channel_id"]
        else "❌ لم يتم التحديد"
    )

    character = (
        config["character"]
        or "❌ لم يتم التحديد"
    )

    embed = discord.Embed(
        title="🤖 MyAI • لوحة التحكم",
        description=(
            "### ⚡ إعداد الذكاء الاصطناعي\n"
            "استخدم الأزرار والقوائم بالأسفل "
            "لتخصيص MyAI بسهولة.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 **الحالة:** "
            f"{'مفعل' if config['enabled'] else 'متوقف'}\n"
            f"📢 **القناة:** {channel}\n"
            f"🎭 **الشخصية:** `{character}`\n"
            f"🎛️ **النمط:** {mode['name']}\n"
            f"💬 **الرد:** {reply['name']}\n"
            f"🛡️ **الصلاحيات:** "
            f"`{config['permissions']}`"
        ),
        color=discord.Color.blurple()
    )

    embed.set_footer(
        text="MyAI • AI Server Control"
    )

    return embed


# ============================================================
# SETUP VIEW
# ============================================================

class AISetupView(
    discord.ui.View
):

    def __init__(self, guild):

        super().__init__(
            timeout=300
        )

        self.guild = guild

    # --------------------------------------------------------
    # ENABLE
    # --------------------------------------------------------

    @discord.ui.button(
        label="تشغيل AI",
        emoji="🟢",
        style=discord.ButtonStyle.success,
        row=0
    )
    async def enable(
        self,
        interaction,
        button
    ):

        config = get_config(
            self.guild.id
        )

        config["enabled"] = True

        await interaction.response.edit_message(
            embed=setup_embed(
                self.guild
            ),
            view=self
        )

    # --------------------------------------------------------
    # DISABLE
    # --------------------------------------------------------

    @discord.ui.button(
        label="إيقاف",
        emoji="🔴",
        style=discord.ButtonStyle.danger,
        row=0
    )
    async def disable(
        self,
        interaction,
        button
    ):

        config = get_config(
            self.guild.id
        )

        config["enabled"] = False

        await interaction.response.edit_message(
            embed=setup_embed(
                self.guild
            ),
            view=self
        )

    # --------------------------------------------------------
    # CHANNEL
    # --------------------------------------------------------

    @discord.ui.button(
        label="اختيار القناة",
        emoji="📢",
        style=discord.ButtonStyle.primary,
        row=1
    )
    async def channel(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "📢 **اختر قناة الذكاء الاصطناعي:**",
            view=ChannelView(
                self.guild
            ),
            ephemeral=True
        )

    # --------------------------------------------------------
    # MODE
    # --------------------------------------------------------

    @discord.ui.button(
        label="نوع AI",
        emoji="🎛️",
        style=discord.ButtonStyle.primary,
        row=1
    )
    async def mode(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "🎛️ **اختر نمط الذكاء الاصطناعي:**",
            view=ModeView(
                self.guild
            ),
            ephemeral=True
        )

    # --------------------------------------------------------
    # CHARACTER
    # --------------------------------------------------------

    @discord.ui.button(
        label="الشخصية",
        emoji="🎭",
        style=discord.ButtonStyle.primary,
        row=2
    )
    async def character(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "🎭 **اختر الشخصية:**",
            view=CharacterView(
                self.guild
            ),
            ephemeral=True
        )

    # --------------------------------------------------------
    # REPLY
    # --------------------------------------------------------

    @discord.ui.button(
        label="نوع الرد",
        emoji="💬",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def reply(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "💬 **اختر طريقة الرد:**",
            view=ReplyView(
                self.guild
            ),
            ephemeral=True
        )

    # --------------------------------------------------------
    # PERMISSIONS
    # --------------------------------------------------------

    @discord.ui.button(
        label="الصلاحيات",
        emoji="🛡️",
        style=discord.ButtonStyle.secondary,
        row=3
    )
    async def permissions(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "🛡️ **اختر مستوى الصلاحيات:**",
            view=PermissionView(
                self.guild
            ),
            ephemeral=True
        )


# ============================================================
# CHANNEL SELECT
# ============================================================

class ChannelSelect(
    discord.ui.ChannelSelect
):

    def __init__(self, guild):

        super().__init__(
            placeholder="📢 اختر قناة AI",
            channel_types=[
                discord.ChannelType.text
            ]
        )

        self.guild = guild

    async def callback(
        self,
        interaction
    ):

        channel = self.values[0]

        config = get_config(
            self.guild.id
        )

        config["channel_id"] = channel.id

        await interaction.response.send_message(
            f"✅ تم تحديد قناة AI:\n"
            f"{channel.mention}",
            ephemeral=True
        )


class ChannelView(
    discord.ui.View
):

    def __init__(self, guild):

        super().__init__(
            timeout=120
        )

        self.add_item(
            ChannelSelect(guild)
        )


# ============================================================
# MODE SELECT
# ============================================================

class ModeSelect(
    discord.ui.Select
):

    def __init__(self, guild):

        self.guild = guild

        options = []

        for key, data in ai.MODES.items():

            options.append(
                discord.SelectOption(
                    label=data["name"],
                    value=key,
                    description=data[
                        "description"
                    ][:100]
                )
            )

        super().__init__(
            placeholder="🎛️ اختر نمط AI",
            options=options
        )

    async def callback(
        self,
        interaction
    ):

        selected = self.values[0]

        config = get_config(
            self.guild.id
        )

        config["mode"] = selected

        await interaction.response.send_message(
            f"✅ تم اختيار:\n"
            f"**{ai.MODES[selected]['name']}**",
            ephemeral=True
        )


class ModeView(
    discord.ui.View
):

    def __init__(self, guild):

        super().__init__(
            timeout=120
        )

        self.add_item(
            ModeSelect(guild)
        )


# ============================================================
# REPLY SELECT
# ============================================================

class ReplySelect(
    discord.ui.Select
):

    def __init__(self, guild):

        self.guild = guild

        options = []

        for key, data in ai.REPLY_TYPES.items():

            options.append(
                discord.SelectOption(
                    label=data["name"],
                    value=key,
                    description=data[
                        "description"
                    ]
                )
            )

        super().__init__(
            placeholder="💬 اختر طريقة الرد",
            options=options
        )

    async def callback(
        self,
        interaction
    ):

        selected = self.values[0]

        config = get_config(
            self.guild.id
        )

        config["reply_type"] = selected

        await interaction.response.send_message(
            f"✅ تم اختيار:\n"
            f"**{ai.REPLY_TYPES[selected]['name']}**",
            ephemeral=True
        )


class ReplyView(
    discord.ui.View
):

    def __init__(self, guild):

        super().__init__(
            timeout=120
        )

        self.add_item(
            ReplySelect(guild)
        )


# ============================================================
# PERMISSION SELECT
# ============================================================

class PermissionSelect(
    discord.ui.Select
):

    def __init__(self, guild):

        self.guild = guild

        options = []

        for key, data in ai.PERMISSION_PRESETS.items():

            options.append(
                discord.SelectOption(
                    label=data["name"],
                    value=key,
                    description=data[
                        "description"
                    ]
                )
            )

        super().__init__(
            placeholder="🛡️ اختر الصلاحيات",
            options=options
        )

    async def callback(
        self,
        interaction
    ):

        selected = self.values[0]

        config = get_config(
            self.guild.id
        )

        config["permissions"] = selected

        await interaction.response.send_message(
            f"✅ تم اختيار الصلاحيات:\n"
            f"**{ai.PERMISSION_PRESETS[selected]['name']}**",
            ephemeral=True
        )


class PermissionView(
    discord.ui.View
):

    def __init__(self, guild):

        super().__init__(
            timeout=120
        )

        self.add_item(
            PermissionSelect(guild)
        )


# ============================================================
# CHARACTER SELECT
# ============================================================

class CharacterSelect(
    discord.ui.Select
):

    def __init__(self, guild):

        self.guild = guild

        rows = db.get_characters(
            guild.id
        )

        options = []

        for row in rows[:25]:

            row = ai.row_to_dict(
                row
            )

            options.append(
                discord.SelectOption(
                    label=row.get(
                        "name",
                        "Character"
                    )[:100],
                    value=row.get(
                        "name",
                        "Character"
                    )[:100]
                )
            )

        if not options:

            options.append(
                discord.SelectOption(
                    label="لا توجد شخصيات",
                    value="none",
                    description=(
                        "أنشئ شخصية أولًا."
                    )
                )
            )

        super().__init__(
            placeholder="🎭 اختر شخصية",
            options=options
        )

    async def callback(
        self,
        interaction
    ):

        selected = self.values[0]

        if selected == "none":

            await interaction.response.send_message(
                "❌ لا توجد شخصيات.",
                ephemeral=True
            )

            return

        config = get_config(
            self.guild.id
        )

        config["character"] = selected

        await interaction.response.send_message(
            f"✅ الشخصية الحالية:\n"
            f"🎭 **{selected}**",
            ephemeral=True
        )


class CharacterView(
    discord.ui.View
):

    def __init__(self, guild):

        super().__init__(
            timeout=120
        )

        self.add_item(
            CharacterSelect(guild)
        )


# ============================================================
# CHARACTER CREATE MODAL
# ============================================================

class CharacterModal(
    discord.ui.Modal,
    title="🎭 إنشاء شخصية AI"
):

    name = discord.ui.TextInput(
        label="اسم الشخصية",
        placeholder="مثال: سالم",
        max_length=50
    )

    personality = discord.ui.TextInput(
        label="شخصية AI",
        placeholder=(
            "مثال: مرح، ذكي، يحب مساعدة الأعضاء..."
        ),
        style=discord.TextStyle.paragraph,
        max_length=1000
    )

    async def on_submit(
        self,
        interaction
    ):

        guild_id = interaction.guild.id

        try:

            db.create_character(
                guild_id,
                self.name.value,
                self.personality.value,
                "google",
                "gemini-2.5-flash"
            )

            await interaction.response.send_message(
                f"✅ تم إنشاء الشخصية!\n\n"
                f"🎭 الاسم: **{self.name.value}**\n"
                f"🧠 المزود: **Gemini**",
                ephemeral=True
            )

        except Exception as e:

            await interaction.response.send_message(
                f"❌ تعذر إنشاء الشخصية:\n"
                f"`{e}`",
                ephemeral=True
            )


# ============================================================
# COMMAND: /ai setup
# ============================================================

@bot.tree.command(
    name="ai_setup",
    description="فتح لوحة إعداد MyAI"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def ai_setup(
    interaction: discord.Interaction
):

    embed = setup_embed(
        interaction.guild
    )

    await interaction.response.send_message(
        embed=embed,
        view=AISetupView(
            interaction.guild
        )
    )


# ============================================================
# COMMAND: /character create
# ============================================================

@bot.tree.command(
    name="character_create",
    description="إنشاء شخصية AI جديدة"
)
async def character_create(
    interaction: discord.Interaction
):

    await interaction.response.send_modal(
        CharacterModal()
    )


# ============================================================
# COMMAND: /ai
# ============================================================

@bot.tree.command(
    name="ai",
    description="التحدث مع MyAI"
)
@app_commands.describe(
    message="رسالتك إلى الذكاء الاصطناعي"
)
async def ai_command(
    interaction: discord.Interaction,
    message: str
):

    await interaction.response.defer()

    config = get_config(
        interaction.guild.id
    )

    if not config["character"]:

        await interaction.followup.send(
            "❌ لم يتم اختيار شخصية AI لهذا السيرفر.\n"
            "استخدم `/ai_setup` أولًا."
        )

        return

    try:

        response = await ai.generate(

            guild_id=
                interaction.guild.id,

            channel_id=
                interaction.channel.id,

            user_id=
                interaction.user.id,

            character_name=
                config["character"],

            user_message=
                message,

            provider=
                "google",

            model=
                "gemini-2.5-flash",

            mode=
                config["mode"]
        )

        await interaction.followup.send(
            response
        )

    except Exception as e:

        await interaction.followup.send(
            f"❌ حصل خطأ أثناء تشغيل الذكاء الاصطناعي.\n"
            f"```{e}```"
        )


# ============================================================
# MESSAGE LISTENER
# ============================================================

@bot.event
async def on_message(
    message
):

    if message.author.bot:
        return

    await bot.process_commands(
        message
    )

    if not message.guild:
        return

    config = get_config(
        message.guild.id
    )

    if not config["enabled"]:
        return

    if not config["character"]:
        return

    channel_id = config[
        "channel_id"
    ]

    reply_type = config[
        "reply_type"
    ]

    # ------------------------------------------
    # CHANNEL MODE
    # ------------------------------------------

    if reply_type == "channel":

        if channel_id != message.channel.id:
            return

    # ------------------------------------------
    # MENTION MODE
    # ------------------------------------------

    elif reply_type == "mention":

        if bot.user not in message.mentions:
            return

        message.content = (
            message.content
            .replace(
                f"<@{bot.user.id}>",
                ""
            )
            .replace(
                f"<@!{bot.user.id}>",
                ""
            )
            .strip()
        )

    # ------------------------------------------
    # COMMAND MODE
    # ------------------------------------------

    elif reply_type == "command":

        return

    if not message.content:
        return

    try:

        async with message.channel.typing():

            response = await ai.generate(

                guild_id=
                    message.guild.id,

                channel_id=
                    message.channel.id,

                user_id=
                    message.author.id,

                character_name=
                    config["character"],

                user_message=
                    message.content,

                provider=
                    "google",

                model=
                    "gemini-2.5-flash",

                mode=
                    config["mode"]
            )

            # رسالة عادية بدون Embed
            await message.channel.send(
                response
            )

    except Exception as e:

        print(
            "AI ERROR:",
            e
        )


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():

    try:

        synced = await bot.tree.sync()

        print(
            f"✅ تم مزامنة "
            f"{len(synced)} أمر Slash."
        )

    except Exception as e:

        print(
            "SYNC ERROR:",
            e
        )

    print(
        "=" * 60
    )

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

    print(
        "=" * 60
    )


# ============================================================
# ERROR HANDLER
# ============================================================

@bot.tree.error
async def on_app_command_error(
    interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):

        if interaction.response.is_done():

            await interaction.followup.send(
                "❌ تحتاج صلاحية **إدارة السيرفر**.",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "❌ تحتاج صلاحية **إدارة السيرفر**.",
                ephemeral=True
            )

        return

    print(
        "COMMAND ERROR:",
        error
    )


# ============================================================
# START
# ============================================================

TOKEN = os.getenv(
    "DISCORD_TOKEN"
)

if not TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN غير موجود في Environment Variables."
    )

bot.run(TOKEN)
