from pydantic import BaseModel, Field


class CourseLessonBrief(BaseModel):
    id: int
    position: int
    title: str
    duration_label: str | None = None
    objective: str | None = None
    has_video: bool = False
    original_filename: str | None = None
    completed: bool = False


class CourseModuleBrief(BaseModel):
    id: int
    position: int
    number: str
    title: str
    goal: str | None = None
    lessons: list[CourseLessonBrief]


class CourseDetailResponse(BaseModel):
    id: int
    code: str
    title: str
    description: str | None = None
    is_published: bool
    modules: list[CourseModuleBrief]


class CourseListItem(BaseModel):
    id: int
    code: str
    title: str
    description: str | None = None
    is_published: bool
    module_count: int
    lesson_count: int
    videos_ready: int


class LessonUploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=80)


class LessonUploadUrlResponse(BaseModel):
    upload_url: str
    storage_key: str
    content_type: str


class LessonConfirmUploadRequest(BaseModel):
    storage_key: str
    original_filename: str
    mime_type: str


class LessonPlayResponse(BaseModel):
    play_url: str
    mime_type: str
    title: str
    expires_in: int
