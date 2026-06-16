import fitz

from app.services.document_media import (
    is_pdf_media_type,
    pdf_bytes_to_png_pages,
    prepare_vision_images,
)


def _sample_pdf_bytes(*texts: str) -> bytes:
    doc = fitz.open()
    try:
        for text in texts:
            page = doc.new_page()
            page.insert_text((72, 72), text)
        return doc.tobytes()
    finally:
        doc.close()


def test_is_pdf_media_type():
    assert is_pdf_media_type("application/pdf")
    assert is_pdf_media_type("application/pdf; charset=binary")
    assert not is_pdf_media_type("image/png")


def test_pdf_bytes_to_png_pages():
    pdf_bytes = _sample_pdf_bytes("Page one", "Page two")
    pages = pdf_bytes_to_png_pages(pdf_bytes, max_pages=5)
    assert len(pages) == 2
    assert pages[0].startswith(b"\x89PNG\r\n\x1a\n")


def test_prepare_vision_images_for_pdf():
    pdf_bytes = _sample_pdf_bytes("SSN document")
    images = prepare_vision_images(pdf_bytes, "application/pdf")
    assert len(images) == 1
    assert images[0][1] == "image/png"


def test_prepare_vision_images_for_image():
    png_bytes = pdf_bytes_to_png_pages(_sample_pdf_bytes("Only page"))[0]
    images = prepare_vision_images(png_bytes, "image/png")
    assert images == [(png_bytes, "image/png")]
