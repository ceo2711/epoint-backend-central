from app.services.chatbot.guides import (
    build_platform_guide_context,
    is_how_to_question,
    platform_sections_for_role,
    select_guides,
)


def test_how_to_detection():
    assert is_how_to_question("¿Cómo registro un cliente?")
    assert is_how_to_question("dónde apruebo pendientes")
    assert is_how_to_question("How does the platform work?")
    assert not is_how_to_question("aprobar todos")


def test_sales_sections_include_prospects_and_payments():
    sections = platform_sections_for_role("SALES_REP", "https://app.example.com")
    urls = {s["url"] for s in sections}
    assert "https://app.example.com/prospectos" in urls
    assert "https://app.example.com/pagos" in urls
    assert "https://app.example.com/clientes" in urls


def test_onboarding_sections_skip_sales_only_screens():
    sections = platform_sections_for_role("ONBOARDING_MANAGER", "https://app.example.com")
    urls = {s["url"] for s in sections}
    assert "https://app.example.com/clientes" in urls
    assert "https://app.example.com/prospectos" not in urls


def test_select_guides_prioritizes_approve_for_onboarding():
    guides = select_guides("ONBOARDING_MANAGER", "cómo apruebo un cliente pendiente")
    assert guides
    assert guides[0]["id"] == "aprobar_cliente"


def test_select_guides_hides_internal_from_client():
    assert select_guides("CLIENT", "cómo funciona la plataforma") == []


def test_platform_context_includes_sections_and_guides():
    payload = build_platform_guide_context(
        role="SALES_REP",
        base_url="https://app.example.com",
        message="¿Cómo registro un cliente?",
    )
    assert payload["secciones"]
    assert payload["guias_tutoriales"]
    assert any(g["id"] == "registrar_cliente" for g in payload["guias_tutoriales"])
    assert "nota_guia" in payload
