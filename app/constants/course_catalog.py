from functools import lru_cache
import json
from pathlib import Path
from typing import Any


@lru_cache
def default_course_catalog() -> dict[str, Any]:
    path = Path(__file__).with_name("course_catalog.json")
    return json.loads(path.read_text(encoding="utf-8"))
