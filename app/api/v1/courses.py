from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, DbSession, require_permissions
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.course import (
    CourseDetailResponse,
    CourseListItem,
    LessonConfirmUploadRequest,
    LessonPlayResponse,
    LessonUploadUrlRequest,
    LessonUploadUrlResponse,
)
from app.services.courses import CourseService

router = APIRouter(prefix="/courses", tags=["Cursos"])
ManageUser = Annotated[User, Depends(require_permissions("courses:manage"))]


@router.get("", response_model=list[CourseListItem])
def list_courses(current_user: ManageUser, db: DbSession) -> list[CourseListItem]:
    del current_user
    return CourseService(db).list_courses()


@router.post("/lessons/{lesson_id}/upload-url", response_model=LessonUploadUrlResponse)
def request_lesson_upload_url(
    lesson_id: int,
    payload: LessonUploadUrlRequest,
    current_user: ManageUser,
    db: DbSession,
) -> LessonUploadUrlResponse:
    del current_user
    return CourseService(db).request_upload_url(lesson_id, payload.filename, payload.content_type)


@router.post("/lessons/{lesson_id}/confirm", response_model=MessageResponse)
def confirm_lesson_upload(
    lesson_id: int,
    payload: LessonConfirmUploadRequest,
    current_user: ManageUser,
    db: DbSession,
) -> MessageResponse:
    del current_user
    CourseService(db).confirm_upload(
        lesson_id,
        storage_key=payload.storage_key,
        original_filename=payload.original_filename,
        mime_type=payload.mime_type,
    )
    return MessageResponse(message="Video cargado")


@router.delete("/lessons/{lesson_id}/video", response_model=MessageResponse)
def delete_lesson_video(
    lesson_id: int,
    current_user: ManageUser,
    db: DbSession,
) -> MessageResponse:
    del current_user
    CourseService(db).delete_video(lesson_id)
    return MessageResponse(message="Video eliminado")


@router.get("/lessons/{lesson_id}/play", response_model=LessonPlayResponse)
def preview_lesson(
    lesson_id: int,
    current_user: ManageUser,
    db: DbSession,
) -> LessonPlayResponse:
    del current_user
    return CourseService(db).play_url(lesson_id)


@router.get("/{course_id}", response_model=CourseDetailResponse)
def get_course(
    course_id: int,
    current_user: ManageUser,
    db: DbSession,
) -> CourseDetailResponse:
    del current_user
    service = CourseService(db)
    course = service.get_course(course_id)
    return service.to_detail(course, include_filenames=True)
