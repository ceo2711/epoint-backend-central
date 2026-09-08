from app.models.enums import ProspectStatus
from app.schemas.prospect import ProspectCreate, ProspectUpdate
from app.services.prospects import ALLOWED_TRANSITIONS, INITIAL_STATUS


def test_prospect_create_qualification_is_optional():
    payload = ProspectCreate(
        first_name="Ana",
        last_name="Perez",
        email="ana@test.com",
        phone="1234567890",
        merchant_id=1,
    )
    assert payload.is_qualified is None


def test_prospect_update_can_clear_qualification():
    payload = ProspectUpdate(is_qualified=None)
    assert payload.model_dump(exclude_unset=True) == {"is_qualified": None}


class TestProspectTransitions:
    def test_initial_status_is_pending_contact(self):
        assert INITIAL_STATUS == ProspectStatus.PENDIENTE_CONTACTAR.value

    def test_pending_can_become_contacted(self):
        allowed = ALLOWED_TRANSITIONS[ProspectStatus.PENDIENTE_CONTACTAR.value]
        assert ProspectStatus.LEAD_CONTACTADO.value in allowed
        assert ProspectStatus.LEAD_CERRADO.value in allowed

    def test_no_legacy_qualification_statuses(self):
        assert "LEAD_CALIFICADO" not in ALLOWED_TRANSITIONS
        assert "LEAD_NO_CALIFICADO" not in ALLOWED_TRANSITIONS
        assert not hasattr(ProspectStatus, "LEAD_CALIFICADO")
        assert not hasattr(ProspectStatus, "LEAD_NO_CALIFICADO")
