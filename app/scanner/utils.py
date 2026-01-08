import re
from typing import Optional


_LETTER_RE = re.compile(r"[A-Za-z]")


def artist_letter(name: Optional[str], sort_name: Optional[str]) -> str:
    candidate = (sort_name or name or "").strip()
    if candidate and _LETTER_RE.match(candidate):
        return candidate[0].upper()
    return "#"
