import re

MENTION_TOKEN_PATTERN = re.compile(r"@\[([^\]]+)\]\(mention:(\d+)\)")


def extract_mention_user_ids(body: str) -> list[int]:
    seen: set[int] = set()
    ids: list[int] = []
    for match in MENTION_TOKEN_PATTERN.finditer(body):
        user_id = int(match.group(2))
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
