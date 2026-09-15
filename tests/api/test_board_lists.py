from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.boards import _require_column_manager, create_list, delete_list, update_list
from app.schemas.board import ListCreate, ListUpdate
from app.schemas.common import MessageResponse


def _user(*, role: str, area: str | None = None):
    return SimpleNamespace(
        id=3,
        full_name="Onboarding Demo",
        role=SimpleNamespace(code=role),
        area=SimpleNamespace(code=area) if area else None,
        parent_user_id=None,
    )


def test_require_column_manager_allows_onboarding_and_advisor():
    _require_column_manager(_user(role="AREA_LEADER", area="ONBOARDING"))
    _require_column_manager(_user(role="ADVISOR"))


def test_require_column_manager_rejects_client():
    with pytest.raises(HTTPException) as exc:
        _require_column_manager(_user(role="CLIENT"))
    assert exc.value.status_code == 403


def test_create_list_endpoint_delegates_to_service():
    board = MagicMock()
    board.id = 5
    board.client_id = 9
    created = MagicMock()
    created.id = 44
    created.title = "Seguimiento extra"
    created.position = 13
    db = MagicMock()
    db.get.return_value = board
    actor = _user(role="ADVISOR", area="ASESORES")

    with (
        patch("app.api.v1.boards._require_staff_client_workspace"),
        patch("app.api.v1.boards.BoardService") as mock_service,
    ):
        mock_service.return_value.create_list.return_value = created
        response = create_list(
            board_id=5,
            payload=ListCreate(title="Seguimiento extra"),
            db=db,
            current_user=actor,
            merchant_id=None,
        )

    mock_service.return_value.create_list.assert_called_once_with(board=board, title="Seguimiento extra")
    assert response.id == 44
    assert response.is_system is False


def test_update_list_endpoint_delegates_to_service():
    board = MagicMock()
    board.client_id = 9
    board_list = MagicMock()
    board_list.board = board
    updated = MagicMock()
    updated.id = 44
    updated.title = "Seguimiento VIP"
    updated.position = 13
    db = MagicMock()
    db.get.return_value = board_list
    actor = _user(role="ADVISOR", area="ASESORES")

    with (
        patch("app.api.v1.boards._require_staff_client_workspace"),
        patch("app.api.v1.boards.BoardService") as mock_service,
    ):
        mock_service.return_value.update_list.return_value = updated
        response = update_list(
            list_id=44,
            payload=ListUpdate(title="Seguimiento VIP"),
            db=db,
            current_user=actor,
            merchant_id=None,
        )

    mock_service.return_value.update_list.assert_called_once_with(
        board_list=board_list,
        title="Seguimiento VIP",
    )
    assert response.id == 44
    assert response.title == "Seguimiento VIP"
    assert response.is_system is False


def test_delete_list_endpoint_delegates_to_service():
    board = MagicMock()
    board.client_id = 9
    board_list = MagicMock()
    board_list.board = board
    db = MagicMock()
    db.get.return_value = board_list
    actor = _user(role="AREA_LEADER", area="ONBOARDING")

    with (
        patch("app.api.v1.boards._require_staff_client_workspace"),
        patch("app.api.v1.boards.BoardService") as mock_service,
    ):
        response = delete_list(
            list_id=44,
            db=db,
            current_user=actor,
            merchant_id=None,
        )

    mock_service.return_value.delete_list.assert_called_once_with(board_list=board_list)
    assert isinstance(response, MessageResponse)
    assert response.message == "Columna eliminada"
