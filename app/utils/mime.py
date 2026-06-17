ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}

MIME_BY_EXTENSION = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def resolve_content_type(content_type: str, filename: str) -> str:
    normalized = content_type.split(";")[0].strip().lower()
    if normalized in ALLOWED_MIME_TYPES:
        return "image/jpeg" if normalized == "image/jpg" else normalized
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return MIME_BY_EXTENSION.get(ext, normalized)
