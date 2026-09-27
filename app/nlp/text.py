"""Text normalisation helpers shared by the NLP pipeline."""

from __future__ import annotations

import re
from collections.abc import Iterable

_WS = re.compile(r"\s+")
_BOILERPLATE = re.compile(
    r"^(hi team|hello|fyi|quick feedback|honestly|ticket from admin)[,:]?\s*|"
    r"\s*(thanks!?|please advise\.?|any update on this\?|rated \d/5\.?|raised by our account manager\.?|"
    r"this is blocking our team\.?)\s*$",
    re.IGNORECASE,
)


def clean(text: str) -> str:
    text = _WS.sub(" ", str(text or "")).strip()
    # strip greeting / sign-off boilerplate (repeat to catch both ends)
    for _ in range(3):
        new = _BOILERPLATE.sub("", text).strip()
        if new == text:
            break
        text = new
    return text


def build_entity_masker(names: Iterable[str], token: str = "this feature"):
    """Return fn(text)->text that replaces product/feature names with a neutral token.

    Masking entity names before clustering makes clusters capture *themes*
    ("slow load times") rather than simply grouping by which feature a ticket
    mentions.
    """
    names = sorted({n for n in names if n and len(n) > 2}, key=len, reverse=True)
    if not names:
        return lambda t: t
    pattern = re.compile("|".join(re.escape(n) for n in names), re.IGNORECASE)
    return lambda t: pattern.sub(token, t)
