# -*- coding: utf-8 -*-
"""
GroqProvider - Groq API implementation with vision support.
Uses OpenAI-compatible API with Llama 4 Scout/Maverick models.
"""
import base64
import json
from pathlib import Path
from typing import List, Type, TypeVar

from groq import AsyncGroq
from loguru import logger
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_fixed

ResponseT = TypeVar("ResponseT", bound=BaseModel)


def extract_first_json_block(text: str) -> dict | None:
    """Extract the first JSON code block from text."""
    import re
    pattern = r"```json\s*([\s\S]*?)```"
    matches = re.findall(pattern, text)
    if matches:
        return json.loads(matches[0])
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return None


class GroqProvider:
    """
    Groq-based chat provider with vision support.
    Drop-in replacement for GeminiProvider.
    """

    def __init__(self, api_key: str, model: str = "meta-llama/llama-4-scout-17b-16e-instruct"):
        self._api_key = api_key
        self._model = model
        self._client: AsyncGroq | None = None
        self._last_response_text: str | None = None

    @property
    def client(self) -> AsyncGroq:
        if self._client is None:
            self._client = AsyncGroq(api_key=self._api_key)
        return self._client

    def _image_to_base64_url(self, file_path: Path) -> str:
        """Convert image file to base64 data URL."""
        data = file_path.read_bytes()
        b64 = base64.standard_b64encode(data).decode("utf-8")
        suffix = file_path.suffix.lower()
        media_type_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        media_type = media_type_map.get(suffix, "image/png")
        return f"data:{media_type};base64,{b64}"

    def _build_json_schema_from_pydantic(self, schema_class: Type[BaseModel]) -> str:
        schema = schema_class.model_json_schema()
        return json.dumps(schema, indent=2)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(3),
        before_sleep=lambda retry_state: logger.warning(
            f"Retry request ({retry_state.attempt_number}/3) - "
            f"Wait 3 seconds - Exception: {retry_state.outcome.exception()}"
        ),
    )
    async def generate_with_images(
        self,
        *,
        images: List[Path],
        response_schema: Type[ResponseT],
        user_prompt: str | None = None,
        description: str | None = None,
        **kwargs,
    ) -> ResponseT:
        """Generate content with image inputs using Groq vision."""
        # Build content parts
        content = []

        for img_path in images:
            if img_path and img_path.exists():
                content.append({
                    "type": "image_url",
                    "image_url": {"url": self._image_to_base64_url(img_path)},
                })

        # Build prompt with schema
        schema_json = self._build_json_schema_from_pydantic(response_schema)
        prompt_parts = []
        if user_prompt:
            prompt_parts.append(user_prompt)
        prompt_parts.append(
            f"\nRespond with ONLY valid JSON matching this schema:\n{schema_json}\n"
            f"Do NOT wrap in ```json``` code blocks. Output raw JSON only."
        )
        content.append({"type": "text", "text": "\n".join(prompt_parts)})

        messages = []
        if description:
            messages.append({"role": "system", "content": description})
        messages.append({"role": "user", "content": content})

        response = await self.client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=1024,
            temperature=0.1,
        )

        response_text = response.choices[0].message.content or ""
        self._last_response_text = response_text
        logger.debug(f"Groq response: {response_text[:200]}")

        # Parse JSON
        try:
            data = json.loads(response_text.strip())
            return response_schema(**data)
        except (json.JSONDecodeError, Exception):
            pass

        data = extract_first_json_block(response_text)
        if data:
            return response_schema(**data)

        raise ValueError(f"Failed to parse Groq response: {response_text[:200]}")

    def cache_response(self, path: Path) -> None:
        if not self._last_response_text:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"text": self._last_response_text}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Failed to cache response: {e}")
