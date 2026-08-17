from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.docusign.service import DocusignService


def _user(role_code: str, area: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        role=SimpleNamespace(code=role_code),
        area=SimpleNamespace(code=area) if area else None,
    )


@pytest.mark.parametrize(
    "role_code,area",
    [
        ("ADMIN", None),
        ("BRANCH_MANAGER", None),
        ("SALES_REP", "VENTAS"),
        ("SUB_SELLER", "VENTAS"),
        ("AREA_LEADER", "VENTAS"),
        ("AREA_LEADER", "ONBOARDING"),
        ("AREA_LEADER", "ASESORES"),
        ("ADVISOR", "ASESORES"),
    ],
)
def test_ensure_access_allows_contract_roles(role_code: str, area: str | None) -> None:
    DocusignService.ensure_access(_user(role_code, area))


@pytest.mark.parametrize("role_code", ["CLIENT"])
def test_ensure_access_denies_other_roles(role_code: str) -> None:
    with pytest.raises(HTTPException) as exc:
        DocusignService.ensure_access(_user(role_code))
    assert exc.value.status_code == 403
