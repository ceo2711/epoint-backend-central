import httpx
import pytest

from app.services.address.base import AddressProviderError, to_state_code
from app.services.address.google import _parse_address_components
from app.services.address.photon import PhotonAddressClient


def _photon_feature(**properties):
    base = {
        "osm_type": "N",
        "osm_id": 1,
        "housenumber": "350",
        "street": "5th Avenue",
        "city": "New York",
        "state": "New York",
        "postcode": "10118",
        "countrycode": "US",
    }
    base.update(properties)
    return {"type": "Feature", "properties": base}


def _patch_photon(monkeypatch, features):
    def fake_get(url, **kwargs):
        return httpx.Response(200, json={"features": features}, request=httpx.Request("GET", url))

    monkeypatch.setattr("app.services.address.photon.httpx.get", fake_get)


def test_to_state_code_normalizes_full_names():
    assert to_state_code("New York") == "NY"
    assert to_state_code("california") == "CA"
    assert to_state_code("FL") == "FL"
    assert to_state_code("") == ""
    assert to_state_code("Autonomous City of Buenos Aires") == "CABA"
    assert to_state_code("Buenos Aires") == "Buenos Aires"


def test_photon_suggestion_is_fully_resolved(monkeypatch):
    _patch_photon(monkeypatch, [_photon_feature()])
    suggestions = PhotonAddressClient().autocomplete("350 5th Ave")

    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion.street == "350 5th Avenue"
    assert suggestion.city == "New York"
    assert suggestion.state == "NY"
    assert suggestion.zip_code == "10118"
    # Al venir resuelta, el cliente no necesita una segunda llamada de detalles.
    assert suggestion.is_resolved


def test_photon_allows_us_and_argentina(monkeypatch):
    _patch_photon(
        monkeypatch,
        [
            _photon_feature(osm_id=2, city="Saskatoon", state="Saskatchewan", countrycode="CA"),
            _photon_feature(osm_id=3),
            _photon_feature(
                osm_id=4,
                housenumber="1856",
                street="Paunero",
                city="Buenos Aires",
                state="Autonomous City of Buenos Aires",
                postcode="C1425",
                countrycode="AR",
            ),
        ],
    )
    suggestions = PhotonAddressClient().autocomplete("Paunero")

    assert [(s.city, s.state, s.zip_code) for s in suggestions] == [
        ("New York", "NY", "10118"),
        ("Buenos Aires", "CABA", "C1425"),
    ]


def test_photon_uses_district_when_city_missing(monkeypatch):
    _patch_photon(
        monkeypatch,
        [
            _photon_feature(
                osm_id=9,
                housenumber="1856",
                street="Paunero",
                city=None,
                district="Villa Delfina",
                state="Buenos Aires",
                postcode="B8000ABL",
                countrycode="AR",
            ),
        ],
    )
    suggestions = PhotonAddressClient().autocomplete("Paunero 1856")
    assert suggestions[0].city == "Villa Delfina"
    assert suggestions[0].state == "Buenos Aires"

def test_photon_deduplicates_pois_sharing_an_address(monkeypatch):
    _patch_photon(
        monkeypatch,
        [
            _photon_feature(osm_id=4, name="Empire State Building"),
            _photon_feature(osm_id=5, name="WNEW-FM"),
        ],
    )
    assert len(PhotonAddressClient().autocomplete("350 5th Ave")) == 1


def test_photon_skips_results_without_street_or_name(monkeypatch):
    _patch_photon(monkeypatch, [_photon_feature(street=None, name=None)])
    assert PhotonAddressClient().autocomplete("350 5th Ave") == []


def test_photon_ignores_short_queries(monkeypatch):
    def fail(*args, **kwargs):  # pragma: no cover - no debería llamarse
        raise AssertionError("no debe llamar al proveedor con menos de 3 caracteres")

    monkeypatch.setattr("app.services.address.photon.httpx.get", fail)
    assert PhotonAddressClient().autocomplete("35") == []


def test_photon_details_not_supported():
    with pytest.raises(AddressProviderError):
        PhotonAddressClient().place_details("N1")


def test_google_components_parsed_to_form_fields():
    components = [
        {"longText": "1600", "shortText": "1600", "types": ["street_number"]},
        {"longText": "Amphitheatre Parkway", "shortText": "Amphitheatre Pkwy", "types": ["route"]},
        {"longText": "Mountain View", "shortText": "Mountain View", "types": ["locality"]},
        {"longText": "California", "shortText": "CA", "types": ["administrative_area_level_1"]},
        {"longText": "94043", "shortText": "94043", "types": ["postal_code"]},
    ]
    parsed = _parse_address_components(components, "1600 Amphitheatre Parkway, Mountain View, CA")

    assert parsed == {
        "street": "1600 Amphitheatre Parkway",
        "city": "Mountain View",
        "state": "CA",
        "zip_code": "94043",
    }
