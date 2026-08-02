"""Validación de vínculo Calendly ↔ prospecto del mismo vendedor."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services.prospects import ProspectService


def test_link_calendly_rejects_mismatched_sales_rep():
    db = MagicMock()
    prospect = SimpleNamespace(
        id=1,
        converted_client_id=None,
        assigned_to_user_id=10,
        calendly_event_id=None,
        status="PENDIENTE_CONTACTAR",
    )
    event = SimpleNamespace(id=99, user_id=20, prospect_id=None, name="Demo")
    db.get.side_effect = lambda model, pk: event if pk == 99 else None
    actor = SimpleNamespace(id=1, role=SimpleNamespace(code="ADMIN"))

    with pytest.raises(HTTPException) as exc:
        ProspectService(db).link_calendly_event(
            actor=actor,
            prospect=prospect,
            calendly_event_id=99,
        )

    assert exc.value.status_code == 400
    assert "mismo vendedor" in exc.value.detail


def test_link_calendly_allows_matching_sales_rep(monkeypatch):
    db = MagicMock()
    prospect = SimpleNamespace(
        id=1,
        converted_client_id=None,
        assigned_to_user_id=10,
        calendly_event_id=None,
        status="PENDIENTE_CONTACTAR",
    )
    event = SimpleNamespace(id=99, user_id=10, prospect_id=None, name="Demo")
    db.get.side_effect = lambda model, pk: event if pk == 99 else None
    actor = SimpleNamespace(id=1, role=SimpleNamespace(code="BRANCH_MANAGER"))

    service = ProspectService(db)
    monkeypatch.setattr(service, "_add_history", MagicMock())

    result = service.link_calendly_event(
        actor=actor,
        prospect=prospect,
        calendly_event_id=99,
    )

    assert result is prospect
    assert prospect.calendly_event_id == 99
    assert event.prospect_id == 1
    db.commit.assert_called_once()
