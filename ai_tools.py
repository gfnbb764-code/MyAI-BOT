from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from google import genai
from google.genai import types


# ============================================================
# CONFIG
# ============================================================

GOOGLE_API_KEY = (
    os.getenv("GOOGLE_API_KEY")
    or os.getenv("GEMINI_API_KEY")
    or ""
).strip()


DEFAULT_IMAGE_MODEL = os.getenv(
    "GOOGLE_IMAGE_MODEL",
    "gemini-3.1-flash-image-preview",
).strip()


DEFAULT_VIDEO_MODEL = os.getenv(
    "GOOGLE_VIDEO_MODEL",
    "veo-3.1-generate-preview",
).strip()


DEFAULT_SEARCH_MODEL = os.getenv(
    "GOOGLE_SEARCH_MODEL",
    "gemini-3.7-flash",
).strip()


DEFAULT_TEXT_MODEL = os.getenv(
    "GOOGLE_MODEL",
    "gemini-3.5-flash-lite",
).strip()


DEFAULT_TIMEOUT = int(
    os.getenv(
        "AI_TOOLS_TIMEOUT",
        "300",
    )
)


DEFAULT_VIDEO_TIMEOUT = int(
    os.getenv(
        "AI_VIDEO_TIMEOUT",
        "900",
    )
)


DEFAULT_OUTPUT_DIR = (
    os.getenv(
        "AI_OUTPUT_DIR",
        "generated_files",
    )
    .strip()
    or "generated_files"
)


MAX_FILE_BYTES = int(
    os.getenv(
        "AI_MAX_FILE_BYTES",
        str(8 * 1024 * 1024),
    )
)


SUPPORTED_FILE_EXTENSIONS = {
    "txt",
    "md",
    "json",
    "csv",
    "py",
    "html",
    "css",
    "js",
}


SUPPORTED_IMAGE_SIZES = {
    "1024x1024",
    "1536x1024",
    "1024x1536",
}


SUPPORTED_VIDEO_ASPECT_RATIOS = {
    "16:9",
    "9:16",
}


SUPPORTED_VIDEO_RESOLUTIONS = {
    "720p",
    "1080p",
    "4k",
}


SUPPORTED_VIDEO_DURATIONS = {
    "4",
    "6",
    "8",
}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def safe_int(
    value: Any,
    default: int,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:

    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default

    if minimum is not None:
        result = max(minimum, result)

    if maximum is not None:
        result = min(maximum, result)

    return result


def safe_float(
    value: Any,
    default: float,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:

    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default

    if minimum is not None:
        result = max(minimum, result)

    if maximum is not None:
        result = min(maximum, result)

    return result


def clean_text(
    value: Any
) -> str:

    return str(
        value or ""
    ).strip()


def sanitize_filename(
    name: str,
    fallback: str = "myai",
) -> str:

    name = clean_text(
        name
    )

    name = re.sub(
        r"[^a-zA-Z0-9_\-]+",
        "_",
        name,
    )

    name = name.strip(
        "_"
    )

    return name or fallback


def ensure_directory(
    path: Path
) -> None:

    path.mkdir(
        parents=True,
        exist_ok=True,
    )


def extract_text_from_response(
    response: Any
) -> str:

    text = getattr(
        response,
        "text",
        None,
    )

    if text:
        return str(
            text
        ).strip()

    parts = getattr(
        response,
        "parts",
        None,
    )

    if parts:

        collected = []

        for part in parts:

            part_text = getattr(
                part,
                "text",
                None,
            )

            if part_text:
                collected.append(
                    str(part_text)
                )

        if collected:
            return "".join(
                collected
            ).strip()

    return ""


def decode_image_part(
    part: Any
) -> Optional[bytes]:

    inline_data = getattr(
        part,
        "inline_data",
        None,
    )

    if inline_data is None:

        return None

    data = getattr(
        inline_data,
        "data",
        None,
    )

    if data is None:

        return None

    if isinstance(
        data,
        bytes,
    ):

        return data

    try:

        return bytes(
            data
        )

    except Exception:

        return None


def extract_urls_from_response(
    response: Any
) -> list[dict[str, str]]:

    sources = []

    seen = set()

    # --------------------------------------------------------
    # NEW SDK ANNOTATIONS
    # --------------------------------------------------------

    candidates = []

    response_text = getattr(
        response,
        "text",
        None,
    )

    if response_text:
        candidates.append(
            response_text
        )

    # --------------------------------------------------------
    # RESPONSE PARTS
    # --------------------------------------------------------

    parts = getattr(
        response,
        "parts",
        None,
    )

    if parts:

        for part in parts:

            grounding_metadata = getattr(
                part,
                "grounding_metadata",
                None,
            )

            if grounding_metadata:

                candidates.append(
                    grounding_metadata
                )

    # --------------------------------------------------------
    # RECURSIVE OBJECT WALK
    # --------------------------------------------------------

    def walk(
        obj: Any
    ):

        if obj is None:
            return

        if isinstance(
            obj,
            dict,
        ):

            for key, value in obj.items():

                key_lower = str(
                    key
                ).lower()

                if key_lower in {
                    "url",
                    "uri",
                }:

                    if isinstance(
                        value,
                        str,
                    ):

                        url = value.strip()

                        if (
                            url
                            and url not in seen
                            and (
                                url.startswith(
                                    "http://"
                                )
                                or url.startswith(
                                    "https://"
                                )
                            )
                        ):

                            seen.add(
                                url
                            )

                            sources.append({
                                "title": url,
                                "url": url,
                            })

                elif isinstance(
                    value,
                    (
                        dict,
                        list,
                        tuple,
                    )
                ):

                    walk(
                        value
                    )

            return

        if isinstance(
            obj,
            (
                list,
                tuple,
            )
        ):

            for item in obj:
                walk(item)

            return

        # ----------------------------------------------------
        # OBJECT ATTRIBUTES
        # ----------------------------------------------------

        for attribute in [
            "url",
            "uri",
            "title",
            "web",
            "web_url",
            "web_uri",
            "source",
            "sources",
            "grounding_metadata",
            "grounding_chunks",
            "grounding_supports",
        ]:

            try:

                value = getattr(
                    obj,
                    attribute,
                    None,
                )

            except Exception:

                value = None

            if value is None:
                continue

            if attribute in {
                "url",
                "uri",
                "web_url",
                "web_uri",
            }:

                if isinstance(
                    value,
                    str,
                ):

                    url = value.strip()

                    if (
                        url
                        and url not in seen
                        and (
                            url.startswith(
                                "http://"
                            )
                            or url.startswith(
                                "https://"
                            )
                        )
                    ):

                        seen.add(
                            url
                        )

                        title = "مصدر"

                        try:

                            title_value = getattr(
                                obj,
                                "title",
                                None,
                            )

                            if title_value:
                                title = str(
                                    title_value
                                )

                        except Exception:

                            pass

                        sources.append({
                            "title": title,
                            "url": url,
                        })

            else:

                walk(
                    value
                )

    walk(
        response
    )

    return sources[:20]


# ============================================================
# AI TOOLS
# ============================================================

class AITools:

    def __init__(
        self,
        ai_engine=None,
    ):

        self.ai = ai_engine

        self.google_api_key = (
            GOOGLE_API_KEY
        )

        self.image_model = (
            DEFAULT_IMAGE_MODEL
        )

        self.video_model = (
            DEFAULT_VIDEO_MODEL
        )

        self.search_model = (
            DEFAULT_SEARCH_MODEL
        )

        self.text_model = (
            DEFAULT_TEXT_MODEL
        )

        self.timeout = (
            DEFAULT_TIMEOUT
        )

        self.video_timeout = (
            DEFAULT_VIDEO_TIMEOUT
        )

        self.output_dir = Path(
            DEFAULT_OUTPUT_DIR
        )

        ensure_directory(
            self.output_dir
        )

        self._client = None

        self.reload_key()


    # ========================================================
    # GOOGLE CLIENT
    # ========================================================

    def reload_key(
        self
    ):

        self.google_api_key = (
            os.getenv("GOOGLE_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or ""
        ).strip()

        self._client = None

    def get_client(
        self
    ):

        self.reload_key()

        if not self.google_api_key:

            raise RuntimeError(
                "GOOGLE_API_KEY غير موجود."
            )

        if self._client is None:

            self._client = genai.Client(
                api_key=self.google_api_key
            )

        return self._client


    # ========================================================
    # IMAGE GENERATION
    # ========================================================

    async def generate_image(
        self,
        prompt: str,
        size: str = "1024x1024",
    ) -> bytes:

        prompt = clean_text(
            prompt
        )

        if not prompt:

            raise ValueError(
                "وصف الصورة فارغ."
            )

        if size not in (
            SUPPORTED_IMAGE_SIZES
        ):

            size = "1024x1024"

        client = self.get_client()

        def generate():

            # ------------------------------------------------
            # Nano Banana / Gemini Image
            # ------------------------------------------------

            config = types.GenerateContentConfig(
                response_modalities=[
                    "IMAGE"
                ],
            )

            return client.models.generate_content(
                model=self.image_model,
                contents=prompt,
                config=config,
            )

        response = await asyncio.to_thread(
            generate
        )

        parts = getattr(
            response,
            "parts",
            None
        )

        if not parts:

            raise RuntimeError(
                "Google Image API لم يرجع أجزاء."
            )

        # ----------------------------------------------------
        # FIND IMAGE
        # ----------------------------------------------------

        for part in parts:

            image_bytes = (
                decode_image_part(
                    part
                )
            )

            if image_bytes:

                return image_bytes

            # ------------------------------------------------
            # SDK helper: as_image()
            # ------------------------------------------------

            try:

                image = part.as_image()

            except Exception:

                image = None

            if image is not None:

                # --------------------------------------------
                # Try common SDK representations
                # --------------------------------------------

                image_bytes = getattr(
                    image,
                    "image_bytes",
                    None,
                )

                if image_bytes:

                    if isinstance(
                        image_bytes,
                        bytes,
                    ):

                        return image_bytes

                    return bytes(
                        image_bytes
                    )

                image_data = getattr(
                    image,
                    "_image_bytes",
                    None,
                )

                if image_data:

                    if isinstance(
                        image_data,
                        bytes,
                    ):

                        return image_data

                    return bytes(
                        image_data
                    )

        raise RuntimeError(
            "Google Image API لم يرجع صورة."
        )


    # ========================================================
    # WEB SEARCH
    # ========================================================

    async def web_search(
        self,
        query: str,
        context_size: str = "medium",
    ) -> dict[str, Any]:

        query = clean_text(
            query
        )

        if not query:

            raise ValueError(
                "استعلام البحث فارغ."
            )

        context_size = (
            clean_text(
                context_size
            )
            .lower()
        )

        if context_size not in {
            "low",
            "medium",
            "high",
        }:

            context_size = "medium"

        client = self.get_client()

        def search():

            config = types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        google_search=types.GoogleSearch()
                    )
                ],
            )

            return client.models.generate_content(
                model=self.search_model,
                contents=query,
                config=config,
            )

        response = await asyncio.to_thread(
            search
        )

        answer = extract_text_from_response(
            response
        )

        if not answer:

            answer = (
                "لم يرجع البحث إجابة نصية."
            )

        sources = (
            extract_urls_from_response(
                response
            )
        )

        return {
            "text": answer,
            "sources": sources,
        }


    # ========================================================
    # VIDEO GENERATION
    # ========================================================

    async def create_video(
        self,
        prompt: str,
        seconds: str = "8",
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
    ) -> bytes:

        prompt = clean_text(
            prompt
        )

        if not prompt:

            raise ValueError(
                "وصف الفيديو فارغ."
            )

        if seconds not in (
            SUPPORTED_VIDEO_DURATIONS
        ):

            seconds = "8"

        if aspect_ratio not in (
            SUPPORTED_VIDEO_ASPECT_RATIOS
        ):

            aspect_ratio = "16:9"

        if resolution not in (
            SUPPORTED_VIDEO_RESOLUTIONS
        ):

            resolution = "720p"

        # ----------------------------------------------------
        # Current Veo restrictions
        # ----------------------------------------------------

        if resolution == "4k":

            # Keep it explicit rather than silently
            # producing something else.
            pass

        client = self.get_client()

        # ----------------------------------------------------
        # CREATE LONG RUNNING OPERATION
        # ----------------------------------------------------

        def create_operation():

            config = types.GenerateVideosConfig(
                aspect_ratio=aspect_ratio,
                resolution=resolution,
            )

            return client.models.generate_videos(
                model=self.video_model,
                prompt=prompt,
                config=config,
            )

        operation = await asyncio.to_thread(
            create_operation
        )

        started = (
            time.monotonic()
        )

        # ----------------------------------------------------
        # POLLING
        # ----------------------------------------------------

        while not getattr(
            operation,
            "done",
            False
        ):

            elapsed = (
                time.monotonic()
                - started
            )

            if elapsed >= self.video_timeout:

                raise TimeoutError(
                    "توليد الفيديو تجاوز الوقت المحدد."
                )

            await asyncio.sleep(
                10
            )

            def refresh():

                return client.operations.get(
                    operation
                )

            operation = await asyncio.to_thread(
                refresh
            )

        # ----------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------

        error = getattr(
            operation,
            "error",
            None
        )

        if error:

            raise RuntimeError(
                f"Google Veo error: {error}"
            )

        response = getattr(
            operation,
            "response",
            None
        )

        if response is None:

            raise RuntimeError(
                "Veo لم يرجع response."
            )

        generated_videos = getattr(
            response,
            "generated_videos",
            None
        )

        if not generated_videos:

            raise RuntimeError(
                "Veo لم يرجع فيديو."
            )

        video_entry = (
            generated_videos[0]
        )

        video_file = getattr(
            video_entry,
            "video",
            None
        )

        if video_file is None:

            raise RuntimeError(
                "لم يتم العثور على ملف الفيديو."
            )

        # ----------------------------------------------------
        # DOWNLOAD
        # ----------------------------------------------------

        temporary_path = (
            self.output_dir
            / f"_video_{int(time.time() * 1000)}.mp4"
        )

        def download():

            return client.files.download(
                file=video_file,
                destination=str(
                    temporary_path
                ),
            )

        await asyncio.to_thread(
            download
        )

        if not temporary_path.exists():

            raise RuntimeError(
                "تعذر تنزيل الفيديو الناتج."
            )

        data = (
            temporary_path.read_bytes()
        )

        try:

            temporary_path.unlink(
                missing_ok=True
            )

        except Exception:

            pass

        return data


    # ========================================================
    # FILE CREATION
    # ========================================================

    async def create_ai_file(
        self,
        user_id: int,
        prompt: str,
        extension: str,
        ai_generate=None,
        max_bytes: Optional[int] = None,
    ) -> Path:

        prompt = clean_text(
            prompt
        )

        if not prompt:

            raise ValueError(
                "طلب إنشاء الملف فارغ."
            )

        extension = (
            clean_text(
                extension
            )
            .lower()
            .lstrip(".")
        )

        if extension not in (
            SUPPORTED_FILE_EXTENSIONS
        ):

            raise ValueError(
                "نوع الملف غير مدعوم."
            )

        if max_bytes is None:

            max_bytes = (
                MAX_FILE_BYTES
            )

        # ----------------------------------------------------
        # Generate content
        # ----------------------------------------------------

        if ai_generate is not None:

            result = await ai_generate(
                (
                    f"أنشئ محتوى ملف "
                    f"{extension} حسب الطلب التالي.\n"
                    "أعد محتوى الملف فقط.\n"
                    "لا تضف ``` ولا شرحًا خارجيًا.\n\n"
                    f"الطلب:\n{prompt}"
                )
            )

        elif self.ai is not None:

            result = await self.ai.generate(
                guild_id=0,
                channel_id=0,
                user_id=user_id,
                prompt=(
                    f"أنشئ محتوى ملف "
                    f"{extension} حسب الطلب التالي.\n"
                    "أعد محتوى الملف فقط.\n"
                    "لا تستخدم Markdown fences.\n"
                    "لا تضف شرحًا خارج الملف.\n\n"
                    f"الطلب:\n{prompt}"
                ),
                provider="google",
                model=self.text_model,
                history_limit=0,
                max_tokens_override=4000,
            )

        else:

            raise RuntimeError(
                "AIEngine غير متوفر لإنشاء محتوى الملف."
            )

        content = clean_text(
            result
        )

        # ----------------------------------------------------
        # REMOVE CODE FENCES
        # ----------------------------------------------------

        content = re.sub(
            r"^```[a-zA-Z0-9_+#.-]*\s*\n",
            "",
            content
        )

        content = re.sub(
            r"\n```\s*$",
            "",
            content
        )

        content = content.strip()

        if not content:

            raise RuntimeError(
                "AI رجع ملفًا فارغًا."
            )

        # ----------------------------------------------------
        # JSON
        # ----------------------------------------------------

        if extension == "json":

            cleaned_json = content

            if cleaned_json.startswith(
                "```"
            ):

                cleaned_json = re.sub(
                    r"^```(?:json)?\s*",
                    "",
                    cleaned_json,
                    flags=re.IGNORECASE,
                )

                cleaned_json = re.sub(
                    r"\s*```$",
                    "",
                    cleaned_json,
                )

            try:

                parsed = json.loads(
                    cleaned_json
                )

            except json.JSONDecodeError as exc:

                raise ValueError(
                    "AI رجع JSON غير صالح."
                ) from exc

            content = json.dumps(
                parsed,
                ensure_ascii=False,
                indent=2,
            )

        # ----------------------------------------------------
        # CSV
        # ----------------------------------------------------

        elif extension == "csv":

            try:

                list(
                    csv.reader(
                        content.splitlines()
                    )
                )

            except Exception as exc:

                raise ValueError(
                    "الملف CSV غير صالح."
                ) from exc

        # ----------------------------------------------------
        # BYTES
        # ----------------------------------------------------

        raw = content.encode(
            "utf-8"
        )

        if len(raw) > max_bytes:

            raise ValueError(
                "الملف الناتج أكبر من الحد المسموح."
            )

        # ----------------------------------------------------
        # FILE NAME
        # ----------------------------------------------------

        safe_user = sanitize_filename(
            str(user_id),
            "user",
        )

        timestamp = int(
            time.time() * 1000
        )

        filename = (
            f"myai_"
            f"{safe_user}_"
            f"{timestamp}."
            f"{extension}"
        )

        path = (
            self.output_dir
            / filename
        )

        path.write_bytes(
            raw
        )

        return path


    # ========================================================
    # SAVE IMAGE
    # ========================================================

    async def save_image(
        self,
        image_bytes: bytes,
        user_id: int,
    ) -> Path:

        if not image_bytes:

            raise ValueError(
                "الصورة فارغة."
            )

        timestamp = int(
            time.time() * 1000
        )

        filename = (
            f"myai_"
            f"{sanitize_filename(str(user_id), 'user')}_"
            f"{timestamp}.png"
        )

        path = (
            self.output_dir
            / filename
        )

        path.write_bytes(
            image_bytes
        )

        return path


    # ========================================================
    # SAVE VIDEO
    # ========================================================

    async def save_video(
        self,
        video_bytes: bytes,
        user_id: int,
    ) -> Path:

        if not video_bytes:

            raise ValueError(
                "الفيديو فارغ."
            )

        timestamp = int(
            time.time() * 1000
        )

        filename = (
            f"myai_"
            f"{sanitize_filename(str(user_id), 'user')}_"
            f"{timestamp}.mp4"
        )

        path = (
            self.output_dir
            / filename
        )

        path.write_bytes(
            video_bytes
        )

        return path


    # ========================================================
    # CLEAN FILE
    # ========================================================

    async def delete_file(
        self,
        path: Optional[Path],
    ) -> bool:

        if path is None:

            return False

        try:

            path = Path(
                path
            )

            if path.exists():

                path.unlink()

            return True

        except Exception:

            return False
