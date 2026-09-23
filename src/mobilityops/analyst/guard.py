"""Safety checks around the analyst: what it will not do, and proof its numbers are grounded.

Two independent defences:

1. **Screening.** Questions asking the analyst to change data, run code or SQL, reveal secrets
   or its own instructions, or act outside analysing this dataset are refused. Text that *tries
   to override instructions* is flagged and ignored: in this design a question can only ever
   select among read-only tools, so an injected instruction has nothing to hijack. The planner
   never sees tool outputs either, so data (zone names, event text) cannot inject instructions
   into planning.

2. **Grounding.** Every FACT statement in an answer must cite tool facts, and every number in it
   must appear in one of them. A statement failing this is replaced, not shown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_QUESTION_CHARS = 500

# (pattern, reason). Refusals: the request itself is outside what a read-only analyst may do.
_REFUSE: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.I), why)
    for p, why in (
        (
            r"\b(drop|truncate|alter|delete|insert|update)\s+(table|from|into|database|schema)\b",
            "I only read data; I cannot modify or delete it.",
        ),
        (
            r"\b(delete|erase|wipe|remove|overwrite|modify|edit|change)\b.{0,30}\b(data|database|table|records?|files?|model)\b",
            "I only read data; I cannot modify or delete it.",
        ),
        (
            r"\b(select\s+.+\s+from|union\s+select|;\s*--)\b",
            "I do not run SQL; I only use a fixed set of read-only analysis tools.",
        ),
        (
            r"\b(run|execute|eval|exec)\b.{0,25}\b(code|python|script|command|shell|bash|sql|query)\b",
            "I do not execute code or commands.",
        ),
        (
            r"(api[\s_-]?key|\bsecret[\s_-]?(key|token)s?\b|\bclient secret\b|\bpasswords?\b|"
            r"\bcredentials?\b|access[\s_-]?token|"
            r"private key|\.env\b|environment variable)",
            "I do not have or reveal credentials, keys or configuration secrets.",
        ),
        (
            r"\b(system|developer|hidden|initial)\s+(prompt|message|instructions?)\b|\byour\s+(instructions|prompt|rules)\b",
            "I do not disclose my instructions; I answer questions about the mobility data.",
        ),
        (
            r"\b(read|open|cat|show|print|list)\b.{0,20}(/etc/|/home/|\.\./|c:\\\\|passwd|ssh)",
            "I cannot access files; I only use the analysis tools.",
        ),
    )
)

_INJECTION: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+"
        r"(instructions?|rules?|prompts?)",
        r"disregard\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|your)",
        r"\byou\s+are\s+now\b",
        r"\bact\s+as\b.{0,20}\b(admin|root|developer|dan|unrestricted)\b",
        r"\b(developer|debug|jailbreak|god)\s+mode\b",
        r"^\s*(system|assistant)\s*:",
        r"<\s*/?\s*(system|instructions?)\s*>",
        r"\bnew\s+instructions?\b",
        r"\bpretend\b.{0,30}\b(no|without)\s+(rules|restrictions|limits)\b",
    )
)

# Requests the tools cannot serve; declining is more honest than improvising an answer.
_OUT_OF_SCOPE: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.I), why)
    for p, why in (
        (
            r"\b(stock|bitcoin|crypto|lottery|horoscope|recipe|joke|poem|song)\b",
            "That is outside what I can analyse: NYC yellow-taxi demand, forecasts, anomalies "
            "and simulated repositioning.",
        ),
        (
            r"\b(driver|passenger|customer|person|people|individual)s?\b.{0,20}\b(name|address|phone|email|identity|track|who)\b",
            "The data has no personal information, and I do not track individuals.",
        ),
        (
            r"\b(uber|lyft|green taxi|for-hire|fhv|subway|bus)\b",
            "This dataset covers yellow taxis only, so I cannot answer about other services.",
        ),
    )
)


@dataclass(frozen=True)
class Screen:
    refused: bool
    reason: str | None = None
    injection_suspected: bool = False
    flags: list[str] = field(default_factory=list)


def sanitize(question: str) -> str:
    """Trim, drop control characters, collapse whitespace, cap length."""
    cleaned = "".join(ch if ch.isprintable() or ch in "\n\t" else " " for ch in question)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:MAX_QUESTION_CHARS]


def screen(question: str) -> Screen:
    flags: list[str] = []
    injected = any(p.search(question) for p in _INJECTION)
    if injected:
        flags.append("instruction-override phrasing ignored")
    for pattern, why in _REFUSE:
        if pattern.search(question):
            return Screen(True, why, injected, [*flags, "disallowed request"])
    for pattern, why in _OUT_OF_SCOPE:
        if pattern.search(question):
            return Screen(True, why, injected, [*flags, "out of scope"])
    return Screen(False, None, injected, flags)


# ----------------------------------------------------------------------------- grounding
_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_TIME = re.compile(r"\b\d{1,2}:\d{2}\b")
_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?%?")


def _numbers(text: str) -> list[str]:
    stripped = _TIME.sub(" ", _ISO.sub(" ", text))
    return [m.group(0) for m in _NUM.finditer(stripped)]


def _value(tok: str) -> float | None:
    try:
        return float(tok.replace(",", "").rstrip("%"))
    except ValueError:
        return None


def ungrounded_numbers(text: str, allowed_displays: list[str]) -> list[str]:
    """Numbers in ``text`` that match none of the cited facts' displayed values.

    A number is grounded if it equals a displayed number from a cited fact (ignoring thousands
    separators and a trailing %), or, when the text rounds more coarsely, is within rounding of
    one. Dates and clock times are checked as substrings of the cited displays.
    """
    pool: list[float] = []
    joined = " ".join(allowed_displays)
    for disp in allowed_displays:
        for tok in _numbers(disp):
            v = _value(tok)
            if v is not None:
                pool.append(v)
    bad: list[str] = []
    for tok in _numbers(text):
        v = _value(tok)
        if v is None:
            continue
        decimals = len(tok.rstrip("%").split(".")[1]) if "." in tok else 0
        ok = any(abs(v - p) <= 0.5 * 10 ** (-decimals) + 1e-9 for p in pool)
        if not ok:
            bad.append(tok)
    for d in _ISO.findall(text) + _TIME.findall(text):
        if d not in joined:
            bad.append(d)
    return bad
