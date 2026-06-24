import pytest

from app.services.chatbot.registration_intents import (
    is_registration_meta_question,
    looks_like_person_name,
)


@pytest.mark.parametrize(
    "message",
    [
        "Chat puedes registrar varios clientes al mismo tiempo?",
        "¿Puedo registrar varios clientes seguidos?",
        "¿Se puede registrar más de un cliente a la vez?",
        "Can you register multiple clients at once?",
    ],
)
def test_is_registration_meta_question_matches(message: str):
    assert is_registration_meta_question(message)


@pytest.mark.parametrize(
    "message",
    [
        "registrar a Juan Perez",
        "Alexis Diaz juan@mail.com 1131432490",
        "hola como estas",
        "quiero registrar un cliente",
    ],
)
def test_is_registration_meta_question_does_not_match_registration(message: str):
    assert not is_registration_meta_question(message)


def test_looks_like_person_name_rejects_stopwords():
    assert not looks_like_person_name("Chat", "puedes registrar varios clientes")
    assert not looks_like_person_name("registrar", "varios clientes")


def test_looks_like_person_name_accepts_real_names():
    assert looks_like_person_name("Alexis", "Diaz")
    assert looks_like_person_name("Maria", "Laura Gomez")
