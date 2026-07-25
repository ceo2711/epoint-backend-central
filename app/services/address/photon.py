"""Proveedor de direcciones basado en Photon (OpenStreetMap) — sin API key ni cuenta.

Photon está pensado específicamente para autocompletado (a diferencia de Nominatim,
cuya política de uso lo prohíbe) y devuelve la dirección ya desglosada en una sola
llamada, así que no necesita un segundo request de "detalles".
Docs: https://photon.komoot.io
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from app.services.address.base import (
    ALLOWED_COUNTRY_CODES,
    AddressDetails,
    AddressProviderError,
    AddressSuggestion,
    to_state_code,
)

PHOTON_API_BASE = "https://photon.komoot.io"
# Photon pide un User-Agent identificable en su instancia pública.
USER_AGENT = "epoint-crm/1.0 (+address autocomplete)"
# Idiomas que acepta la instancia pública de Photon.
PHOTON_LANGS = frozenset({"default", "de", "en", "fr"})
# Sesgamos por región: un solo bbox mundial diluye resultados; consultamos ambos.
REGION_BBOXES = (
    # EE.UU. (incluye Alaska, Hawái y Puerto Rico)
    "-171.8,17.8,-64.5,71.4",
    # Argentina
    "-73.6,-55.1,-53.6,-21.8",
)


def _photon_lang(language: str) -> str:
    lang = (language or "en").lower().split("-")[0]
    return lang if lang in PHOTON_LANGS else "en"


def _build_suggestion(properties: dict[str, Any], osm_id: Any) -> AddressSuggestion | None:
    housenumber = (properties.get("housenumber") or "").strip()
    route = (properties.get("street") or "").strip()
    name = (properties.get("name") or "").strip()

    if route:
        street = f"{housenumber} {route}".strip()
    elif name:
        # POI sin calle asociada (ej. un edificio con nombre propio).
        street = f"{housenumber} {name}".strip() if housenumber else name
    else:
        return None

    city = (
        properties.get("city")
        or properties.get("town")
        or properties.get("village")
        or properties.get("district")
        or properties.get("county")
        or ""
    ).strip()
    state = to_state_code(properties.get("state") or "")
    zip_code = (properties.get("postcode") or "").strip()

    secondary_parts = [part for part in (city, state, zip_code) if part]
    return AddressSuggestion(
        place_id=f"{properties.get('osm_type', '')}{osm_id}",
        description=", ".join([street, *secondary_parts]),
        main_text=street,
        secondary_text=", ".join(secondary_parts),
        street=street,
        city=city,
        state=state,
        zip_code=zip_code,
    )


class PhotonAddressClient:
    provider = "photon"
    supports_details = False

    def _fetch_region(
        self,
        query: str,
        *,
        bbox: str,
        language: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            response = httpx.get(
                f"{PHOTON_API_BASE}/api/",
                params={
                    "q": query,
                    "limit": limit,
                    "lang": language,
                    "layer": "house",
                    "bbox": bbox,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise AddressProviderError(
                f"No se pudo conectar con el servicio de direcciones: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise AddressProviderError(
                f"El servicio de direcciones respondió con error {response.status_code}",
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AddressProviderError("Respuesta inválida del servicio de direcciones") from exc

        # Photon responde 200 con {lang: [...]} cuando el idioma no es soportado.
        if "features" not in payload:
            return []
        return list(payload.get("features") or [])

    def autocomplete(
        self,
        query: str,
        *,
        session_token: str | None = None,
        language: str = "en",
        limit: int = 6,
    ) -> list[AddressSuggestion]:
        query = (query or "").strip()
        if len(query) < 3:
            return []

        lang = _photon_lang(language)
        # Pedimos un poco más por región para compensar el filtro por país.
        per_region = max(limit, 4)

        features: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=len(REGION_BBOXES)) as pool:
            futures = [
                pool.submit(self._fetch_region, query, bbox=bbox, language=lang, limit=per_region)
                for bbox in REGION_BBOXES
            ]
            for future in futures:
                features.extend(future.result())

        suggestions: list[AddressSuggestion] = []
        seen: set[str] = set()
        for feature in features:
            properties = feature.get("properties") or {}
            country = (properties.get("countrycode") or "").lower()
            if country not in ALLOWED_COUNTRY_CODES:
                continue
            suggestion = _build_suggestion(properties, properties.get("osm_id"))
            if suggestion is None:
                continue
            # Photon devuelve varios POI para el mismo portal (ej. locales de un edificio).
            key = suggestion.description.lower()
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(suggestion)
            if len(suggestions) >= limit:
                break
        return suggestions

    def place_details(
        self,
        place_id: str,
        *,
        session_token: str | None = None,
        language: str = "en",
    ) -> AddressDetails:
        raise AddressProviderError(
            "Este proveedor ya devuelve la dirección completa en el autocompletado.",
            status_code=400,
        )
