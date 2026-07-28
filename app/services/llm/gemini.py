import logging
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.document_media import prepare_vision_images

logger = logging.getLogger(__name__)

# 503 (alta demanda) y 429 (rate limit) suelen ser temporales.
_RETRYABLE_STATUS_CODES = frozenset({429, 503})
_MAX_GENERATE_ATTEMPTS = 4
_RETRY_BASE_SECONDS = 1.5


class GeminiLLMService:
    """Servicio Gemini vía google-genai (SDK oficial actual).

    El SDK se importa solo al primer uso, no al arrancar la API.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.model_name = settings.gemini_model
        self._api_key = settings.gemini_api_key or ""
        self._client: Any = None

        if not self._api_key:
            logger.warning("GEMINI_API_KEY no configurada — el servicio LLM estará deshabilitado")

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> Any:
        if not self._api_key:
            raise RuntimeError("Servicio Gemini no disponible: configure GEMINI_API_KEY")
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    @staticmethod
    def _extract_text(response: Any) -> str:
        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text
        parts: list[str] = []
        for candidate in getattr(response, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                part_text = getattr(part, "text", None)
                if part_text:
                    parts.append(str(part_text))
        return "".join(parts)

    @staticmethod
    def _is_retryable_api_error(exc: BaseException) -> bool:
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if code in _RETRYABLE_STATUS_CODES:
            return True
        message = str(exc).lower()
        return "high demand" in message or "try again later" in message or "unavailable" in message

    def _generate_content_with_retry(self, *, contents: Any, config: Any) -> Any:
        """Llama a Gemini con reintentos ante 429/503 (demanda / rate limit)."""
        client = self._get_client()
        last_exc: BaseException | None = None
        for attempt in range(1, _MAX_GENERATE_ATTEMPTS + 1):
            try:
                return client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=config,
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= _MAX_GENERATE_ATTEMPTS or not self._is_retryable_api_error(exc):
                    raise
                delay = _RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "Gemini temporalmente no disponible (intento %s/%s): %s — reintento en %.1fs",
                    attempt,
                    _MAX_GENERATE_ATTEMPTS,
                    exc,
                    delay,
                )
                time.sleep(delay)
        assert last_exc is not None
        raise last_exc

    async def analyze_text(self, prompt: str) -> str:
        from google.genai import types

        client = self._get_client()
        response = await client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1),
        )
        return self._extract_text(response)

    async def chat(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        temperature: float = 0.35,
    ) -> str:
        from google.genai import types

        contents: list[types.Content] = []
        for item in messages:
            role = item.get("role")
            content = item.get("content", "")
            if role == "user":
                contents.append(
                    types.Content(role="user", parts=[types.Part.from_text(text=content)])
                )
            elif role == "assistant":
                contents.append(
                    types.Content(role="model", parts=[types.Part.from_text(text=content)])
                )

        if not contents:
            contents = [types.Content(role="user", parts=[types.Part.from_text(text="")])]

        client = self._get_client()
        response = await client.aio.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=temperature,
                system_instruction=system_prompt,
            ),
        )
        return self._extract_text(response)

    def analyze_document_sync(self, *, image_url: str, prompt: str) -> str:
        """Analiza documento desde URL (presigned S3) con visión multimodal."""
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(image_url)
            resp.raise_for_status()
            media_type = resp.headers.get("content-type", "image/jpeg")
            content = resp.content

        return self.analyze_document_bytes(content=content, media_type=media_type, prompt=prompt)

    def analyze_document_bytes(self, *, content: bytes, media_type: str, prompt: str) -> str:
        from google.genai import types

        vision_images = prepare_vision_images(content, media_type)
        if len(vision_images) > 1:
            prompt = (
                f"{prompt}\n\nThe document is a PDF with {len(vision_images)} page(s). "
                "Each image is one page. Analyze all pages together."
            )

        parts: list[types.Part] = [types.Part.from_text(text=prompt)]
        for image_bytes, image_media_type in vision_images:
            parts.append(
                types.Part.from_bytes(data=image_bytes, mime_type=image_media_type)
            )

        response = self._generate_content_with_retry(
            contents=types.Content(role="user", parts=parts),
            config=types.GenerateContentConfig(temperature=0.1),
        )
        return self._extract_text(response)

    async def health_check(self) -> dict:
        if not self.is_available:
            return {"status": "unavailable", "model": self.model_name}
        try:
            result = await self.analyze_text("Responde únicamente: OK")
            return {"status": "ok", "model": self.model_name, "response": result[:50]}
        except Exception as exc:
            logger.exception("Error en health check de Gemini")
            return {"status": "error", "detail": str(exc)}


_llm_service: GeminiLLMService | None = None


def get_llm_service() -> GeminiLLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = GeminiLLMService()
    return _llm_service
