from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services.docusign.service import DocusignService


def _user(role_code: str) -> MagicMock:
    user = MagicMock()
    user.role.code = role_code
    return user


@pytest.mark.parametrize("role_code", ["ADMIN", "SALES_REP", "ONBOARDING_MANAGER"])
def test_ensure_access_allows_contract_roles(role_code: str) -> None:
    DocusignService.ensure_access(_user(role_code))


@pytest.mark.parametrize("role_code", ["ADVISOR", "AREA_LEADER", "CLIENT"])
def test_ensure_access_denies_other_roles(role_code: str) -> None:
    with pytest.raises(HTTPException) as exc:
        DocusignService.ensure_access(_user(role_code))
    assert exc.value.status_code == 403
