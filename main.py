import os
import discord

from discord import app_commands
from discord.ext import commands

from database import Database
from ai_engine import AIEngine


# ============================================================
# Secrets
# ============================================================

DISCORD_TOKEN = os.getenv(
    "DISCORD_TOKEN"
)


if not DISCORD_TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN غير موجود في Replit Secrets."
    )


# ============================================================
# Discord Intents
# ============================================================

intents = discord.Intents.default()

intents.message_content = True

intents.guilds = True

intents.messages = True


# ============================================================
# Bot
# ============================================================

class MyAIBot(
    commands.Bot
):

    def __init__(self):

        super().__init__(

            command_prefix="!",

            intents=intents,

            help_command=None
        )


        self.db = Database()

        self.ai = AIEngine(
            self.db
        )


    async def setup_hook(self):

        # -----------------------------------------------------
        # مزامنة Slash Commands
        # -----------------------------------------------------

        synced = await self.tree.sync()

        print(
            f"✅ تم مزامنة {len(synced)} أمر Slash."
        )


    async def on_ready(self):

        print()
        print("=" * 60)

        print(
            "🤖 MyAI اشتغل بنجاح!"
        )

        print(
            f"👤 الحساب: {self.user}"
        )

        print(
            f"🆔 ID: {self.user.id}"
        )

        print(
            f"🌐 السيرفرات: {len(self.guilds)}"
        )

        print("=" * 60)
        print()


bot = MyAIBot()


# ============================================================
# أداة إرسال رد طويل
# ============================================================

async def send_long(
    interaction,
    text
):

    if not text:

        return


    # Discord limit تقريبًا 2000 حرف
    # نخليها أقل بقليل

    chunks = [

        text[i:i + 1900]

        for i in range(
            0,
            len(text),
            1900
        )
    ]


    for chunk in chunks:

        await interaction.followup.send(
            chunk
        )


# ============================================================
# /help
# ============================================================

@bot.tree.command(
    name="help",
    description="عرض أوامر MyAI"
)
async def help_command(
    interaction: discord.Interaction
):

    text = """

# 🤖 MyAI

أهلًا! أنا MyAI، بوت ذكاء اصطناعي متعدد الشخصيات. 🧠

## 💬 الذكاء الاصطناعي

`/ai`

تحدث مع الشخصية الحالية.

## 👤 الشخصيات

`/character_create`

إنشاء شخصية جديدة.

`/characters`

عرض شخصيات السيرفر.

`/character_use`

اختيار الشخصية الحالية.

`/character_delete`

حذف شخصية.

## 🔌 الذكاء الاصطناعي

`/provider`

اختيار مزود AI والموديل.

## 🧠 الذاكرة

`/memory`

عرض جزء من الذاكرة.

`/forget`

مسح ذاكرة الشخصية في القناة.

## 🤝 الشخصيات

`/talk`

جعل شخصيتين تتحدثان مع بعض.

━━━━━━━━━━━━━━━━━━━━

🔥 MyAI
"""

    await interaction.response.send_message(
        text
    )


# ============================================================
# /ai
# ============================================================

@bot.tree.command(
    name="ai",
    description="تحدث مع شخصية MyAI الحالية"
)
@app_commands.describe(
    message="الرسالة التي تريد إرسالها للذكاء الاصطناعي"
)
async def ai_command(
    interaction: discord.Interaction,
    message: str
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفرات فقط.",
            ephemeral=True
        )

        return


    settings = bot.db.get_settings(
        interaction.guild.id
    )


    character_name = (
        settings["active_character"]
    )


    character = bot.db.get_character(

        interaction.guild.id,

        character_name
    )


    if not character:

        await interaction.response.send_message(

            "❌ ما عندك شخصية مفعلة.\n"
            "استخدم `/character_create` أولًا.",

            ephemeral=True
        )

        return


    await interaction.response.defer()


    try:

        answer = await bot.ai.generate(

            guild_id=
                interaction.guild.id,

            channel_id=
                interaction.channel.id,

            user_id=
                interaction.user.id,

            character_name=
                character_name,

            user_message=
                message
        )


        await send_long(
            interaction,
            f"**🤖 {character_name}**\n\n{answer}"
        )


    except Exception as error:

        print(
            "AI ERROR:",
            repr(error)
        )


        await interaction.followup.send(

            "❌ حصل خطأ أثناء تشغيل الذكاء الاصطناعي.\n\n"
            f"```{str(error)[:1200]}```"
        )


# ============================================================
# /character_create
# ============================================================

@bot.tree.command(
    name="character_create",
    description="إنشاء شخصية ذكاء اصطناعي"
)
@app_commands.describe(

    name="اسم الشخصية",

    description="وصف الشخصية",

    personality="شخصية وطريقة تصرف الشخصية",

    model="اسم موديل الذكاء الاصطناعي",

    provider="مزود الذكاء الاصطناعي"
)
async def character_create(

    interaction: discord.Interaction,

    name: str,

    description: str,

    personality: str,

    model: str = "",

    provider: str = "openai"
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ استخدم الأمر داخل سيرفر.",
            ephemeral=True
        )

        return


    provider = provider.lower()


    allowed = [

        "openai",

        "google",

        "anthropic",

        "custom"
    ]


    if provider not in allowed:

        await interaction.response.send_message(

            "❌ المزود غير صحيح.\n"
            "المتاح: openai / google / anthropic / custom",

            ephemeral=True
        )

        return


    system_prompt = f"""

أنت شخصية اسمها {name}.

الوصف:

{description}

الشخصية:

{personality}

حافظ على هذه الشخصية باستمرار.

تحدث بالعربية بطريقة طبيعية.

كن متسقًا في أسلوبك.

لا تخترع معلومات.

"""


    success = bot.db.create_character(

        guild_id=
            interaction.guild.id,

        name=
            name,

        description=
            description,

        personality=
            personality,

        system_prompt=
            system_prompt,

        provider=
            provider,

        model=
            model
    )


    if not success:

        await interaction.response.send_message(

            "❌ توجد شخصية بنفس الاسم بالفعل.",

            ephemeral=True
        )

        return


    await interaction.response.send_message(

        f"✅ تم إنشاء الشخصية **{name}**!\n\n"

        f"📝 **الوصف:** {description}\n"

        f"🎭 **الشخصية:** {personality}\n"

        f"🔌 **المزود:** `{provider}`\n"

        f"🧠 **الموديل:** `{model or 'غير محدد'}`\n\n"

        f"استخدم `/character_use` لتفعيلها."
    )


# ============================================================
# /characters
# ============================================================

@bot.tree.command(
    name="characters",
    description="عرض شخصيات MyAI"
)
async def characters_command(
    interaction: discord.Interaction
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ استخدم الأمر داخل سيرفر.",
            ephemeral=True
        )

        return


    characters = bot.db.get_characters(

        interaction.guild.id

    )


    if not characters:

        await interaction.response.send_message(

            "📭 ما فيه شخصيات حاليًا.\n"
            "استخدم `/character_create`.",

            ephemeral=True
        )

        return


    settings = bot.db.get_settings(

        interaction.guild.id

    )


    active = settings[
        "active_character"
    ]


    text = "# 👥 شخصيات MyAI\n\n"


    for character in characters:

        marker = (
            " 🟢 **الحالية**"
            if character["name"].lower()
            == active.lower()
            else ""
        )


        text += (

            f"### 👤 {character['name']}"
            f"{marker}\n"

            f"📝 {character['description']}\n"

            f"🔌 `{character['provider']}`\n"

            f"🧠 `{character['model'] or 'غير محدد'}`\n\n"
        )


    await interaction.response.send_message(
        text[:1900]
    )


# ============================================================
# /character_use
# ============================================================

@bot.tree.command(
    name="character_use",
    description="اختيار الشخصية الحالية"
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
            "❌ استخدم الأمر داخل سيرفر.",
            ephemeral=True
        )

        return


    character = bot.db.get_character(

        interaction.guild.id,

        name
    )


    if not character:

        await interaction.response.send_message(

            f"❌ الشخصية **{name}** غير موجودة.",

            ephemeral=True
        )

        return


    bot.db.set_active_character(

        interaction.guild.id,

        character["name"]
    )


    await interaction.response.send_message(

        f"✅ الشخصية الحالية أصبحت:\n\n"
        f"🤖 **{character['name']}**"
    )


# ============================================================
# /character_delete
# ============================================================

@bot.tree.command(
    name="character_delete",
    description="حذف شخصية"
)
@app_commands.describe(
    name="اسم الشخصية المراد حذفها"
)
async def character_delete(

    interaction: discord.Interaction,

    name: str
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ استخدم الأمر داخل سيرفر.",
            ephemeral=True
        )

        return


    character = bot.db.get_character(

        interaction.guild.id,

        name
    )


    if not character:

        await interaction.response.send_message(

            "❌ الشخصية غير موجودة.",

            ephemeral=True
        )

        return


    deleted = bot.db.delete_character(

        interaction.guild.id,

        name
    )


    if deleted:

        await interaction.response.send_message(

            f"🗑️ تم حذف الشخصية **{name}**."
        )

    else:

        await interaction.response.send_message(

            "❌ فشل حذف الشخصية.",

            ephemeral=True
        )


# ============================================================
# /provider
# ============================================================

@bot.tree.command(
    name="provider",
    description="اختيار مزود الذكاء الاصطناعي والموديل"
)
@app_commands.describe(

    provider="مزود الذكاء الاصطناعي",

    model="اسم الموديل"
)
async def provider_command(

    interaction: discord.Interaction,

    provider: str,

    model: str
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ استخدم الأمر داخل سيرفر.",
            ephemeral=True
        )

        return


    provider = provider.lower()


    allowed = [

        "openai",

        "google",

        "anthropic",

        "custom"
    ]


    if provider not in allowed:

        await interaction.response.send_message(

            "❌ مزود غير صحيح.\n\n"

            "المتاح:\n"
            "`openai`\n"
            "`google`\n"
            "`anthropic`\n"
            "`custom`",

            ephemeral=True
        )

        return


    bot.db.set_provider(

        interaction.guild.id,

        provider,

        model
    )


    await interaction.response.send_message(

        "✅ تم تحديث إعدادات AI.\n\n"

        f"🔌 المزود: `{provider}`\n"

        f"🧠 الموديل: `{model}`"
    )


# ============================================================
# /memory
# ============================================================

@bot.tree.command(
    name="memory",
    description="عرض ذاكرة الشخصية الحالية"
)
async def memory_command(

    interaction: discord.Interaction
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ استخدم الأمر داخل سيرفر.",
            ephemeral=True
        )

        return


    settings = bot.db.get_settings(

        interaction.guild.id

    )


    character = settings[
        "active_character"
    ]


    history = bot.db.get_history(

        interaction.guild.id,

        interaction.channel.id,

        character,

        limit=10
    )


    if not history:

        await interaction.response.send_message(

            "🧠 الذاكرة فارغة.",

            ephemeral=True
        )

        return


    text = (

        f"# 🧠 ذاكرة {character}\n\n"
    )


    for item in history:

        role = (

            "👤 المستخدم"

            if item["role"] == "user"

            else

            "🤖 الشخصية"
        )


        text += (

            f"**{role}:**\n"
            f"{item['content'][:300]}\n\n"
        )


    await interaction.response.send_message(

        text[:1900],

        ephemeral=True
    )


# ============================================================
# /forget
# ============================================================

@bot.tree.command(
    name="forget",
    description="مسح ذاكرة الشخصية في هذه القناة"
)
async def forget_command(

    interaction: discord.Interaction
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ استخدم الأمر داخل سيرفر.",
            ephemeral=True
        )

        return


    settings = bot.db.get_settings(

        interaction.guild.id
    )


    character = settings[
        "active_character"
    ]


    bot.db.clear_history(

        interaction.guild.id,

        interaction.channel.id,

        character
    )


    await interaction.response.send_message(

        f"🧹 تم مسح ذاكرة **{character}** "
        f"في هذه القناة."
    )


# ============================================================
# /talk
# ============================================================

@bot.tree.command(
    name="talk",
    description="جعل شخصيتين تتحدثان مع بعض"
)
@app_commands.describe(

    character_a="الشخصية الأولى",

    character_b="الشخصية الثانية",

    topic="موضوع الحوار",

    rounds="عدد الجولات من 2 إلى 12"
)
async def talk_command(

    interaction: discord.Interaction,

    character_a: str,

    character_b: str,

    topic: str,

    rounds: int = 6
):

    if not interaction.guild:

        await interaction.response.send_message(
            "❌ استخدم الأمر داخل سيرفر.",
            ephemeral=True
        )

        return


    if rounds < 2:

        rounds = 2


    if rounds > 12:

        rounds = 12


    a = bot.db.get_character(

        interaction.guild.id,

        character_a
    )


    b = bot.db.get_character(

        interaction.guild.id,

        character_b
    )


    if not a:

        await interaction.response.send_message(

            f"❌ الشخصية **{character_a}** غير موجودة.",

            ephemeral=True
        )

        return


    if not b:

        await interaction.response.send_message(

            f"❌ الشخصية **{character_b}** غير موجودة.",

            ephemeral=True
        )

        return


    await interaction.response.defer()


    try:

        conversation = (

            await bot.ai.character_conversation(

                guild_id=
                    interaction.guild.id,

                channel_id=
                    interaction.channel.id,

                character_a=
                    a["name"],

                character_b=
                    b["name"],

                topic=
                    topic,

                rounds=
                    rounds
            )
        )


        await interaction.followup.send(

            f"# 🤖💬 حوار الشخصيات\n\n"
            f"📌 **الموضوع:** {topic}\n"
            f"👤 **{a['name']}** × "
            f"**{b['name']}**"
        )


        for message in conversation:

            await interaction.followup.send(
                message[:1900]
            )


    except Exception as error:

        print(
            "TALK ERROR:",
            repr(error)
        )


        await interaction.followup.send(

            "❌ حدث خطأ أثناء تشغيل الحوار.\n\n"

            f"```{str(error)[:1200]}```"
        )


# ============================================================
# تشغيل البوت
# ============================================================

bot.run(
    DISCORD_TOKEN
)