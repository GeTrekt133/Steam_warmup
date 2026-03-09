# -*- coding: utf-8 -*-
"""
ClaudeProvider - Anthropic Claude API implementation.
Replaces GeminiProvider for hcaptcha-challenger.
"""
import asyncio
import base64
import json
from pathlib import Path
from typing import List, Type, TypeVar

import anthropic
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
    # Try parsing raw JSON
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return None


class ClaudeProvider:
    """
    Claude-based chat provider implementation.
    Drop-in replacement for GeminiProvider.
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self._api_key = api_key
        self._model = model
        self._client: anthropic.AsyncAnthropic | None = None
        self._last_response_text: str | None = None

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client

    def _image_to_base64_part(self, file_path: Path) -> dict:
        """Convert image file to Claude API content block."""
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
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": b64,
            },
        }

    def _build_json_schema_from_pydantic(self, schema_class: Type[BaseModel]) -> str:
        """Build a JSON format instruction from pydantic schema."""
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
        """
        Generate content with image inputs using Claude.
        """
        # Build content blocks
        content = []

        # Add images
        for img_path in images:
            if img_path and img_path.exists():
                content.append(self._image_to_base64_part(img_path))

        # Build the user prompt with schema instructions
        schema_json = self._build_json_schema_from_pydantic(response_schema)
        prompt_parts = []
        if user_prompt:
            prompt_parts.append(user_prompt)
        prompt_parts.append(
            f"\nRespond with ONLY valid JSON matching this schema:\n{schema_json}\n"
            f"Do NOT wrap in ```json``` code blocks. Output raw JSON only."
        )

        content.append({"type": "text", "text": "\n".join(prompt_parts)})

        # Call Claude API
        message = await self.client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=description or "",
            messages=[{"role": "user", "content": content}],
        )

        # Extract text response
        response_text = ""
        for block in message.content:
            if block.type == "text":
                response_text += block.text

        self._last_response_text = response_text
        logger.debug(f"Claude response: {response_text[:200]}")

        # Parse JSON response
        # Try direct parse first
        try:
            data = json.loads(response_text.strip())
            return response_schema(**data)
        except (json.JSONDecodeError, Exception):
            pass

        # Try extracting from code block
        data = extract_first_json_block(response_text)
        if data:
            return response_schema(**data)

        raise ValueError(f"Failed to parse Claude response: {response_text[:200]}")

    def cache_response(self, path: Path) -> None:
        """Cache the last response to a file."""
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
