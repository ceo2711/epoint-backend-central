from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.services.chatbot.calendly_intents import EVENT_ID_PATTERN, OPTION_NUMBER_PATTERN, TIME_PATTERN

DEFAULT_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
DATE_ISO_PATTERN = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
DATE_DMY_PATTERN = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def parse_date_input(text: str) -> str | None:
    cleaned = text.strip()
    match = DATE_ISO_PATTERN.search(cleaned)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

    match = DATE_DMY_PATTERN.search(cleaned)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None

    lowered = cleaned.lower()
    if any(token in lowered for token in ("hoy", "today")):
        return datetime.now(DEFAULT_TZ).date().isoformat()
    if any(token in lowered for token in ("manana", "mañana", "tomorrow")):
        return (datetime.now(DEFAULT_TZ).date() + timedelta(days=1)).isoformat()
    return None


def day_bounds(date_value: str, tz: ZoneInfo = DEFAULT_TZ) -> tuple[datetime, datetime]:
    day = date.fromisoformat(date_value)
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    return start, end


def resolve_event_type(message: str, event_types: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not event_types:
        return None

    number_match = OPTION_NUMBER_PATTERN.match(message.strip())
    if number_match:
        index = int(number_match.group(1)) - 1
        if 0 <= index < len(event_types):
            return event_types[index]

    lowered = message.strip().lower()
    for item in event_types:
        name = (item.get("name") or "").lower()
        if name and (name in lowered or lowered in name):
            return item
    return None


def resolve_event_id(message: str, events: list[dict[str, Any]]) -> int | None:
    match = EVENT_ID_PATTERN.search(message)
    if match:
        candidate = int(match.group(1))
        if any(event.get("id") == candidate for event in events):
            return candidate

    number_match = OPTION_NUMBER_PATTERN.match(message.strip())
    if number_match:
        index = int(number_match.group(1)) - 1
        if 0 <= index < len(events):
            return int(events[index]["id"])
    return None


def resolve_slot(message: str, slots: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not slots:
        return None

    number_match = OPTION_NUMBER_PATTERN.match(message.strip())
    if number_match:
        index = int(number_match.group(1)) - 1
        if 0 <= index < len(slots):
            return slots[index]

    lowered = message.strip().lower()
    time_match = TIME_PATTERN.search(lowered)
    if time_match:
        target = time_match.group(1).replace(".", "").replace(" ", "")
        for slot in slots:
            label = (slot.get("label") or "").lower().replace(".", "").replace(" ", "")
            if target in label or label in target:
                return slot
    return None


def extract_email(text: str) -> str | None:
    match = EMAIL_PATTERN.search(text)
    return match.group(0) if match else None


def format_event_types(event_types: list[dict[str, Any]], *, locale: str) -> list[dict[str, Any]]:
    return [
        {
            "index": index + 1,
            "uri": item.get("uri"),
            "name": item.get("name") or "Evento",
            "duration": item.get("duration"),
            "description": item.get("description"),
            "custom_questions": item.get("custom_questions") or [],
        }
        for index, item in enumerate(event_types)
    ]


def format_slots(slots: list[dict[str, Any]], *, locale: str) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for index, slot in enumerate(slots):
        start_raw = slot.get("start_time")
        if isinstance(start_raw, datetime):
            start_dt = start_raw if start_raw.tzinfo else start_raw.replace(tzinfo=timezone.utc)
        else:
            start_dt = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
        local = start_dt.astimezone(DEFAULT_TZ)
        label = local.strftime("%H:%M") if locale == "en" else local.strftime("%I:%M %p").lstrip("0")
        formatted.append(
            {
                "index": index + 1,
                "start_time": start_dt.isoformat().replace("+00:00", "Z"),
                "label": label,
            }
        )
    return formatted


def format_events(events: list[Any], *, locale: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        start = event.start_time if hasattr(event, "start_time") else event.get("start_time")
        end = event.end_time if hasattr(event, "end_time") else event.get("end_time")
        if isinstance(start, str):
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        else:
            start_dt = start
        if isinstance(end, str):
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        else:
            end_dt = end
        local_start = start_dt.astimezone(DEFAULT_TZ)
        local_end = end_dt.astimezone(DEFAULT_TZ)
        rows.append(
            {
                "id": event.id if hasattr(event, "id") else event.get("id"),
                "name": event.name if hasattr(event, "name") else event.get("name"),
                "status": event.status if hasattr(event, "status") else event.get("status"),
                "invitee_name": event.invitee_name if hasattr(event, "invitee_name") else event.get("invitee_name"),
                "invitee_email": event.invitee_email if hasattr(event, "invitee_email") else event.get("invitee_email"),
                "invitee_comment": event.invitee_comment if hasattr(event, "invitee_comment") else event.get("invitee_comment"),
                "start_label": local_start.strftime("%d/%m/%Y %H:%M"),
                "end_label": local_end.strftime("%H:%M"),
            }
        )
    return rows


def format_events_reply(events: list[dict[str, Any]], *, locale: str, title: str) -> str:
    if not events:
        return title + ("\n\nNo tienes reuniones programadas para ese período." if locale != "en" else "\n\nYou have no meetings scheduled for that period.")

    lines = [title, ""]
    for event in events:
        invitee = event.get("invitee_name") or "—"
        email = event.get("invitee_email") or ""
        suffix = f" ({email})" if email else ""
        lines.append(
            f"- **#{event['id']}** {event.get('name')} — {event.get('start_label')} · {invitee}{suffix}"
        )
        if event.get("invitee_comment"):
            lines.append(f"  _{event['invitee_comment']}_")
    return "\n".join(lines)
