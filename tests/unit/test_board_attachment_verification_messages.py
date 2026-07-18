from app.services.board_attachment_verification_messages import build_board_rejection_messages
from app.services.board_attachment_verification_rules import CREDIT_BUREAU_REPORTS


def test_rejection_message_for_outdated_report_mentions_15_days():
    messages = build_board_rejection_messages(
        {
            "is_readable": True,
            "is_complete": True,
            "document_type_matches": True,
            "name_matches": True,
            "is_recent": False,
            "report_date": "2026-01-01",
        },
        attachment_kind=CREDIT_BUREAU_REPORTS,
        client_name="Jane Doe",
    )
    assert len(messages) == 1
    assert "15 days" in messages[0]["en"]
    assert "15 días" in messages[0]["es"]
    assert "2026-01-01" in messages[0]["en"]
