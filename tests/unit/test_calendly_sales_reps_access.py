from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.calendly.service import CalendlyService


def _user(*, role: str, area: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        role=SimpleNamespace(code=role),
        area=SimpleNamespace(code=area) if area else None,
        sede_id=1,
        id=9,
    )


def _service() -> CalendlyService:
    db = MagicMock()
    db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []
    return CalendlyService(db)


def test_advisor_cannot_list_sales_reps_for_client_filter() -> None:
    with pytest.raises(HTTPException) as exc:
        _service().list_sales_reps(_user(role="ADVISOR", area="ASESORES"))
    assert exc.value.status_code == 403


def test_onboarding_leader_can_list_sales_reps_for_client_filter() -> None:
    with patch("app.services.sede_scope.effective_sede_id", return_value=1):
        result = _service().list_sales_reps(_user(role="AREA_LEADER", area="ONBOARDING"))
    assert result == []


def test_client_cannot_list_sales_reps() -> None:
    with pytest.raises(HTTPException) as exc:
        _service().list_sales_reps(_user(role="CLIENT"))
    assert exc.value.status_code == 403
    assert "calendario" not in exc.value.detail.lower()
