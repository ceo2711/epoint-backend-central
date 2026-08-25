"""Catálogo de cursos, upload firmado a Bucketeer y playback."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.constants.course_catalog import default_course_catalog
from app.models.course import Course, CourseLesson, CourseLessonProgress, CourseModule
from app.models.user import User
from app.schemas.course import (
    CourseDetailResponse,
    CourseLessonBrief,
    CourseListItem,
    CourseModuleBrief,
    LessonPlayResponse,
    LessonUploadUrlResponse,
)
from app.services.entitlements import EntitlementService
from app.services.storage import get_storage_provider

logger = logging.getLogger(__name__)

VIDEO_MIME_TYPES = frozenset({"video/mp4"})
PLAY_URL_TTL = 4 * 3600
UPLOAD_URL_TTL = 3600


class CourseService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._storage = None

    @property
    def storage(self):
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage

    def ensure_default_course(self) -> Course:
        catalog = default_course_catalog()
        course = self.db.execute(
            select(Course).where(Course.code == catalog["code"])
        ).scalar_one_or_none()
        if course is not None:
            existing_lessons = self.db.execute(
                select(func.count()).select_from(CourseLesson).join(CourseModule).where(
                    CourseModule.course_id == course.id
                )
            ).scalar_one()
            if int(existing_lessons) > 0:
                return course
        if course is None:
            course = Course(
                code=catalog["code"],
                title=catalog["title"],
                description=catalog.get("description"),
                is_published=True,
            )
            self.db.add(course)
            self.db.flush()
        for module_data in catalog["modules"]:
            module = CourseModule(
                course_id=course.id,
                position=int(module_data["position"]),
                number=str(module_data["number"]),
                title=module_data["title"],
                goal=module_data.get("goal"),
            )
            self.db.add(module)
            self.db.flush()
            for lesson_data in module_data["lessons"]:
                self.db.add(
                    CourseLesson(
                        module_id=module.id,
                        position=int(lesson_data["position"]),
                        title=lesson_data["title"],
                        duration_label=lesson_data.get("duration_label"),
                        objective=lesson_data.get("objective"),
                    )
                )
        self.db.commit()
        self.db.refresh(course)
        return course

    def list_courses(self) -> list[CourseListItem]:
        self.ensure_default_course()
        courses = self.db.execute(select(Course).order_by(Course.id)).scalars().all()
        items: list[CourseListItem] = []
        for course in courses:
            module_count = self.db.execute(
                select(func.count()).select_from(CourseModule).where(CourseModule.course_id == course.id)
            ).scalar_one()
            lesson_count = self.db.execute(
                select(func.count())
                .select_from(CourseLesson)
                .join(CourseModule)
                .where(CourseModule.course_id == course.id)
            ).scalar_one()
            videos_ready = self.db.execute(
                select(func.count())
                .select_from(CourseLesson)
                .join(CourseModule)
                .where(
                    CourseModule.course_id == course.id,
                    CourseLesson.storage_key.is_not(None),
                )
            ).scalar_one()
            items.append(
                CourseListItem(
                    id=course.id,
                    code=course.code,
                    title=course.title,
                    description=course.description,
                    is_published=course.is_published,
                    module_count=int(module_count),
                    lesson_count=int(lesson_count),
                    videos_ready=int(videos_ready),
                )
            )
        return items

    def get_course(self, course_id: int) -> Course:
        course = (
            self.db.execute(
                select(Course)
                .options(joinedload(Course.modules).joinedload(CourseModule.lessons))
                .where(Course.id == course_id)
            )
            .unique()
            .scalar_one_or_none()
        )
        if course is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curso no encontrado")
        return course

    def default_published_course(self) -> Course:
        self.ensure_default_course()
        course = (
            self.db.execute(
                select(Course)
                .options(joinedload(Course.modules).joinedload(CourseModule.lessons))
                .where(Course.is_published.is_(True))
                .order_by(Course.id)
                .limit(1)
            )
            .unique()
            .scalar_one_or_none()
        )
        if course is None:
            raise HTTPException(status_code=404, detail="No hay un curso publicado")
        return course

    def to_detail(
        self,
        course: Course,
        *,
        client_id: int | None = None,
        include_filenames: bool = False,
    ) -> CourseDetailResponse:
        completed: set[int] = set()
        if client_id:
            rows = self.db.execute(
                select(CourseLessonProgress.lesson_id).where(
                    CourseLessonProgress.client_id == client_id,
                    CourseLessonProgress.completed_at.is_not(None),
                )
            ).scalars().all()
            completed = {int(item) for item in rows}

        modules: list[CourseModuleBrief] = []
        for module in sorted(course.modules, key=lambda item: item.position):
            lessons: list[CourseLessonBrief] = []
            for lesson in sorted(module.lessons, key=lambda item: item.position):
                lessons.append(
                    CourseLessonBrief(
                        id=lesson.id,
                        position=lesson.position,
                        title=lesson.title,
                        duration_label=lesson.duration_label,
                        objective=lesson.objective,
                        has_video=bool(lesson.storage_key),
                        original_filename=lesson.original_filename if include_filenames else None,
                        completed=lesson.id in completed,
                    )
                )
            modules.append(
                CourseModuleBrief(
                    id=module.id,
                    position=module.position,
                    number=module.number,
                    title=module.title,
                    goal=module.goal,
                    lessons=lessons,
                )
            )
        return CourseDetailResponse(
            id=course.id,
            code=course.code,
            title=course.title,
            description=course.description,
            is_published=course.is_published,
            modules=modules,
        )

    def _get_lesson(self, lesson_id: int) -> CourseLesson:
        lesson = self.db.get(CourseLesson, lesson_id)
        if lesson is None:
            raise HTTPException(status_code=404, detail="Lección no encontrada")
        return lesson

    def request_upload_url(self, lesson_id: int, filename: str, content_type: str) -> LessonUploadUrlResponse:
        lesson = self._get_lesson(lesson_id)
        mime_type = self._resolve_video_mime(filename, content_type)
        module = self.db.get(CourseModule, lesson.module_id)
        if module is None:
            raise HTTPException(status_code=404, detail="Módulo no encontrado")
        key = self.storage.build_key(
            "courses",
            str(module.course_id),
            "lessons",
            str(lesson.id),
            f"{uuid.uuid4()}.mp4",
        )
        upload_url = self.storage.generate_upload_url(key, mime_type, expires_in=UPLOAD_URL_TTL)
        return LessonUploadUrlResponse(upload_url=upload_url, storage_key=key, content_type=mime_type)

    def confirm_upload(
        self,
        lesson_id: int,
        *,
        storage_key: str,
        original_filename: str,
        mime_type: str,
    ) -> CourseLesson:
        lesson = self._get_lesson(lesson_id)
        mime = self._resolve_video_mime(original_filename, mime_type)
        expected_prefix = self.storage.build_key("courses")
        if not storage_key.startswith(expected_prefix) or f"/lessons/{lesson.id}/" not in storage_key:
            raise HTTPException(status_code=400, detail="Clave de almacenamiento inválida")
        if not self.storage.object_exists(storage_key):
            raise HTTPException(status_code=400, detail="El video no se subió correctamente")
        old_key = lesson.storage_key
        lesson.storage_key = storage_key
        lesson.original_filename = original_filename
        lesson.mime_type = mime
        self.db.commit()
        if old_key and old_key != storage_key:
            try:
                self.storage.delete_object(old_key)
            except Exception:
                logger.warning("No se pudo borrar el video anterior %s", old_key)
        return lesson

    def delete_video(self, lesson_id: int) -> None:
        lesson = self._get_lesson(lesson_id)
        key = lesson.storage_key
        lesson.storage_key = None
        lesson.original_filename = None
        lesson.mime_type = None
        self.db.commit()
        if key:
            try:
                self.storage.delete_object(key)
            except Exception:
                logger.warning("No se pudo borrar el video %s", key)

    def play_url(self, lesson_id: int) -> LessonPlayResponse:
        lesson = self._get_lesson(lesson_id)
        if not lesson.storage_key:
            raise HTTPException(status_code=404, detail="Esta lección todavía no tiene video")
        url = self.storage.generate_download_url(lesson.storage_key, expires_in=PLAY_URL_TTL)
        return LessonPlayResponse(
            play_url=url,
            mime_type=lesson.mime_type or "video/mp4",
            title=lesson.title,
            expires_in=PLAY_URL_TTL,
        )

    def mark_complete(self, *, client_id: int, lesson_id: int) -> None:
        self._get_lesson(lesson_id)
        row = self.db.execute(
            select(CourseLessonProgress).where(
                CourseLessonProgress.client_id == client_id,
                CourseLessonProgress.lesson_id == lesson_id,
            )
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if row is None:
            self.db.add(
                CourseLessonProgress(client_id=client_id, lesson_id=lesson_id, completed_at=now)
            )
        elif row.completed_at is None:
            row.completed_at = now
        self.db.commit()

    def require_course_entitlement(self, user: User) -> int:
        if user.role.code != "CLIENT" or not user.client_id:
            raise HTTPException(status_code=403, detail="Acceso solo para clientes")
        flags = EntitlementService(self.db).entitlements_for_client(user.client_id)
        if not flags.course:
            raise HTTPException(status_code=403, detail="Este producto no está incluido en tu plan")
        return user.client_id

    @staticmethod
    def _resolve_video_mime(filename: str, content_type: str) -> str:
        mime = (content_type or "").split(";")[0].strip().lower()
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if mime in VIDEO_MIME_TYPES or ext == "mp4":
            return "video/mp4"
        raise HTTPException(status_code=400, detail="Solo se aceptan videos MP4")
