"""SQL helpers.

Rule for this codebase: SQL that touches *user input* (API parameters, AI tool arguments) must use
bound parameters, never string formatting. The pipeline layers (``transform``) build a few
statements from server-controlled values only (file paths derived from configuration, date
literals from ``datetime.date``); those go through :func:`quote_literal` so a path that happens to
contain a quote cannot break or alter the statement.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path


def quote_literal(value: str | Path | date) -> str:
    """Return ``value`` as a safely quoted SQL string literal, e.g. ``'it''s'``."""
    text = value.isoformat() if isinstance(value, date) else str(value)
    if "\x00" in text:
        raise ValueError("NUL byte in SQL literal")
    return "'" + text.replace("'", "''") + "'"
