from app.services.docusign.service import resolve_template_role_name


class TestResolveTemplateRoleName:
    def test_keeps_exact_match(self):
        assert resolve_template_role_name("Cliente", ["Cliente", "Testigo"]) == "Cliente"

    def test_case_insensitive_match(self):
        assert resolve_template_role_name("cliente", ["Cliente"]) == "Cliente"

    def test_maps_signer_default_to_cliente(self):
        assert resolve_template_role_name("Signer", ["Cliente"]) == "Cliente"

    def test_uses_single_role_when_requested_missing(self):
        assert resolve_template_role_name("Signer", ["Firmante único"]) == "Firmante único"

    def test_prefers_known_aliases(self):
        assert resolve_template_role_name(None, ["Witness", "Cliente"]) == "Cliente"
