import pytest

from app.services.chatbot.approval_intents import (
    looks_like_approve_all,
    looks_like_approve_one,
    looks_like_reject_all,
)


@pytest.mark.parametrize(
    "message",
    [
        "aprobar todos los pendientes",
        "aprobar a todos",
        "aprueba todos",
        "apruebalos todos",
        "Chat apruebalos todos.",
        "apruébalos a todos",
        "aprueben todos los clientes pendientes",
        "todos los pendientes aprobar",
    ],
)
def test_looks_like_approve_all_matches_natural_spanish(message: str):
    assert looks_like_approve_all(message)


@pytest.mark.parametrize(
    "message",
    [
        "informe completo del cliente",
        "tengo algun cliente pendiente",
        "hola como estas",
    ],
)
def test_looks_like_approve_all_does_not_match_unrelated(message: str):
    assert not looks_like_approve_all(message)


def test_looks_like_approve_one_distinguishes_from_all():
    assert looks_like_approve_one("aprobar a Angela")
    assert not looks_like_approve_one("apruebalos todos")


def test_looks_like_reject_all_matches():
    assert looks_like_reject_all("rechaza todos los pendientes")
    assert looks_like_reject_all("rechazalos a todos")
