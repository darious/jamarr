
import re
import unicodedata
from typing import Optional

def _normalize_basic(value: Optional[str]) -> str:
    if not value:
        return ""
    value = "".join(
        c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)
    )
    value = value.lower()
    value = value.replace("&", "and")
    value = value.replace("+", "and")
    value = value.replace("’", "'")
    value = value.replace(".", "")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())

def _strip_benign_suffix(title: str) -> str:
    if not title:
        return ""
    original = title
    pattern = re.compile(r"\s*[\(\[]([^\)\]]+)[\)\]]\s*$")
    BENIGN_SUFFIX_TOKENS = {
        "remaster", "remastered", "mono", "stereo", "edit", "radio", 
        "explicit", "clean", "bonus", "deluxe", "expanded", "anniversary", 
        "reissue", "version", "single", "original", "acoustic", "live", "mix", "album", "remix"
    }
    while True:
        match = pattern.search(title)
        if not match:
            break
        suffix = match.group(1)
        tokens = re.findall(r"[a-z0-9]+", suffix.lower())
        if not tokens:
            break
        if all(token.isdigit() or token in BENIGN_SUFFIX_TOKENS for token in tokens):
            title = title[: match.start()].rstrip()
            continue
        break
    return title or original

def normalize_title(value: Optional[str]) -> str:
    if not value:
        return ""
    stripped = _strip_benign_suffix(value)
    stripped = re.sub(
        r"\s*-?\s*(radio edit|edit|remix|acoustic|version|mix|live|mono|stereo|"
        r"12\" version|12 inch version|single version|album version)\s*$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = stripped.replace("’", "'")
    return _normalize_basic(stripped)

print(f"You should be sad (Acoustic) -> '{normalize_title('You should be sad (Acoustic)')}'")
print(f"Last Kiss (Album Version) -> '{normalize_title('Last Kiss (Album Version)')}'")
print(f"Generic Track (Remix) -> '{normalize_title('Generic Track (Remix)')}'")
print(f"Roses (Imanbek remix) -> '{normalize_title('Roses (Imanbek remix)')}'")
