from app.services.chatbot.locale_prefs import (
    detect_explicit_locale_switch,
    infer_locale_from_message,
    is_locale_switch_request,
    resolve_chat_locale,
)


def test_explicit_spanish_switch():
    assert detect_explicit_locale_switch("Chat hablame en español.") == "es"
    assert detect_explicit_locale_switch("por favor habla en castellano") == "es"


def test_explicit_english_switch():
    assert detect_explicit_locale_switch("please speak in english") == "en"


def test_infer_spanish_from_message():
    assert infer_locale_from_message("Hola chat, que cosas puedes hacer?") == "es"
    assert infer_locale_from_message("Si, registra un cliente nuevo llamado Antonio Diaz") == "es"


def test_resolve_prefers_explicit_over_stored():
    assert (
        resolve_chat_locale(
            "hablame en español",
            chat_locale="en",
            fallback_locale="en",
        )
        == "es"
    )


def test_resolve_infers_spanish_when_ui_is_english():
    assert (
        resolve_chat_locale(
            "registra un cliente llamado Antonio Diaz",
            chat_locale="en",
            fallback_locale="en",
        )
        == "es"
    )


def test_locale_switch_request():
    assert is_locale_switch_request("hablame en español")
    assert not is_locale_switch_request("registra un cliente llamado Juan")
