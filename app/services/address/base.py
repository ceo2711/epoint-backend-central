"""Tipos compartidos por los proveedores de autocompletado de direcciones."""

from __future__ import annotations

from dataclasses import dataclass

# Países habilitados para autocompletar (ISO 3166-1 alpha-2).
ALLOWED_COUNTRY_CODES = ("us", "ar")


class AddressProviderError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class AddressSuggestion:
    """Sugerencia mostrada mientras el cliente escribe.

    Los proveedores que devuelven la dirección ya desglosada (Photon) completan
    street/city/state/zip acá; los que no (Google) dejan esos campos vacíos y
    requieren una segunda llamada a ``place_details``.
    """

    place_id: str
    description: str
    main_text: str
    secondary_text: str
    street: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""

    @property
    def is_resolved(self) -> bool:
        return bool(self.street and self.city and self.state and self.zip_code)


@dataclass
class AddressDetails:
    place_id: str
    formatted_address: str
    street: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""


US_STATE_CODES: dict[str, str] = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "american samoa": "AS",
    "guam": "GU",
    "northern mariana islands": "MP",
    "puerto rico": "PR",
    "united states virgin islands": "VI",
    "virgin islands": "VI",
}


def to_state_code(value: str) -> str:
    """Normaliza el estado/provincia a una forma corta cuando aplica.

    EE.UU.: nombre completo → sigla de 2 letras.
    Argentina: deja el nombre de provincia; CABA se unifica a 'CABA'.
    """
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) == 2:
        return text.upper()
    lowered = text.lower()
    if lowered in US_STATE_CODES:
        return US_STATE_CODES[lowered]
    if lowered in {
        "autonomous city of buenos aires",
        "ciudad autonoma de buenos aires",
        "ciudad autónoma de buenos aires",
        "caba",
    }:
        return "CABA"
    return text
