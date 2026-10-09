"""Small deterministic routes for low-effort Buddy conversation turns."""

from __future__ import annotations

import re
import unicodedata


def social_reply(message: str) -> str | None:
    """Return a short reply only when the entire message is a social turn.

    Exact, normalized matches make this deliberately conservative: a greeting
    followed by a question or task continues through the normal answer path.
    """
    normalized = unicodedata.normalize("NFKC", message).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    normalized = " ".join(normalized.split())

    if normalized in {
        "hi", "hello", "hey", "hiya", "hey there", "hello there",
        "hi there", "hey buddy", "hello buddy", "good morning",
        "good afternoon", "good evening", "morning",
    }:
        return "Hi! What would you like to work on today?"
    if normalized in {"thanks", "thank you", "thanks buddy", "thank you buddy", "ty"}:
        return "You’re welcome!"
    if normalized in {"bye", "goodbye", "see you", "see you later"}:
        return "See you next time!"
    return None
