import pytest
from fastapi import HTTPException

from app.constants.course_catalog import default_course_catalog
from app.services.courses import CourseService


class TestCourseCatalog:
    def test_twelve_modules_thirty_six_lessons(self):
        catalog = default_course_catalog()
        assert catalog["code"] == "CREDIT_MENTORSHIP"
        assert len(catalog["modules"]) == 12
        assert sum(len(module["lessons"]) for module in catalog["modules"]) == 36


class TestVideoMime:
    def test_accepts_mp4(self):
        assert CourseService._resolve_video_mime("clase.mp4", "video/mp4") == "video/mp4"
        assert CourseService._resolve_video_mime("clase.MP4", "application/octet-stream") == "video/mp4"

    def test_rejects_other_types(self):
        with pytest.raises(HTTPException) as exc:
            CourseService._resolve_video_mime("doc.pdf", "application/pdf")
        assert exc.value.status_code == 400
