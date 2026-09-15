from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.boards import _require_comment_editor, delete_comment, update_comment
from app.schemas.board import CardCommentUpdate
from app.schemas.common import MessageResponse


def _user(*, role: str, area: str | None = None):
    return SimpleNamespace(
        id=3,
        full_name="Onboarding Demo",
        role=SimpleNamespace(code=role),
        area=SimpleNamespace(code=area) if area else None,
        parent_user_id=None,
    )


def test_require_comment_editor_allows_onboarding_leader():
    _require_comment_editor(_user(role="AREA_LEADER", area="ONBOARDING"))


def test_require_comment_editor_rejects_client():
    with pytest.raises(HTTPException) as exc:
        _require_comment_editor(_user(role="CLIENT"))
    assert exc.value.status_code == 403


def test_update_comment_endpoint_delegates_to_service():
    card = MagicMock()
    card.id = 10
    comment = MagicMock()
    comment.card_id = 10
    comment.body = "Nuevo texto"
    comment.is_internal = False
    comment.author = SimpleNamespace(full_name="EPoint Corp")
    comment.created_at = datetime.now(timezone.utc)
    comment.updated_at = datetime.now(timezone.utc)
    comment.id = 22

    db = MagicMock()
    db.get.side_effect = lambda model, pk: card if pk == 10 else comment
    actor = _user(role="AREA_LEADER", area="ONBOARDING")
    payload = CardCommentUpdate(body="Nuevo texto")

    with (
        patch("app.api.v1.boards._get_card_client"),
        patch("app.api.v1.boards.BoardService") as mock_service,
    ):
        mock_service.return_value.update_comment.return_value = comment
        response = update_comment(
            card_id=10,
            comment_id=22,
            payload=payload,
            db=db,
            current_user=actor,
            merchant_id=None,
        )

    mock_service.return_value.update_comment.assert_called_once()
    assert response.body == "Nuevo texto"
    assert response.author_name == "EPoint Corp"


def test_update_comment_endpoint_404_when_comment_belongs_to_other_card():
    card = MagicMock()
    comment = MagicMock()
    comment.card_id = 99
    db = MagicMock()
    db.get.side_effect = lambda model, pk: card if pk == 10 else comment
    actor = _user(role="AREA_LEADER", area="ONBOARDING")

    with patch("app.api.v1.boards._get_card_client"):
        with pytest.raises(HTTPException) as exc:
            update_comment(
                card_id=10,
                comment_id=22,
                payload=CardCommentUpdate(body="x"),
                db=db,
                current_user=actor,
                merchant_id=None,
            )
    assert exc.value.status_code == 404


def test_delete_comment_endpoint_delegates_to_service():
    card = MagicMock()
    card.id = 10
    comment = MagicMock()
    comment.card_id = 10
    db = MagicMock()
    db.get.side_effect = lambda model, pk: card if pk == 10 else comment
    actor = _user(role="ADVISOR", area="ASESORES")

    with (
        patch("app.api.v1.boards._get_card_client"),
        patch("app.api.v1.boards.BoardService") as mock_service,
    ):
        response = delete_comment(
            card_id=10,
            comment_id=22,
            db=db,
            current_user=actor,
            merchant_id=None,
        )

    mock_service.return_value.delete_comment.assert_called_once_with(comment=comment)
    assert isinstance(response, MessageResponse)
    assert response.message == "Comentario eliminado"


def test_delete_comment_endpoint_rejects_client():
    with pytest.raises(HTTPException) as exc:
        _require_comment_editor(_user(role="CLIENT"))
    assert exc.value.status_code == 403
