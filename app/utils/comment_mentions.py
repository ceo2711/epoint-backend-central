import re

MENTION_TOKEN_PATTERN = re.compile(r"@\[([^\]]+)\]\(mention:(\d+)\)")


def strip_self_mentions(body: str, user_id: int) -> str:
    """Convierte menciones al autor en texto plano (sin notificar)."""

    def replacer(match: re.Match[str]) -> str:
        if int(match.group(2)) == user_id:
            return f"@{match.group(1)}"
        return match.group(0)

    return MENTION_TOKEN_PATTERN.sub(replacer, body)


def extract_mention_user_ids(body: str, *, exclude_user_id: int | None = None) -> list[int]:
    seen: set[int] = set()
    ids: list[int] = []
    for match in MENTION_TOKEN_PATTERN.finditer(body):
        user_id = int(match.group(2))
        if exclude_user_id is not None and user_id == exclude_user_id:
            continue
        if user_id not in seen:
            seen.add(user_id)
            ids.append(user_id)
    return ids


def format_mention_token(*, full_name: str, user_id: int) -> str:
    return f"@[{full_name}](mention:{user_id})"


def format_comment_preview(body: str, *, max_length: int = 100) -> str:
    import re

    plain = re.sub(r"@\[([^\]]+)\]\(mention:\d+\)", r"@\1", body.strip())
    if not plain:
        return "(archivos adjuntos)"
    return plain[:max_length]
