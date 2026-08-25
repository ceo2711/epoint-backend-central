from app.models.enums import ProductCode
from app.schemas.entitlements import entitlements_from_codes
from app.services.courses import CourseService
from app.services.entitlements import EntitlementService


class TestEntitlementsFromCodes:
    def test_empty(self):
        result = entitlements_from_codes(set())
        assert result.credit is False
        assert result.course is False
        assert result.mentorship is False

    def test_all_three(self):
        result = entitlements_from_codes(
            {ProductCode.CREDIT.value, ProductCode.COURSE.value, ProductCode.MENTORSHIP.value}
        )
        assert result.credit is True
        assert result.course is True
        assert result.mentorship is True

    def test_course_only(self):
        result = entitlements_from_codes({ProductCode.COURSE.value})
        assert result.credit is False
        assert result.course is True
        assert result.mentorship is False


class TestGrantIdempotent:
    def test_grant_skips_duplicate(self):
        from unittest.mock import MagicMock

        from app.models.client_entitlement import ClientEntitlement

        db = MagicMock()
        existing = ClientEntitlement(client_id=1, product_code="COURSE")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing
        db.execute.return_value = result_mock

        client = MagicMock()
        client.id = 1
        created = EntitlementService(db).grant(client, "COURSE")
        assert created is False
        db.add.assert_not_called()
