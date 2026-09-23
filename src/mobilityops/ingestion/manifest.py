"""Ingestion manifest: an auditable record of exactly which files the data came from.

One JSON file per data mode. Each entry stores the source URL, size, SHA-256, retrieval time
(UTC), and, for Parquet, the row count and column types actually found in the file. Re-running
ingestion updates entries in place, so the manifest never accumulates duplicates.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ManifestEntry:
    source: str  # e.g. "tlc_trips"
    url: str
    path: str  # relative to the data directory, so manifests are portable
    bytes: int
    sha256: str
    retrieved_at: str  # UTC ISO-8601
    rows: int | None = None
    columns: dict[str, str] | None = None
    synthetic: bool = False
    usage_note: str = ""


@dataclass
class Manifest:
    entries: dict[str, ManifestEntry] = field(default_factory=dict)
    window: dict[str, str] | None = None  # {"start": ..., "end": ...} covered by this ingestion

    @classmethod
    def load(cls, path: Path) -> Manifest:
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        entries = {k: ManifestEntry(**v) for k, v in raw.get("entries", {}).items()}
        return cls(entries=entries, window=raw.get("window"))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "window": self.window,
            "entries": {k: asdict(v) for k, v in sorted(self.entries.items())},
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.replace(tmp, path)  # atomic: a crash never leaves a half-written manifest

    def upsert(self, entry: ManifestEntry) -> None:
        self.entries[entry.path] = entry

    def get(self, relative_path: str) -> ManifestEntry | None:
        return self.entries.get(relative_path)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
