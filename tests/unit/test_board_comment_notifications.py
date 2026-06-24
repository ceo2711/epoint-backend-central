from unittest.mock import MagicMock, patch

from app.services.boards import BoardService


@patch("app.services.clients.ClientService.validate_mention_user_ids")
def test_mentioned_onboarding_manager_is_not_filtered_from_recipients(mock_validate_mentions):
    service = BoardService(MagicMock())

    author = MagicMock()
    author.id = 1
    author.role.code = "ADVISOR"

    onboarding = MagicMock()
    onboarding.id = 10
    onboarding.role.code = "ONBOARDING_MANAGER"

    advisor = MagicMock()
    advisor.id = 20
    advisor.role.code = "ADVISOR"

    card = MagicMock()
    card.id = 5
    card.title = "Tarea demo"

    client = MagicMock()
    client.id = 99

    mock_validate_mentions.return_value = [onboarding]
    service._comment_notification_recipients = MagicMock(return_value=[advisor])
    service.notifications = MagicMock()

    service._notify_comment(
        card=card,
        author=author,
        client=client,
        body="@[Onboarding](mention:10) revisá esto",
        is_internal=False,
    )

    notified_users = service.notifications.notify.call_args.kwargs["users"]
    notified_ids = {user.id for user in notified_users}
    assert 10 in notified_ids
    assert 20 in notified_ids
