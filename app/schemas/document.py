from pydantic import BaseModel, Field


class UploadUrlRequest(BaseModel):
    document_type: str
    filename: str
    content_type: str


class UploadUrlResponse(BaseModel):
    upload_url: str
    storage_key: str
    content_type: str


class ConfirmUploadRequest(BaseModel):
    document_type: str
    storage_key: str
    original_filename: str
    mime_type: str


class DocumentResponse(BaseModel):
    id: int
    type: str
    verification_status: str
    original_filename: str
    download_url: str | None = None
