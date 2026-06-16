"""Preparación de documentos (imagen o PDF) para análisis con visión IA."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PDF_MEDIA_TYPES = frozenset({"application/pdf", "application/x-pdf"})
IMAGE_MEDIA_TYPES = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
        "image/gif",
        "image/bmp",
        "image/tiff",
    }
)
DEFAULT_MAX_PDF_PAGES = 5
PDF_RENDER_SCALE = 2.0


def normalize_media_type(media_type: str) -> str:
    normalized = media_type.split(";")[0].strip().lower()
    if normalized == "image/jpg":
        return "image/jpeg"
    return normalized


def is_pdf_media_type(media_type: str) -> bool:
    return normalize_media_type(media_type) in PDF_MEDIA_TYPES


def is_image_media_type(media_type: str) -> bool:
    return normalize_media_type(media_type) in IMAGE_MEDIA_TYPES


def pdf_bytes_to_png_pages(content: bytes, *, max_pages: int = DEFAULT_MAX_PDF_PAGES) -> list[bytes]:
    import fitz

    doc = fitz.open(stream=content, filetype="pdf")
    try:
        if doc.page_count == 0:
            raise ValueError("El PDF no contiene páginas")

        pages: list[bytes] = []
        matrix = fitz.Matrix(PDF_RENDER_SCALE, PDF_RENDER_SCALE)
        for page_index in range(min(doc.page_count, max_pages)):
            pixmap = doc.load_page(page_index).get_pixmap(matrix=matrix, alpha=False)
            pages.append(pixmap.tobytes("png"))
        return pages
    finally:
        doc.close()


def prepare_vision_images(content: bytes, media_type: str) -> list[tuple[bytes, str]]:
    """Devuelve una o más imágenes listas para enviar al modelo de visión."""
    normalized = normalize_media_type(media_type)

    if is_pdf_media_type(normalized):
        png_pages = pdf_bytes_to_png_pages(content)
        logger.info("PDF convertido a %s página(s) para verificación IA", len(png_pages))
        return [(page, "image/png") for page in png_pages]

    if is_image_media_type(normalized):
        return [(content, normalized)]

    raise ValueError(f"Tipo de archivo no soportado para verificación IA: {media_type}")
