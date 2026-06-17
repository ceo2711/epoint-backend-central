from app.utils.comment_mentions import extract_mention_user_ids, format_comment_preview, format_mention_token


def test_format_and_extract_mention_token():
    token = format_mention_token(full_name="Paola Lopez", user_id=42)
    assert token == "@[Paola Lopez](mention:42)"
    assert extract_mention_user_ids(f"Hola {token} gracias") == [42]


def test_extract_mention_user_ids_deduplicates():
    body = "@[A](mention:1) y @[B](mention:1)"
    assert extract_mention_user_ids(body) == [1]


def test_extract_mention_user_ids_empty():
    assert extract_mention_user_ids("sin menciones") == []


def test_format_comment_preview():
    body = "@[Asesor Demo](mention:4) hola"
    assert format_comment_preview(body) == "@Asesor Demo hola"
