from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMBase


class CardCommentCreate(BaseModel):
    body: str = Field(default="", max_length=10000)
    is_internal: bool = False


class BoardMentionableUserResponse(ORMBase):
    id: int
    full_name: str
    role_code: str


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
    mime_type: str | None = None
    download_url: str | None = None
    comment_id: int | None = None
    uploaded_by_name: str | None = None
    created_at: datetime | None = None


class CardStatusUpdate(BaseModel):
    status: str = Field(pattern="^(PENDIENTE|EN_PROGRESO|EN_REVISION|COMPLETADA)$")


class CardMoveUpdate(BaseModel):
    list_id: int = Field(gt=0)
    position: int = Field(ge=0)


class CardCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    position: int | None = Field(default=None, ge=0)


class CardUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description_md: str | None = None


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
