from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.docusign.service import (
    MANUAL_CONTRACT_ORIGIN,
    DocusignService,
)


def test_is_manual_origin():
    assert DocusignService._is_manual(SimpleNamespace(origin="manual")) is True
    assert DocusignService._is_manual(SimpleNamespace(origin="docusign")) is False
    assert DocusignService._is_manual(SimpleNamespace(origin=None)) is False


def test_upload_manual_requires_prospect_or_client():
    svc = DocusignService.__new__(DocusignService)
    svc.ensure_access = MagicMock()
    with pytest.raises(HTTPException) as exc:
        svc.upload_manual_contract(
            actor=SimpleNamespace(id=1),
            file_bytes=b"%PDF",
            filename="contrato.pdf",
            content_type="application/pdf",
            merchant_id=1,
        )
    assert exc.value.status_code == 400


def test_upload_manual_rejects_empty_file():
    svc = DocusignService.__new__(DocusignService)
    svc.ensure_access = MagicMock()
    with pytest.raises(HTTPException) as exc:
        svc.upload_manual_contract(
            actor=SimpleNamespace(id=1),
            file_bytes=b"",
            filename="contrato.pdf",
            content_type="application/pdf",
            merchant_id=1,
            prospect_id=3,
        )
    assert exc.value.status_code == 400


@patch("app.services.prospects.ProspectService")
@patch("app.services.docusign.service.get_storage_provider")
def test_upload_manual_marks_envelope_completed(mock_storage, mock_prospect_cls):
    storage = MagicMock()
    mock_storage.return_value = storage
    storage.build_key.return_value = "docusign/envelopes/9/signed.pdf"

    prospect = SimpleNamespace(
        id=3,
        first_name="Ana",
        last_name="Lopez",
        email="ana@test.com",
        merchant_id=7,
        converted_client_id=None,
        docusign_envelope_id=None,
    )
    psvc = MagicMock()
    psvc._get_prospect_for_user.return_value = prospect
    mock_prospect_cls.return_value = psvc

    mapped = SimpleNamespace(id=9, status="completed", origin=MANUAL_CONTRACT_ORIGIN)
    svc = DocusignService.__new__(DocusignService)
    svc.db = MagicMock()
    svc.ensure_access = MagicMock()
    svc._map_envelope = MagicMock(return_value=mapped)
    svc._signed_storage_key = MagicMock(return_value="docusign/envelopes/9/signed.pdf")

    added = []

    def add(row):
        row.id = 9
        added.append(row)

    svc.db.add.side_effect = add
    loaded = SimpleNamespace(id=9, origin=MANUAL_CONTRACT_ORIGIN)
    svc.db.execute.return_value.unique.return_value.scalar_one.return_value = loaded

    result = svc.upload_manual_contract(
        actor=SimpleNamespace(id=1),
        file_bytes=b"%PDF-1.4 fake",
        filename="firma.pdf",
        content_type="application/pdf",
        merchant_id=7,
        prospect_id=3,
        subject="Contrato en papel",
    )

    assert result.status == "completed"
    assert added[0].status == "completed"
    assert added[0].origin == MANUAL_CONTRACT_ORIGIN
    assert added[0].signer_email == "ana@test.com"
    storage.put_object.assert_called_once()
    psvc.attach_envelope.assert_called_once()
    psvc.on_envelope_completed.assert_called_once()
    svc.db.commit.assert_called_once()
