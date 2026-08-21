from unittest.mock import patch

from app.core.app_review import is_app_review_email


class TestAppReviewEmail:
    def test_matches_default_review_account(self):
        assert is_app_review_email("appreview@epoint.com") is True
        assert is_app_review_email("AppReview@epoint.com") is True

    def test_ignores_regular_clients(self):
        assert is_app_review_email("cliente@epoint.com") is False
        assert is_app_review_email(None) is False
        assert is_app_review_email("") is False

    def test_honors_custom_allowlist(self):
        with patch("app.core.app_review.get_settings") as get_settings:
            get_settings.return_value.app_review_emails = "reviewer@apple.test, other@test.com"
            assert is_app_review_email("reviewer@apple.test") is True
            assert is_app_review_email("appreview@epoint.com") is False
