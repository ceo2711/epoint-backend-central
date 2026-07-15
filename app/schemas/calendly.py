from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, HttpUrl


class CalendlyConnectRequest(BaseModel):
    access_token: str = Field(min_length=10)
    scheduling_url: HttpUrl | None = None


class CalendlyConnectionResponse(BaseModel):
    connected: bool
    user_id: int | None = None
    calendly_user_name: str | None = None
    scheduling_url: str | None = None
    last_synced_at: datetime | None = None


class CalendlySalesRepItem(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    connected: bool
    scheduling_url: str | None = None
    last_synced_at: datetime | None = None


class CalendlyLinkedProspectBrief(BaseModel):
    id: int
    full_name: str
    email: str
    converted_client_id: int | None = None


class CalendlyEventResponse(BaseModel):
    id: int
    name: str
    status: str
    start_time: datetime
    end_time: datetime
    event_type_name: str | None = None
    event_type_uri: str | None = None
    invitee_name: str | None = None
    invitee_email: str | None = None
    invitee_comment: str | None = None
    location: str | None = None
    meeting_url: str | None = None
    prospect_id: int | None = None
    linked_prospect: CalendlyLinkedProspectBrief | None = None

    model_config = {"from_attributes": True}


class CalendlyQuestionAnswerRequest(BaseModel):
    question_uuid: str = Field(min_length=1)
    answer: str = Field(default="", max_length=2000)


class CalendlyEventCreateRequest(BaseModel):
    event_type_uri: str = Field(min_length=10)
    start_time: datetime
    invitee_name: str = Field(min_length=1, max_length=255)
    invitee_email: EmailStr
    invitee_comment: str | None = Field(default=None, max_length=2000)
    questions_and_answers: list[CalendlyQuestionAnswerRequest] = Field(default_factory=list)
    timezone: str | None = None


class CalendlyEventUpdateRequest(BaseModel):
    event_type_uri: str = Field(min_length=10)
    start_time: datetime
    invitee_name: str = Field(min_length=1, max_length=255)
    invitee_email: EmailStr
    invitee_comment: str | None = Field(default=None, max_length=2000)
    questions_and_answers: list[CalendlyQuestionAnswerRequest] = Field(default_factory=list)
    timezone: str | None = None


class CalendlyEventCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class CalendlyCustomQuestionResponse(BaseModel):
    uuid: str
    name: str
    type: str
    position: int
    required: bool
    enabled: bool
    answer_choices: list[str] | None = None
    include_other: bool | None = None


class CalendlyEventTypeResponse(BaseModel):
    uri: str
    name: str
    duration: int
    scheduling_url: str | None = None
    description: str | None = None
    custom_questions: list[CalendlyCustomQuestionResponse] = Field(default_factory=list)


class CalendlyAvailableTimeResponse(BaseModel):
    start_time: datetime
    status: str


class CalendlySyncResponse(BaseModel):
    synced_count: int
    last_synced_at: datetime
