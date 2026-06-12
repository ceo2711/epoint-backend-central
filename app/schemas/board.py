from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMBase


class CardCommentCreate(BaseModel):
    body: str = Field(min_length=1)
    is_internal: bool = False


class CardCommentResponse(ORMBase):
    id: int
    body: str
    is_internal: bool
    author_name: str
    created_at: datetime


class CardAttachmentResponse(ORMBase):
    id: int
    type: str
    original_filename: str
    download_url: str | None = None


class CardStatusUpdate(BaseModel):
    status: str = Field(pattern="^(PENDIENTE|EN_PROGRESO|EN_REVISION|COMPLETADA)$")


class CardResultUpdate(BaseModel):
    client_result_text: str | None = None


class CredentialSubmit(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class BoardCardResponse(ORMBase):
    id: int
    title: str
    description_md: str | None
    instructions_md: str | None
    external_links: str | None
    status: str
    position: int
    requires_credentials: bool
    requires_file_upload: bool
    client_result_text: str | None
    comments: list[CardCommentResponse] = []
    attachments: list[CardAttachmentResponse] = []
    has_credentials: bool = False


class BoardListResponse(ORMBase):
    id: int
    title: str
    position: int
    cards: list[BoardCardResponse] = []


class BoardResponse(ORMBase):
    id: int
    client_id: int
    template_code: str
    lists: list[BoardListResponse] = []
