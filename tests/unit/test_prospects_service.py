from app.services.prospects import ALLOWED_TRANSITIONS, INITIAL_STATUS
from app.models.enums import ProspectStatus


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
