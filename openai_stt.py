"""
OpenAI-compatible STT provider for VoiceCall.

This bypasses AstrBot's STT provider layer and calls a compatible
`/audio/transcriptions` endpoint directly.
"""

import logging
from pathlib import Path
from typing import Optional

import aiohttp

logger = logging.getLogger("voice_call.openai_stt")


class OpenAICompatibleSTTProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "whisper-1",
        language: str = "zh",
        prompt: str = "",
        timeout: int = 60,
    ):
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "https://api.openai.com/v1").strip()
        self.model = (model or "whisper-1").strip()
        self.language = (language or "").strip()
        self.prompt = (prompt or "").strip()
        self.timeout = int(timeout or 60)

    def meta(self):
        class _Meta:
            id = "openai_compatible_stt"

        return _Meta()

    async def get_text(self, audio_file_path: str) -> Optional[str]:
        if not self.api_key:
            logger.error("OpenAI STT API Key is not configured")
            return None
        if not self.model:
            logger.error("OpenAI STT model is not configured")
            return None

        path = Path(audio_file_path)
        if not path.is_file():
            logger.error("OpenAI STT audio file does not exist: %s", audio_file_path)
            return None

        data = aiohttp.FormData()
        data.add_field("model", self.model)
        data.add_field("response_format", "json")
        if self.language:
            data.add_field("language", self.language)
        if self.prompt:
            data.add_field("prompt", self.prompt)

        headers = {"Authorization": f"Bearer {self.api_key}"}
        with path.open("rb") as f:
            data.add_field(
                "file",
                f,
                filename=path.name,
                content_type=self._content_type(path.suffix),
            )
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self._transcription_url(), headers=headers, data=data) as resp:
                    body = await resp.text()
                    if resp.status >= 400:
                        logger.error("OpenAI STT request failed status=%s body=%s", resp.status, body[:500])
                        return None
                    try:
                        payload = await resp.json(content_type=None)
                    except Exception:
                        return body.strip() or None

        text = payload.get("text") if isinstance(payload, dict) else None
        return str(text).strip() if text else None

    def _transcription_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/audio/transcriptions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/audio/transcriptions"
        return f"{base}/v1/audio/transcriptions"

    @staticmethod
    def _content_type(suffix: str) -> str:
        return {
            ".wav": "audio/wav",
            ".webm": "audio/webm",
            ".ogg": "audio/ogg",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
        }.get(suffix.lower(), "application/octet-stream")
