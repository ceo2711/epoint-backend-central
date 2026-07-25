"""Proveedor opcional de direcciones vía Google Places API (New).

Solo se usa si existe GOOGLE_MAPS_API_KEY; por defecto el sistema usa Photon,
que no requiere credenciales. Google ofrece mejor cobertura de portales en EE.UU.,
así que sirve como upgrade sin cambiar el resto del código.
Docs: https://developers.google.com/maps/documentation/places/web-service
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.address.base import (
    ALLOWED_COUNTRY_CODES,
    AddressDetails,
    AddressProviderError,
    AddressSuggestion,
)

PLACES_API_BASE = "https://places.googleapis.com/v1"
# Tipos de lugar relevantes para direcciones postales (evita comercios, ciudades sueltas, etc.).
ADDRESS_PRIMARY_TYPES = ["street_address", "premise", "subpremise", "route"]
# Campos que pedimos en Place Details (Google factura según el field mask).
PLACE_DETAILS_FIELD_MASK = "id,formattedAddress,addressComponents"


def _component_index(components: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Indexa addressComponents por tipo → {long, short}."""
    index: dict[str, dict[str, str]] = {}
    for comp in components or []:
        long_text = comp.get("longText") or comp.get("long_text") or ""
        short_text = comp.get("shortText") or comp.get("short_text") or long_text
        for type_ in comp.get("types") or []:
            index.setdefault(type_, {"long": long_text, "short": short_text})
    return index


def _parse_address_components(
    components: list[dict[str, Any]],
    formatted_address: str,
) -> dict[str, str]:
    idx = _component_index(components)

    def long(type_: str) -> str:
        return idx.get(type_, {}).get("long", "")

    def short(type_: str) -> str:
        return idx.get(type_, {}).get("short", "")

    street = " ".join(part for part in (long("street_number"), long("route")) if part).strip()

    # Ciudad: locality es lo habitual; con fallbacks para zonas sin locality.
    city = (
        long("locality")
        or long("postal_town")
        or long("sublocality")
        or long("sublocality_level_1")
        or long("administrative_area_level_2")
    )
    state = short("administrative_area_level_1")
    zip_code = long("postal_code")

    # Si no hay número/route pero sí formatted, usamos la primera línea como calle.
    if not street and formatted_address:
        street = formatted_address.split(",")[0].strip()

    return {"street": street, "city": city, "state": state, "zip_code": zip_code}


class GoogleAddressClient:
    provider = "google"
    supports_details = True

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key.strip()

    def _headers(self, *, field_mask: str | None = None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,
        }
        if field_mask:
            headers["X-Goog-FieldMask"] = field_mask
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        field_mask: str | None = None,
    ) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{PLACES_API_BASE}{path}",
                headers=self._headers(field_mask=field_mask),
                params=params,
                json=json_body,
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            raise AddressProviderError(
                f"No se pudo conectar con el servicio de direcciones: {exc}"
            ) from exc

        if response.status_code in (401, 403):
            raise AddressProviderError(
                "Clave de Google Maps inválida o sin permisos para Places API.",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise AddressProviderError(
                f"El servicio de direcciones respondió con error {response.status_code}: "
                f"{response.text[:300]}",
                status_code=response.status_code,
            )
        if not response.content:
            return {}
        return response.json()

    def autocomplete(
        self,
        query: str,
        *,
        session_token: str | None = None,
        language: str = "es",
        limit: int = 6,
    ) -> list[AddressSuggestion]:
        query = (query or "").strip()
        if len(query) < 3:
            return []
        body: dict[str, Any] = {
            "input": query,
            "includedPrimaryTypes": ADDRESS_PRIMARY_TYPES,
            "includedRegionCodes": list(ALLOWED_COUNTRY_CODES),
            "languageCode": language,
        }
        if session_token:
            body["sessionToken"] = session_token

        payload = self._request("POST", "/places:autocomplete", json_body=body)
        suggestions: list[AddressSuggestion] = []
        for item in (payload.get("suggestions") or [])[:limit]:
            prediction = item.get("placePrediction") or {}
            place_id = prediction.get("placeId") or prediction.get("place")
            if not place_id:
                continue
            text = (prediction.get("text") or {}).get("text", "")
            structured = prediction.get("structuredFormat") or {}
            main_text = (structured.get("mainText") or {}).get("text", "") or text
            suggestions.append(
                AddressSuggestion(
                    place_id=place_id.split("/")[-1],
                    description=text or main_text,
                    main_text=main_text,
                    secondary_text=(structured.get("secondaryText") or {}).get("text", ""),
                )
            )
        return suggestions

    def place_details(
        self,
        place_id: str,
        *,
        session_token: str | None = None,
        language: str = "es",
    ) -> AddressDetails:
        place_id = (place_id or "").strip()
        if not place_id:
            raise AddressProviderError("Falta el identificador del lugar.", status_code=400)
        params: dict[str, Any] = {"languageCode": language}
        if session_token:
            params["sessionToken"] = session_token
        payload = self._request(
            "GET",
            f"/places/{place_id}",
            params=params,
            field_mask=PLACE_DETAILS_FIELD_MASK,
        )
        formatted = payload.get("formattedAddress") or ""
        parsed = _parse_address_components(payload.get("addressComponents") or [], formatted)
        return AddressDetails(
            place_id=str(payload.get("id", place_id)).split("/")[-1],
            formatted_address=formatted,
            **parsed,
        )
