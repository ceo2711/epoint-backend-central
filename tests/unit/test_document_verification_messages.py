from app.services.document_verification_messages import (
    build_approval_messages,
    build_rejection_messages,
    normalize_bilingual_messages,
    to_localized_lists,
)


def test_normalize_legacy_spanish_strings():
    items = normalize_bilingual_messages(["Documento borroso"])
    assert items == [{"en": "Documento borroso", "es": "Documento borroso"}]


def test_normalize_bilingual_objects():
    items = normalize_bilingual_messages([{"en": "Blurry", "es": "Borroso"}])
    assert items[0]["en"] == "Blurry"
    assert items[0]["es"] == "Borroso"


def test_build_rejection_messages_from_flags():
    messages = build_rejection_messages(
        {"is_readable": False, "is_complete": False},
        document_type="SSN_CARD",
        client_name="Alexis Guanique",
    )
    localized = to_localized_lists(messages)
    assert localized["en"]
    assert localized["es"]
    assert any("readable" in item.lower() for item in localized["en"])


def test_build_approval_messages_from_flags():
    messages = build_approval_messages(
        {
            "is_readable": True,
            "is_complete": True,
            "is_color": True,
            "corners_cut": False,
            "is_expired": False,
            "document_type_matches": True,
            "detected_document_type": "SSN card",
            "name_matches": True,
        },
        document_type="SSN_CARD",
        client_name="Alexis Guanique",
    )
    localized = to_localized_lists(messages)
    assert localized["en"]
    assert localized["es"]
    assert any("readable" in item.lower() or "clear" in item.lower() for item in localized["en"])


def test_build_rejection_messages_wrong_document_type():
    messages = build_rejection_messages(
        {
            "is_readable": True,
            "document_type_matches": False,
            "detected_document_type": "invoice",
        },
        document_type="SSN_CARD",
        client_name="Alexis Guanique",
    )
    localized = to_localized_lists(messages)
    assert any("invoice" in item.lower() or "ssn_card" in item.lower() for item in localized["en"])
