"""Autocompletado y verificación de direcciones.

Por defecto usa Photon (OpenStreetMap), que no requiere API key ni configuración.
Si se define GOOGLE_MAPS_API_KEY, se usa Google Places por su mejor cobertura.
"""

from typing import Protocol

from app.core.config import get_settings
from app.services.address.base import (
    AddressDetails,
    AddressProviderError,
    AddressSuggestion,
)
from app.services.address.google import GoogleAddressClient
from app.services.address.photon import PhotonAddressClient


class AddressProvider(Protocol):
    provider: str
    supports_details: bool

    def autocomplete(
        self,
        query: str,
        *,
        session_token: str | None = ...,
        language: str = ...,
        limit: int = ...,
    ) -> list[AddressSuggestion]: ...

    def place_details(
        self,
        place_id: str,
        *,
        session_token: str | None = ...,
        language: str = ...,
    ) -> AddressDetails: ...


def get_address_provider() -> AddressProvider:
    settings = get_settings()
    if settings.google_maps_configured:
        return GoogleAddressClient(settings.google_maps_api_key)
    return PhotonAddressClient()


__all__ = [
    "AddressDetails",
    "AddressProvider",
    "AddressProviderError",
    "AddressSuggestion",
    "GoogleAddressClient",
    "PhotonAddressClient",
    "get_address_provider",
]
