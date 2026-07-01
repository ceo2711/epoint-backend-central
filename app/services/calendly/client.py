"""Cliente HTTP para Calendly API v2."""

from __future__ import annotations

from typing import Any

import httpx

CALENDLY_API_BASE = "https://api.calendly.com"


class CalendlyApiError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CalendlyClient:
    def __init__(self, access_token: str) -> None:
        self._access_token = access_token.strip()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{CALENDLY_API_BASE}{path}"
        try:
            response = httpx.request(
                method,
                url,
                headers=self._headers(),
                params=params,
                json=json_body,
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise CalendlyApiError(f"No se pudo conectar con Calendly: {exc}") from exc

        if response.status_code == 401:
            raise CalendlyApiError("Token de Calendly inválido o expirado", status_code=401)
        if response.status_code == 403:
            detail = response.text.strip()[:400]
            hint = (
                "Calendly rechazó la operación (403). "
                "Si el token ya tiene scheduled_events:write, revisá: "
                "(1) que pegaste el token nuevo en /calendario → Configuración, "
                "(2) que tu cuenta Calendly sea plan Standard o superior (el plan Free bloquea crear/cancelar por API), "
                "(3) que el evento pertenezca a la misma cuenta del token."
            )
            if detail:
                raise CalendlyApiError(f"{hint} Detalle Calendly: {detail}", status_code=403)
            raise CalendlyApiError(hint, status_code=403)
        if response.status_code >= 400:
            detail = response.text[:300]
            raise CalendlyApiError(
                f"Calendly respondió con error {response.status_code}: {detail}",
                status_code=response.status_code,
            )
        if not response.content:
            return {}
        return response.json()

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def _post(self, path: str, *, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", path, json_body=json_body or {})

    def get_current_user(self) -> dict[str, Any]:
        payload = self._get("/users/me")
        return payload.get("resource") or {}

    def list_event_types(self, *, user_uri: str, active: bool = True) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        params: dict[str, Any] = {"user": user_uri, "active": active, "count": 100}
        while True:
            payload = self._get("/event_types", params=params)
            items.extend(payload.get("collection") or [])
            next_page = (payload.get("pagination") or {}).get("next_page_token")
            if not next_page:
                break
            params["page_token"] = next_page
        return items

    def list_available_times(
        self,
        *,
        event_type_uri: str,
        start_time: str,
        end_time: str,
    ) -> list[dict[str, Any]]:
        payload = self._get(
            "/event_type_available_times",
            params={
                "event_type": event_type_uri,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        return payload.get("collection") or []

    def list_scheduled_events(
        self,
        *,
        user_uri: str,
        min_start_time: str,
        max_start_time: str,
        count: int = 100,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        params: dict[str, Any] = {
            "user": user_uri,
            "min_start_time": min_start_time,
            "max_start_time": max_start_time,
            "count": count,
        }
        while True:
            payload = self._get("/scheduled_events", params=params)
            events.extend(payload.get("collection") or [])
            next_page = (payload.get("pagination") or {}).get("next_page_token")
            if not next_page:
                break
            params["page_token"] = next_page
        return events

    def list_event_invitees(self, event_uri: str) -> list[dict[str, Any]]:
        event_uuid = event_uri.rstrip("/").split("/")[-1]
        payload = self._get(f"/scheduled_events/{event_uuid}/invitees")
        return payload.get("collection") or []

    def get_event_type(self, event_type_uri: str) -> dict[str, Any]:
        event_type_uuid = event_type_uri.rstrip("/").split("/")[-1]
        payload = self._get(f"/event_types/{event_type_uuid}")
        return payload.get("resource") or {}

    def get_event_type_name(self, event_type_uri: str | None) -> str | None:
        if not event_type_uri:
            return None
        return self.get_event_type(event_type_uri).get("name")

    def cancel_scheduled_event(self, event_uri: str, *, reason: str | None = None) -> None:
        event_uuid = event_uri.rstrip("/").split("/")[-1]
        body: dict[str, Any] = {}
        if reason:
            body["reason"] = reason
        self._post(f"/scheduled_events/{event_uuid}/cancellation", json_body=body)

    def create_invitee(
        self,
        *,
        event_type_uri: str,
        start_time: str,
        name: str,
        email: str,
        timezone: str | None = None,
        questions_and_answers: list[dict[str, str | int]] | None = None,
    ) -> dict[str, Any]:
        invitee: dict[str, Any] = {"name": name, "email": email}
        if timezone:
            invitee["timezone"] = timezone
        body: dict[str, Any] = {
            "event_type": event_type_uri,
            "start_time": start_time,
            "invitee": invitee,
        }
        if questions_and_answers:
            body["questions_and_answers"] = questions_and_answers
        payload = self._post("/invitees", json_body=body)
        return payload.get("resource") or {}
