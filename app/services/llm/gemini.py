import base64
import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class GeminiLLMService:
    """Servicio LangChain para Gemini Flash 2.5 — texto y visión de documentos.

    LangChain se importa solo al primer uso (análisis de documento), no al arrancar la API.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.model_name = settings.gemini_model
        self._api_key = settings.gemini_api_key or ""
        self._llm: Any = None

        if not self._api_key:
            logger.warning("GEMINI_API_KEY no configurada — el servicio LLM estará deshabilitado")

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    def _get_llm(self) -> Any:
        if not self._api_key:
            raise RuntimeError("Servicio Gemini no disponible: configure GEMINI_API_KEY")
        if self._llm is None:
            from langchain_google_genai import ChatGoogleGenerativeAI

            self._llm = ChatGoogleGenerativeAI(
                model=self.model_name,
                google_api_key=self._api_key,
                temperature=0.1,
            )
        return self._llm

    async def analyze_text(self, prompt: str) -> str:
        from langchain_core.messages import HumanMessage

        response = await self._get_llm().ainvoke([HumanMessage(content=prompt)])
        return self._extract_content(response.content)

    def analyze_document_sync(self, *, image_url: str, prompt: str) -> str:
        """Analiza documento desde URL (presigned S3) con visión multimodal."""
        from langchain_core.messages import HumanMessage

        with httpx.Client(timeout=60.0) as client:
            resp = client.get(image_url)
            resp.raise_for_status()
            media_type = resp.headers.get("content-type", "image/jpeg")
            content = resp.content

        return self.analyze_document_bytes(content=content, media_type=media_type, prompt=prompt)

    def analyze_document_bytes(self, *, content: bytes, media_type: str, prompt: str) -> str:
        from langchain_core.messages import HumanMessage

        b64 = base64.b64encode(content).decode("utf-8")
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
            ]
        )
        response = self._get_llm().invoke([message])
        return self._extract_content(response.content)

    def _extract_content(self, content: Any) -> str:
        if isinstance(content, list):
            return "".join(str(part) for part in content)
        return str(content)

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
