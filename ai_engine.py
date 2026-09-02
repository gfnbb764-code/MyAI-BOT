import os
import aiohttp


class AIEngine:
    DEFAULT_PROVIDER = os.getenv("PRIMARY_AI_PROVIDER", "google").lower()

    DEFAULT_MODELS = {
        "google": "gemini-2.5-flash",
        "openai": "gpt-5.6-luna",
        "anthropic": "claude-sonnet-4-6",
    }

    def __init__(self, database):
        self.database = database
        self.reload_keys()

    def reload_keys(self):
        self.api_keys = {
            "google": os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"),
            "openai": os.getenv("OPENAI_API_KEY"),
            "anthropic": os.getenv("ANTHROPIC_API_KEY"),
            "custom": os.getenv("CUSTOM_API_KEY"),
        }

        self.endpoints = {
            "google": os.getenv(
                "GOOGLE_API_ENDPOINT",
                "https://generativelanguage.googleapis.com/v1beta"
            ),
            "openai": os.getenv(
                "OPENAI_API_ENDPOINT",
                "https://api.openai.com/v1/chat/completions"
            ),
            "anthropic": os.getenv(
                "ANTHROPIC_API_ENDPOINT",
                "https://api.anthropic.com/v1/messages"
            ),
            "custom": os.getenv("CUSTOM_API_ENDPOINT", ""),
        }

    def provider_available(self, provider):
        provider = (provider or "").lower()
        return bool(self.api_keys.get(provider))

    def build_system_prompt(self, character):
        name = character.get("name", "MyAI")
        personality = character.get(
            "personality",
            "أنت مساعد ذكاء اصطناعي ودود ومفيد."
        )

        return f"""
اسم الشخصية: {name}

شخصية البوت:
{personality}

كن طبيعيًا في الحوار، وافهم سياق الرسائل السابقة.
لا تذكر أنك مجرد API إلا إذا كان ذلك ضروريًا.
"""

    # =========================
    # Google Gemini
    # =========================

    async def _request_google(
        self,
        model,
        messages,
        temperature=0.8,
        max_tokens=1200
    ):
        api_key = self.api_keys["google"]

        if not api_key:
            raise RuntimeError("API Key غير موجود للمزود: google")

        base_url = self.endpoints["google"].rstrip("/")

        # نحول رسائل النظام إلى systemInstruction
        system_parts = []
        contents = []

        for message in messages:
            role = message.get("role", "user")
            text = str(message.get("content", ""))

            if not text:
                continue

            if role == "system":
                system_parts.append({
                    "text": text
                })

            elif role == "assistant":
                contents.append({
                    "role": "model",
                    "parts": [
                        {"text": text}
                    ]
                })

            else:
                contents.append({
                    "role": "user",
                    "parts": [
                        {"text": text}
                    ]
                })

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }

        if system_parts:
            payload["systemInstruction"] = {
                "parts": system_parts
            }

        url = f"{base_url}/models/{model}:generateContent"

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:

                data = await response.json()

                if response.status >= 400:
                    error = data.get("error", {})
                    message = error.get(
                        "message",
                        f"HTTP {response.status}"
                    )
                    raise RuntimeError(
                        f"Gemini API Error {response.status}: {message}"
                    )

        candidates = data.get("candidates", [])

        if not candidates:
            raise RuntimeError("Gemini لم يرجع أي نتيجة.")

        parts = candidates[0].get("content", {}).get("parts", [])

        text_parts = [
            part.get("text", "")
            for part in parts
            if part.get("text")
        ]

        result = "".join(text_parts).strip()

        if not result:
            raise RuntimeError("Gemini رجع استجابة بدون نص.")

        return result

    # =========================
    # OpenAI
    # =========================

    async def _request_openai(
        self,
        model,
        messages,
        temperature=0.8,
        max_tokens=1200
    ):
        api_key = self.api_keys["openai"]

        if not api_key:
            raise RuntimeError("API Key غير موجود للمزود: openai")

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.endpoints["openai"],
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:

                data = await response.json()

                if response.status >= 400:
                    error = data.get("error", {})
                    message = error.get(
                        "message",
                        f"HTTP {response.status}"
                    )

                    raise RuntimeError(
                        f"OpenAI API Error {response.status}: {message}"
                    )

        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("صيغة استجابة OpenAI غير متوقعة.")

    # =========================
    # Anthropic
    # =========================

    async def _request_anthropic(
        self,
        model,
        messages,
        temperature=0.8,
        max_tokens=1200
    ):
        api_key = self.api_keys["anthropic"]

        if not api_key:
            raise RuntimeError("API Key غير موجود للمزود: anthropic")

        system_messages = []
        chat_messages = []

        for message in messages:
            role = message.get("role", "user")
            content = str(message.get("content", ""))

            if role == "system":
                system_messages.append(content)
            else:
                if role not in ("user", "assistant"):
                    role = "user"

                chat_messages.append({
                    "role": role,
                    "content": content
                })

        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": chat_messages
        }

        if system_messages:
            payload["system"] = "\n\n".join(system_messages)

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.endpoints["anthropic"],
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:

                data = await response.json()

                if response.status >= 400:
                    error = data.get("error", {})
                    message = error.get(
                        "message",
                        f"HTTP {response.status}"
                    )

                    raise RuntimeError(
                        f"Anthropic API Error {response.status}: {message}"
                    )

        blocks = data.get("content", [])

        text_parts = [
            block.get("text", "")
            for block in blocks
            if block.get("type") == "text"
        ]

        result = "".join(text_parts).strip()

        if not result:
            raise RuntimeError("Anthropic رجع استجابة بدون نص.")

        return result

    # =========================
    # Main request
    # =========================

    async def request(
        self,
        provider,
        model,
        messages,
        temperature=0.8,
        max_tokens=1200
    ):
        provider = (
            provider or self.DEFAULT_PROVIDER or "google"
        ).lower()

        if not model:
            model = self.DEFAULT_MODELS.get(
                provider,
                self.DEFAULT_MODELS["google"]
            )

        if provider == "google":
            return await self._request_google(
                model,
                messages,
                temperature,
                max_tokens
            )

        if provider == "openai":
            return await self._request_openai(
                model,
                messages,
                temperature,
                max_tokens
            )

        if provider == "anthropic":
            return await self._request_anthropic(
                model,
                messages,
                temperature,
                max_tokens
            )

        raise RuntimeError(
            f"مزود غير مدعوم: {provider}"
        )

    # =========================
    # Generate
    # =========================

    async def generate(
        self,
        guild_id,
        channel_id,
        user_id,
        character_name,
        user_message,
        provider=None,
        model=None
    ):
        character = self.database.get_character(
            guild_id,
            character_name
        )

        if not character:
            raise RuntimeError(
                f"الشخصية غير موجودة: {character_name}"
            )

        settings = self.database.get_settings(guild_id)

        # Gemini هو الأساسي
        provider = (
            provider
            or os.getenv("PRIMARY_AI_PROVIDER")
            or "google"
        ).lower()

        # إذا لم يتم تحديد موديل، نستخدم موديل المزود الأساسي
        if not model:
            model = self.DEFAULT_MODELS.get(
                provider,
                self.DEFAULT_MODELS["google"]
            )

        system_prompt = self.build_system_prompt(character)

        history = self.database.get_history(
            guild_id,
            channel_id,
            character_name
        )

        messages = [
            {
                "role": "system",
                "content": system_prompt
            }
        ]

        for item in history:
            messages.append({
                "role": item.get("role", "user"),
                "content": item.get("content", "")
            })

        messages.append({
            "role": "user",
            "content": user_message
        })

        response = await self.request(
            provider=provider,
            model=model,
            messages=messages,
            temperature=0.8,
            max_tokens=1200
        )

        # حفظ المحادثة
        self.database.add_message(
            guild_id,
            channel_id,
            user_id,
            character_name,
            "user",
            user_message
        )

        self.database.add_message(
            guild_id,
            channel_id,
            user_id,
            character_name,
            "assistant",
            response
        )

        return response

    # =========================
    # Character conversation
    # =========================

    async def character_conversation(
        self,
        guild_id,
        channel_id,
        character_a,
        character_b,
        topic,
        rounds=6
    ):
        char_a = self.database.get_character(
            guild_id,
            character_a
        )

        char_b = self.database.get_character(
            guild_id,
            character_b
        )

        if not char_a or not char_b:
            raise RuntimeError(
                "إحدى الشخصيات غير موجودة."
            )

        provider = os.getenv(
            "PRIMARY_AI_PROVIDER",
            "google"
        ).lower()

        model = self.DEFAULT_MODELS.get(
            provider,
            "gemini-2.5-flash"
        )

        conversation = []

        current_character = char_a
        other_character = char_b

        for _ in range(rounds):
            system_prompt = self.build_system_prompt(
                current_character
            )

            messages = [
                {
                    "role": "system",
                    "content": system_prompt
                }
            ]

            for item in conversation:
                messages.append({
                    "role": item["role"],
                    "content": item["content"]
                })

            messages.append({
                "role": "user",
                "content": (
                    f"أنت الآن تتحدث مع شخصية "
                    f"{other_character['name']}.\n"
                    f"الموضوع: {topic}\n"
                    f"رد بشكل طبيعي."
                )
            })

            response = await self.request(
                provider,
                model,
                messages,
                temperature=0.9,
                max_tokens=600
            )

            conversation.append({
                "role": "assistant",
                "content": response
            })

            current_character, other_character = (
                other_character,
                current_character
            )

        return conversation

    async def close(self):
        pass
