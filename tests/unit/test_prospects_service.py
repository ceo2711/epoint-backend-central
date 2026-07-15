from app.services.prospects import ALLOWED_TRANSITIONS, INITIAL_STATUSES
from app.models.enums import ProspectStatus


class TestProspectTransitions:
    def test_initial_statuses(self):
        assert ProspectStatus.LEAD_CALIFICADO.value in INITIAL_STATUSES
        assert ProspectStatus.LEAD_NO_CALIFICADO.value in INITIAL_STATUSES

    def test_qualified_can_become_contacted(self):
        allowed = ALLOWED_TRANSITIONS[ProspectStatus.LEAD_CALIFICADO.value]
        assert ProspectStatus.LEAD_CONTACTADO.value in allowed

    def test_unqualified_can_only_close(self):
        allowed = ALLOWED_TRANSITIONS[ProspectStatus.LEAD_NO_CALIFICADO.value]
        assert allowed == {ProspectStatus.LEAD_CERRADO.value}
