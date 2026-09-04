from __future__ import annotations

import os
import json
import asyncio
from typing import Optional, Dict, Any

import aiohttp


# ============================================================
# CONFIG
# ============================================================

DEFAULT_PROVIDER = os.getenv(
    "PRIMARY_AI_PROVIDER",
    "google",
).strip().lower()

GOOGLE_DEFAULT_MODEL = os.getenv(
    "GOOGLE_MODEL",
    "gemini-3.5-flash-lite",
).strip()

OPENAI_DEFAULT_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-5.6-luna",
).strip()

ANTHROPIC_DEFAULT_MODEL = os.getenv(
    "ANTHROPIC_MODEL",
    "claude-sonnet-4-6",
).strip()


MODEL_ALIASES = {
    "gemini-2.5-flash-lite": "gemini-3.5-flash-lite",
}


# ============================================================
# AI MODES
# ============================================================

AI_MODES = {
    "normal": {
        "temperature": 0.7,
        "max_tokens": 1200,
        "auto_reply": False,
    },
    "friendly": {
        "temperature": 0.85,
        "max_tokens": 1400,
        "auto_reply": False,
    },
    "active": {
        "temperature": 0.9,
        "max_tokens": 1500,
        "auto_reply": True,
    },
    "fun": {
        "temperature": 1.0,
        "max_tokens": 1500,
        "auto_reply": True,
    },
    "professional": {
        "temperature": 0.45,
        "max_tokens": 1800,
        "auto_reply": False,
    },
}


# ============================================================
# REPLY TYPES
# ============================================================

REPLY_TYPES = {
    "mention",
    "channel",
    "direct",
    "auto",
    "bot_chat",
}


# ============================================================
# CHARACTER TYPES
# ============================================================

CHARACTER_TYPES = {
    "normal": "مساعد طبيعي ومتوازن.",
    "calm": "هادئ ومحترم ويتحدث بهدوء.",
    "smart": "ذكي وتحليلي ويشرح الأمور بوضوح.",
    "funny": "مرح ويحب المزاح بدون مبالغة.",
    "friendly": "ودود ولطيف ويتفاعل بشكل إيجابي.",
    "formal": "رسمي ومنظم ومحترم.",
    "energetic": "حماسي ونشيط في الحديث.",
    "rude": "حاد في أسلوبه لكن بدون إساءة خطيرة أو محتوى غير مناسب.",
    "mischievous": "مشاغب ومرح ويحب المقالب الخفيفة.",
    "curious": "فضولي ويحب طرح الأسئلة والتفكير.",
    "creative": "إبداعي ويقدم أفكارًا مختلفة.",
    "professional": "احترافي ودقيق ومباشر.",
}


# ============================================================
# HELPERS
# ============================================================

def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _clean_text(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


# ============================================================
# AI ENGINE
# ============================================================

class AIEngine:

    def __init__(self, db):

        self.db = db

        self.google_key = ""
        self.openai_key = ""
        self.anthropic_key = ""

        self.google_base_url = (
            "https://generativelanguage.googleapis.com/"
            "v1beta/models/{model}:generateContent"
        )

        self.openai_url = (
            "https://api.openai.com/v1/responses"
        )

        self.anthropic_url = (
            "https://api.anthropic.com/v1/messages"
        )

        self.timeout = _safe_int(
            os.getenv(
                "AI_REQUEST_TIMEOUT",
                "90",
            ),
            90,
        )

        self.reload_keys()

    # ========================================================
    # RELOAD API KEYS
    # ========================================================

    def reload_keys(self):

        self.google_key = os.getenv(
            "GOOGLE_API_KEY",
            "",
        ).strip() or os.getenv(
            "GEMINI_API_KEY",
            "",
        ).strip()

        self.openai_key = os.getenv(
            "OPENAI_API_KEY",
            "",
        ).strip()

        self.anthropic_key = os.getenv(
            "ANTHROPIC_API_KEY",
            "",
        ).strip()

    # ========================================================
    # ROW TO DICT
    # ========================================================

    def row_to_dict(
        self,
        row,
    ) -> Dict[str, Any]:

        if row is None:
            return {}

        if isinstance(row, dict):
            return dict(row)

        try:
            return dict(row)
        except Exception:
            return {}

    # ========================================================
    # MODE
    # ========================================================

    def get_mode(
        self,
        name: Optional[str],
    ) -> Dict[str, Any]:

        name = _clean_text(
            name
        ).lower()

        if name not in AI_MODES:
            name = "normal"

        return AI_MODES[name]

    # ========================================================
    # REPLY TYPE
    # ========================================================

    def get_reply_type(
        self,
        value: Optional[str],
    ) -> str:

        value = _clean_text(
            value
        ).lower()

        if value not in REPLY_TYPES:
            return "mention"

        return value

    # ========================================================
    # MODEL
    # ========================================================

    def resolve_model(
        self,
        provider: str,
        model: Optional[str] = None,
    ) -> str:

        provider = _clean_text(
            provider
        ).lower()

        model = _clean_text(
            model
        )

        if provider == "google":

            model = (
                model
                or GOOGLE_DEFAULT_MODEL
            )

        elif provider == "openai":

            model = (
                model
                or OPENAI_DEFAULT_MODEL
            )

        elif provider == "anthropic":

            model = (
                model
                or ANTHROPIC_DEFAULT_MODEL
            )

        if model in MODEL_ALIASES:

            model = MODEL_ALIASES[model]

        return model

    # ========================================================
    # CHARACTER TYPE
    # ========================================================

    def get_character_type_description(
        self,
        character_type: Optional[str],
    ) -> str:

        character_type = _clean_text(
            character_type
        ).lower()

        return CHARACTER_TYPES.get(
            character_type,
            CHARACTER_TYPES["normal"],
        )

    # ========================================================
    # SYSTEM PROMPT
    # ========================================================

    def build_system_prompt(
        self,
        character: Optional[Dict[str, Any]] = None,
        mode: Optional[str] = None,
        advanced: Optional[Dict[str, Any]] = None,
    ) -> str:

        character = character or {}
        advanced = advanced or {}

        name = _clean_text(
            character.get("name")
        ) or "مساعد MyAI"

        description = _clean_text(
            character.get("description")
        )

        character_type = _clean_text(
            character.get("type")
        ) or "normal"

        personality = _clean_text(
            character.get("personality")
        )

        mode_name = _clean_text(
            mode
        ).lower() or "normal"

        type_description = (
            self.get_character_type_description(
                character_type
            )
        )

        prompt_parts = [
            f"أنت {name}.",
            type_description,
            "تحدث باللغة التي يستخدمها المستخدم.",
            "كن واضحًا ومفيدًا وطبيعيًا.",
            "لا تدّعي أنك إنسان حقيقي.",
        ]

        if description:

            prompt_parts.append(
                f"وصف الشخصية: {description}"
            )

        if personality:

            prompt_parts.append(
                f"شخصية المساعد: {personality}"
            )

        if mode_name == "friendly":

            prompt_parts.append(
                "كن ودودًا ولطيفًا أثناء التفاعل."
            )

        elif mode_name == "active":

            prompt_parts.append(
                "كن متفاعلًا ونشيطًا في المحادثة."
            )

        elif mode_name == "fun":

            prompt_parts.append(
                "يمكنك استخدام المزاح الخفيف والمناسب."
            )

        elif mode_name == "professional":

            prompt_parts.append(
                "كن احترافيًا ودقيقًا ومباشرًا."
            )

        if advanced.get(
            "security",
            True,
        ):

            prompt_parts.append(
                "تجنب المحتوى الخطير أو غير المناسب."
            )

        return "\n".join(
            prompt_parts
        )

    # ========================================================
    # HTTP ERROR
    # ========================================================

    async def _read_error(
        self,
        response: aiohttp.ClientResponse,
    ) -> str:

        try:

            text = await response.text()

            if not text:

                return (
                    f"HTTP {response.status}"
                )

            return text[:3000]

        except Exception as exc:

            return (
                f"HTTP {response.status}; "
                f"failed to read response: {exc}"
            )

    # ========================================================
    # GOOGLE GEMINI
    # ========================================================

    async def _google(
        self,
        messages: list[Dict[str, str]],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:

        self.reload_keys()

        if not self.google_key:

            raise RuntimeError(
                "Google/Gemini API key is missing."
            )

        model = self.resolve_model(
            "google",
            model,
        )

        url = self.google_base_url.format(
            model=model
        )

        contents = []

        for message in messages:

            role = message.get(
                "role",
                "user",
            )

            text = _clean_text(
                message.get("content")
            )

            if not text:
                continue

            gemini_role = (
                "model"
                if role == "assistant"
                else "user"
            )

            contents.append(
                {
                    "role": gemini_role,
                    "parts": [
                        {
                            "text": text
                        }
                    ],
                }
            )

        if not contents:

            raise RuntimeError(
                "No messages were provided to Google."
            )

        payload = {
            "system_instruction": {
                "parts": [
                    {
                        "text": system_prompt
                    }
                ]
            },
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.google_key,
        }

        timeout = aiohttp.ClientTimeout(
            total=self.timeout
        )

        try:

            async with aiohttp.ClientSession(
                timeout=timeout
            ) as session:

                async with session.post(
                    url,
                    headers=headers,
                    json=payload,
                ) as response:

                    if response.status >= 400:

                        error_text = (
                            await self._read_error(
                                response
                            )
                        )

                        raise RuntimeError(
                            "Google API error "
                            f"{response.status}: "
                            f"{error_text}"
                        )

                    data = await response.json()

        except asyncio.TimeoutError:

            raise RuntimeError(
                "Google API request timed out."
            )

        except aiohttp.ClientError as exc:

            raise RuntimeError(
                f"Google network error: {exc}"
            )

        candidates = data.get(
            "candidates",
            [],
        )

        if not candidates:

            feedback = data.get(
                "promptFeedback"
            )

            if feedback:

                raise RuntimeError(
                    "Google returned no candidates: "
                    + json.dumps(
                        feedback,
                        ensure_ascii=False,
                    )
                )

            raise RuntimeError(
                "Google returned no candidates."
            )

        content = candidates[0].get(
            "content",
            {}
        )

        parts = content.get(
            "parts",
            []
        )

        texts = []

        for part in parts:

            text = part.get(
                "text"
            )

            if text:

                texts.append(
                    str(text)
                )

        result = "".join(
            texts
        ).strip()

        if not result:

            raise RuntimeError(
                "Google returned an empty response."
            )

        return result

    # ========================================================
    # OPENAI
    # ========================================================

    async def _openai(
        self,
        messages: list[Dict[str, str]],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:

        self.reload_keys()

        if not self.openai_key:

            raise RuntimeError(
                "OpenAI API key is missing."
            )

        model = self.resolve_model(
            "openai",
            model,
        )

        input_messages = []

        for message in messages:

            role = message.get(
                "role",
                "user",
            )

            content = _clean_text(
                message.get("content")
            )

            if not content:
                continue

            if role not in (
                "user",
                "assistant",
            ):
                continue

            input_messages.append(
                {
                    "role": role,
                    "content": content,
                }
            )

        if not input_messages:

            raise RuntimeError(
                "No messages were provided to OpenAI."
            )

        payload = {
            "model": model,
            "instructions": system_prompt,
            "input": input_messages,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": (
                f"Bearer {self.openai_key}"
            ),
        }

        timeout = aiohttp.ClientTimeout(
            total=self.timeout
        )

        try:

            async with aiohttp.ClientSession(
                timeout=timeout
            ) as session:

                async with session.post(
                    self.openai_url,
                    headers=headers,
                    json=payload,
                ) as response:

                    if response.status >= 400:

                        error_text = (
                            await self._read_error(
                                response
                            )
                        )

                        raise RuntimeError(
                            "OpenAI API error "
                            f"{response.status}: "
                            f"{error_text}"
                        )

                    data = await response.json()

        except asyncio.TimeoutError:

            raise RuntimeError(
                "OpenAI API request timed out."
            )

        except aiohttp.ClientError as exc:

            raise RuntimeError(
                f"OpenAI network error: {exc}"
            )

        output_text = data.get(
            "output_text"
        )

        if output_text:

            result = str(
                output_text
            ).strip()

            if result:
                return result

        outputs = data.get(
            "output",
            []
        )

        texts = []

        for output in outputs:

            for content in output.get(
                "content",
                []
            ):

                text = content.get(
                    "text"
                )

                if text:

                    texts.append(
                        str(text)
                    )

        result = "".join(
            texts
        ).strip()

        if not result:

            raise RuntimeError(
                "OpenAI returned an empty response."
            )

        return result

    # ========================================================
    # ANTHROPIC
    # ========================================================

    async def _anthropic(
        self,
        messages: list[Dict[str, str]],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:

        self.reload_keys()

        if not self.anthropic_key:

            raise RuntimeError(
                "Anthropic API key is missing."
            )

        model = self.resolve_model(
            "anthropic",
            model,
        )

        anthropic_messages = []

        for message in messages:

            role = message.get(
                "role",
                "user",
            )

            if role not in (
                "user",
                "assistant",
            ):
                continue

            content = _clean_text(
                message.get("content")
            )

            if not content:
                continue

            anthropic_messages.append(
                {
                    "role": role,
                    "content": content,
                }
            )

        if not anthropic_messages:

            raise RuntimeError(
                "No messages were provided to Anthropic."
            )

        payload = {
            "model": model,
            "system": system_prompt,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.anthropic_key,
            "anthropic-version": "2023-06-01",
        }

        timeout = aiohttp.ClientTimeout(
            total=self.timeout
        )

        try:

            async with aiohttp.ClientSession(
                timeout=timeout
            ) as session:

                async with session.post(
                    self.anthropic_url,
                    headers=headers,
                    json=payload,
                ) as response:

                    if response.status >= 400:

                        error_text = (
                            await self._read_error(
                                response
                            )
                        )

                        raise RuntimeError(
                            "Anthropic API error "
                            f"{response.status}: "
                            f"{error_text}"
                        )

                    data = await response.json()

        except asyncio.TimeoutError:

            raise RuntimeError(
                "Anthropic API request timed out."
            )

        except aiohttp.ClientError as exc:

            raise RuntimeError(
                f"Anthropic network error: {exc}"
            )

        content = data.get(
            "content",
            []
        )

        texts = []

        for item in content:

            if item.get("type") == "text":

                text = item.get(
                    "text"
                )

                if text:

                    texts.append(
                        str(text)
                    )

        result = "".join(
            texts
        ).strip()

        if not result:

            raise RuntimeError(
                "Anthropic returned an empty response."
            )

        return result

    # ========================================================
    # PROVIDER REQUEST
    # ========================================================

    async def request(
        self,
        provider: str,
        model: str,
        messages: list[Dict[str, str]],
        system_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:

        provider = _clean_text(
            provider
        ).lower()

        if provider == "google":

            return await self._google(
                messages=messages,
                system_prompt=system_prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        if provider == "openai":

            return await self._openai(
                messages=messages,
                system_prompt=system_prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        if provider == "anthropic":

            return await self._anthropic(
                messages=messages,
                system_prompt=system_prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        raise RuntimeError(
            f"Unknown AI provider: {provider}"
        )

    # ========================================================
    # FALLBACK
    # ========================================================

    async def request_with_fallback(
        self,
        primary_provider: str,
        primary_model: str,
        messages: list[Dict[str, str]],
        system_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:

        self.reload_keys()

        primary_provider = _clean_text(
            primary_provider
        ).lower()

        if not primary_provider:

            primary_provider = DEFAULT_PROVIDER

        attempts = []

        primary_model = self.resolve_model(
            primary_provider,
            primary_model,
        )

        attempts.append(
            (
                primary_provider,
                primary_model,
            )
        )

        fallback_defaults = {
            "google": GOOGLE_DEFAULT_MODEL,
            "openai": OPENAI_DEFAULT_MODEL,
            "anthropic": ANTHROPIC_DEFAULT_MODEL,
        }

        for provider in (
            "google",
            "openai",
            "anthropic",
        ):

            if provider == primary_provider:
                continue

            attempts.append(
                (
                    provider,
                    self.resolve_model(
                        provider,
                        fallback_defaults[provider],
                    ),
                )
            )

        errors = []

        for provider, model in attempts:

            if provider == "google":

                if not self.google_key:

                    errors.append(
                        "google: API key missing"
                    )

                    continue

            elif provider == "openai":

                if not self.openai_key:

                    errors.append(
                        "openai: API key missing"
                    )

                    continue

            elif provider == "anthropic":

                if not self.anthropic_key:

                    errors.append(
                        "anthropic: API key missing"
                    )

                    continue

            print(
                "[AI] Trying provider="
                f"{provider} "
                f"model={model}"
            )

            try:

                result = await self.request(
                    provider=provider,
                    model=model,
                    messages=messages,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                print(
                    "[AI] Success: provider="
                    f"{provider} "
                    f"model={model}"
                )

                return result

            except Exception as exc:

                error_text = str(
                    exc
                )

                print(
                    "[AI] FAILED: provider="
                    f"{provider} "
                    f"model={model}"
                )

                print(
                    f"[AI] Error: {error_text}"
                )

                errors.append(
                    f"{provider}/{model}: "
                    f"{error_text}"
                )

        combined = "\n".join(
            f"- {error}"
            for error in errors
        )

        raise RuntimeError(
            "All AI providers failed:\n"
            + combined
        )

    # ========================================================
    # GENERATE
    #
    # Compatible with main.py:
    #
    # guild_id
    # channel_id
    # user_id
    # prompt
    # character
    # mode
    # provider
    # model
    # history_limit
    # max_tokens_override
    #
    # **kwargs protects against future optional arguments.
    # ========================================================

    async def generate(
        self,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        user_id: Optional[int] = None,
        prompt: str = "",
        character: Optional[Dict[str, Any]] = None,
        mode: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        history_limit: Optional[int] = None,
        max_tokens_override: Optional[int] = None,
        character_name: Optional[str] = None,
        **kwargs: Any,
    ) -> str:

        prompt = _clean_text(
            prompt
        )

        if not prompt:

            raise RuntimeError(
                "Empty prompt."
            )

        # ----------------------------------------------------
        # EXTRA ARGUMENT PROTECTION
        # ----------------------------------------------------

        if kwargs:

            print(
                "[AI] Ignoring unsupported optional "
                "arguments: "
                + ", ".join(
                    str(key)
                    for key in kwargs.keys()
                )
            )

        # ----------------------------------------------------
        # CHARACTER
        # ----------------------------------------------------

        if character is not None:

            character = self.row_to_dict(
                character
            )

        # If main.py already supplied the character,
        # DO NOT replace it with another character.

        if not character:

            try:

                if user_id is not None:

                    character = (
                        self.db.get_user_active_character(
                            user_id,
                            guild_id,
                        )
                    )

            except Exception as exc:

                print(
                    "[AI] User character lookup failed: "
                    f"{exc}"
                )

        if not character and guild_id is not None:

            try:

                character = (
                    self.db.get_active_character(
                        guild_id
                    )
                )

            except Exception as exc:

                print(
                    "[AI] Guild character lookup failed: "
                    f"{exc}"
                )

        if character:

            character = self.row_to_dict(
                character
            )

        if not character:

            character = {
                "name": (
                    character_name
                    or "مساعد MyAI"
                ),
                "type": "normal",
                "description": "",
                "personality": "",
            }

        # ----------------------------------------------------
        # MODE
        # ----------------------------------------------------

        if not mode:

            try:

                if guild_id is not None:

                    config = (
                        self.db.get_ai_config(
                            guild_id
                        )
                        or {}
                    )

                else:

                    config = {}

                mode = config.get(
                    "mode",
                    "normal",
                )

            except Exception as exc:

                print(
                    "[AI] Mode lookup failed: "
                    f"{exc}"
                )

                mode = "normal"

        mode_name = _clean_text(
            mode
        ).lower() or "normal"

        mode_config = self.get_mode(
            mode_name
        )

        # ----------------------------------------------------
        # ADVANCED SETTINGS
        # ----------------------------------------------------

        advanced = {}

        if guild_id is not None:

            try:

                advanced = (
                    self.db.get_ai_advanced_settings(
                        guild_id
                    )
                    or {}
                )

            except Exception as exc:

                print(
                    "[AI] Advanced settings lookup failed: "
                    f"{exc}"
                )

        # ----------------------------------------------------
        # PROVIDER
        # ----------------------------------------------------

        selected_provider = (
            _clean_text(
                provider
            ).lower()
            if provider
            else ""
        )

        if not selected_provider:

            selected_provider = (
                _clean_text(
                    character.get(
                        "provider"
                    )
                ).lower()
            )

        if not selected_provider:

            selected_provider = DEFAULT_PROVIDER

        # ----------------------------------------------------
        # MODEL
        # ----------------------------------------------------

        selected_model = (
            _clean_text(model)
            if model
            else _clean_text(
                character.get(
                    "model"
                )
            )
        )

        selected_model = self.resolve_model(
            selected_provider,
            selected_model,
        )

        # ----------------------------------------------------
        # HISTORY
        # ----------------------------------------------------

        if history_limit is None:

            history_limit = _safe_int(
                advanced.get(
                    "history",
                    20,
                ),
                20,
            )

        else:

            history_limit = _safe_int(
                history_limit,
                20,
            )

        if history_limit < 0:

            history_limit = 0

        if history_limit > 100:

            history_limit = 100

        history = []

        if (
            guild_id is not None
            and user_id is not None
            and history_limit > 0
        ):

            try:

                history = (
                    self.db.get_history(
                        guild_id=guild_id,
                        user_id=user_id,
                        limit=history_limit,
                    )
                    or []
                )

            except TypeError:

                try:

                    history = (
                        self.db.get_history(
                            guild_id,
                            user_id,
                            history_limit,
                        )
                        or []
                    )

                except Exception as exc:

                    print(
                        "[AI] History lookup failed: "
                        f"{exc}"
                    )

            except Exception as exc:

                print(
                    "[AI] History lookup failed: "
                    f"{exc}"
                )

        # ----------------------------------------------------
        # BUILD MESSAGES
        # ----------------------------------------------------

        messages = []

        for item in history:

            row = self.row_to_dict(
                item
            )

            role = _clean_text(
                row.get("role")
            ).lower()

            content = _clean_text(
                row.get("content")
                or row.get("message")
                or row.get("text")
            )

            if not content:
                continue

            if role not in (
                "user",
                "assistant",
            ):
                continue

            messages.append(
                {
                    "role": role,
                    "content": content,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": prompt,
            }
        )

        # ----------------------------------------------------
        # SYSTEM PROMPT
        # ----------------------------------------------------

        system_prompt = (
            self.build_system_prompt(
                character=character,
                mode=mode_name,
                advanced=advanced,
            )
        )

        # ----------------------------------------------------
        # TOKEN LIMIT
        # ----------------------------------------------------

        if max_tokens_override is not None:

            effective_max_tokens = _safe_int(
                max_tokens_override,
                1200,
            )

        else:

            effective_max_tokens = _safe_int(
                mode_config.get(
                    "max_tokens",
                    1200,
                ),
                1200,
            )

        if effective_max_tokens < 1:

            effective_max_tokens = 1

        # ----------------------------------------------------
        # GENERATION LOG
        # ----------------------------------------------------

        print(
            "[AI] ========================================"
        )

        print(
            "[AI] Generation request"
        )

        print(
            f"[AI] provider={selected_provider}"
        )

        print(
            f"[AI] model={selected_model}"
        )

        print(
            f"[AI] mode={mode_name}"
        )

        print(
            f"[AI] history_limit={history_limit}"
        )

        if channel_id is not None:

            print(
                f"[AI] channel_id={channel_id}"
            )

        print(
            f"[AI] max_tokens={effective_max_tokens}"
        )

        print(
            "[AI] ========================================"
        )

        # ----------------------------------------------------
        # CALL PROVIDER
        # ----------------------------------------------------

        try:

            result = (
                await self.request_with_fallback(
                    primary_provider=selected_provider,
                    primary_model=selected_model,
                    messages=messages,
                    system_prompt=system_prompt,
                    temperature=_safe_float(
                        mode_config.get(
                            "temperature",
                            0.7,
                        ),
                        0.7,
                    ),
                    max_tokens=effective_max_tokens,
                )
            )

        except Exception as exc:

            print(
                "[AI] ========================================"
            )

            print(
                "[AI] GENERATION FAILED"
            )

            print(
                f"[AI] {exc}"
            )

            print(
                "[AI] ========================================"
            )

            raise

        result = _clean_text(
            result
        )

        if not result:

            raise RuntimeError(
                "AI returned an empty response."
            )

        # ----------------------------------------------------
        # MEMORY
        #
        # IMPORTANT:
        # main.py already saves guild messages through
        # on_message. To avoid duplicating guild history,
        # only AIEngine handles memory for DM-style calls
        # where guild_id == 0.
        #
        # For guild calls, main.py remains the source that
        # records the Discord messages.
        # ----------------------------------------------------

        memory_enabled = advanced.get(
            "memory",
            True,
        )

        if (
            memory_enabled
            and guild_id == 0
            and user_id is not None
        ):

            try:

                self.db.add_message(
                    guild_id=0,
                    user_id=user_id,
                    role="user",
                    content=prompt,
                )

                self.db.add_message(
                    guild_id=0,
                    user_id=user_id,
                    role="assistant",
                    content=result,
                )

            except TypeError:

                try:

                    self.db.add_message(
                        0,
                        user_id,
                        "user",
                        prompt,
                    )

                    self.db.add_message(
                        0,
                        user_id,
                        "assistant",
                        result,
                    )

                except Exception as exc:

                    print(
                        "[AI] DM memory save failed: "
                        f"{exc}"
                    )

            except Exception as exc:

                print(
                    "[AI] DM memory save failed: "
                    f"{exc}"
                )

        return result

    # ========================================================
    # PROACTIVE GENERATION
    # ========================================================

    async def generate_proactive(
        self,
        guild_id: Optional[int] = None,
        user_id: Optional[int] = None,
        prompt: str = "",
        mode: Optional[str] = "active",
        provider: Optional[str] = None,
        model: Optional[str] = None,
        character_name: Optional[str] = None,
        character: Optional[Dict[str, Any]] = None,
        channel_id: Optional[int] = None,
        history_limit: Optional[int] = None,
        max_tokens_override: Optional[int] = None,
        **kwargs: Any,
    ) -> str:

        return await self.generate(
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            prompt=prompt,
            character=character,
            mode=mode or "active",
            provider=provider,
            model=model,
            character_name=character_name,
            history_limit=history_limit,
            max_tokens_override=max_tokens_override,
            **kwargs,
        )
