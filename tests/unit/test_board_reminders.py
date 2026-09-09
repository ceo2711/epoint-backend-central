from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.board_reminders import (
    pending_board_cards,
    pending_task_labels,
    run_board_reminders,
)
from app.services.notifications.templates import board_reminder_email_body


def _card(title: str, status: str = "PENDIENTE"):
    return SimpleNamespace(title=title, status=status)


def _list(title: str, cards: list):
    return SimpleNamespace(title=title, cards=cards)


def test_pending_board_cards_skips_completed_column():
    board = SimpleNamespace(
        lists=[
            _list("Credenciales", [_card("Cargar usuario Experian"), _card("Listo", "COMPLETADA")]),
            _list("Completed", [_card("Ya hecha")]),
        ]
    )
    titles = [card.title for card in pending_board_cards(board)]
    assert titles == ["Cargar usuario Experian"]


def test_pending_board_cards_skips_optional_taxes():
    board = SimpleNamespace(
        lists=[
            _list("Ideas a realizar", [_card("Informe de Taxes")]),
            _list("Client TO DO", [_card("Reportes: Experian, Equifax y TransUnion")]),
        ]
    )
    titles = [card.title for card in pending_board_cards(board)]
    assert titles == ["Reportes: Experian, Equifax y TransUnion"]


def test_pending_board_cards_skips_review_and_empty_board():
    board = SimpleNamespace(
        lists=[_list("Client TO DO", [_card("Reporte mensual", "EN_REVISION")])]
    )
    assert pending_board_cards(board) == []
    assert pending_board_cards(None) == []


def test_pending_task_labels_caps_long_lists():
    cards = [_card(f"Tarea {index}") for index in range(8)]
    labels = pending_task_labels(cards, limit=3)
    assert labels[:3] == ["Tarea 0", "Tarea 1", "Tarea 2"]
    assert labels[-1] == "y 5 tarea(s) más"


def test_board_reminder_email_mentions_board_and_tasks():
    body = board_reminder_email_body(
        first_name="Ana",
        pending_items=["Cargar credenciales", "Llenar reporte"],
        board_url="https://app.epoint.test/portal/tablero",
    )
    assert "Ana" in body
    assert "Cargar credenciales" in body
    assert "tablero" in body.lower()
    assert "https://app.epoint.test/portal/tablero" in body
    assert "tienes" in body.lower() or "ingresa" in body.lower()
    assert "tenés" not in body.lower()
    assert "entrá" not in body.lower()


def test_board_reminders_skip_without_board_access():
    client = SimpleNamespace(
        id=1,
        email="ana@example.com",
        first_name="Ana",
        documents=[],
        board=SimpleNamespace(lists=[_list("Client TO DO", [_card("Reporte")])]),
        last_board_reminder_at=None,
    )
    db = MagicMock()
    db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = [client]

    with (
        patch("app.services.board_reminders.client_has_board_access", return_value=False),
        patch("app.services.board_reminders.send_board_reminder_email") as send,
    ):
        summary = run_board_reminders(db)

    send.assert_not_called()
    assert summary["skipped"] == 1
    assert summary["sent"] == 0


def test_board_reminders_skip_within_cooldown():
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    client = SimpleNamespace(
        id=1,
        email="ana@example.com",
        first_name="Ana",
        documents=[object()],
        board=SimpleNamespace(lists=[_list("Client TO DO", [_card("Reporte")])]),
        last_board_reminder_at=recent,
    )
    db = MagicMock()
    db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = [client]

    with (
        patch("app.services.board_reminders.client_has_board_access", return_value=True),
        patch("app.services.board_reminders.send_board_reminder_email") as send,
    ):
        summary = run_board_reminders(db)

    send.assert_not_called()
    assert summary["skipped"] == 1


def test_board_reminders_skip_recently_created_without_prior_send():
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    client = SimpleNamespace(
        id=1,
        email="ana@example.com",
        first_name="Ana",
        documents=[object()],
        board=SimpleNamespace(lists=[_list("Client TO DO", [_card("Reporte")])]),
        last_board_reminder_at=None,
        approved_at=recent,
        created_at=recent,
    )
    db = MagicMock()
    db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = [client]

    with (
        patch("app.services.board_reminders.client_has_board_access", return_value=True),
        patch("app.services.board_reminders.send_board_reminder_email") as send,
        patch(
            "app.services.board_reminders.get_settings",
            return_value=SimpleNamespace(
                board_reminder_cooldown_hours=2160,
                portal_board_url="https://portal.example/tablero",
                notifications_dry_run=True,
            ),
        ),
    ):
        summary = run_board_reminders(db)

    send.assert_not_called()
    assert summary["skipped"] == 1


def test_board_reminders_send_when_board_has_pending_tasks():
    old = datetime.now(timezone.utc) - timedelta(days=100)
    client = SimpleNamespace(
        id=4,
        email="ana@example.com",
        first_name="Ana",
        documents=[object()],
        board=SimpleNamespace(
            lists=[_list("Credenciales", [_card("Cargar usuario Experian")])]
        ),
        last_board_reminder_at=old,
    )
    db = MagicMock()
    db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = [client]

    with (
        patch("app.services.board_reminders.client_has_board_access", return_value=True),
        patch("app.services.board_reminders.send_board_reminder_email", return_value=True) as send,
    ):
        summary = run_board_reminders(db)

    send.assert_called_once()
    assert summary["sent"] == 1
    assert client.last_board_reminder_at is not None
