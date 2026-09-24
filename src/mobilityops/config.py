"""Runtime configuration, read from environment variables.

Everything the app needs to know about its surroundings lives here so that no module reads
``os.environ`` directly and no path or secret is hard-coded elsewhere.

The two data modes never share files: sample (synthetic, for tests and demos) and real
(downloaded NYC TLC + NOAA data) each get their own subdirectory, so synthetic results can
never be mistaken for real-world results.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

Mode = Literal["sample", "real"]
_VALID_MODES = ("sample", "real")
_VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


class ConfigError(ValueError):
    """Raised when the environment holds an invalid or unusable setting."""


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    mode: Mode
    log_level: str
    anthropic_api_key: str | None
    llm_model: str | None
    threads: int = 0  # LightGBM threads; 0 = all cores. Cap it when several jobs share a machine.
    api_key: str | None = None  # if set, every /api/v1 request must send it as X-API-Key
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        mode = e.get("MOBILITYOPS_MODE", "sample").strip().lower()
        if mode not in _VALID_MODES:
            raise ConfigError(f"MOBILITYOPS_MODE must be one of {_VALID_MODES}, got {mode!r}")
        level = e.get("MOBILITYOPS_LOG_LEVEL", "INFO").strip().upper()
        if level not in _VALID_LEVELS:
            raise ConfigError(
                f"MOBILITYOPS_LOG_LEVEL must be one of {_VALID_LEVELS}, got {level!r}"
            )
        key = (e.get("ANTHROPIC_API_KEY") or "").strip() or None
        model = (e.get("MOBILITYOPS_LLM_MODEL") or "").strip() or None
        api_key = (e.get("MOBILITYOPS_API_KEY") or "").strip() or None
        raw_threads = (e.get("MOBILITYOPS_THREADS") or "0").strip()
        if not raw_threads.isdigit() or int(raw_threads) > 256:
            raise ConfigError("MOBILITYOPS_THREADS must be a whole number from 0 to 256")
        origins = tuple(
            o.strip() for o in (e.get("MOBILITYOPS_CORS_ORIGINS") or "").split(",") if o.strip()
        )
        if "*" in origins:
            raise ConfigError("MOBILITYOPS_CORS_ORIGINS must list explicit origins, not '*'")
        extra = {"cors_origins": origins} if origins else {}
        return cls(
            data_dir=Path(e.get("MOBILITYOPS_DATA_DIR", "./data")).expanduser().resolve(),
            mode=mode,  # type: ignore[arg-type]
            log_level=level,
            anthropic_api_key=key,
            llm_model=model,
            threads=int(raw_threads),
            api_key=api_key,
            **extra,
        )

    # ---- derived paths: raw inputs and outputs are separated per mode -------------------
    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw" / self.mode

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed" / self.mode

    @property
    def manifests_dir(self) -> Path:
        return self.data_dir / "manifests" / self.mode

    @property
    def db_path(self) -> Path:
        return self.processed_dir / "mobilityops.duckdb"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir.parent / "artifacts" / self.mode

    @property
    def llm_configured(self) -> bool:
        return self.anthropic_api_key is not None and self.llm_model is not None

    def ensure_dirs(self) -> None:
        for d in (self.raw_dir, self.processed_dir, self.manifests_dir, self.artifacts_dir):
            d.mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:  # never leak the key through logs or tracebacks
        key = "set" if self.anthropic_api_key else "unset"
        api = "set" if self.api_key else "unset"
        return (
            f"Settings(mode={self.mode!r}, data_dir={str(self.data_dir)!r}, "
            f"log_level={self.log_level!r}, anthropic_api_key=<{key}>, "
            f"llm_model={self.llm_model!r}, api_key=<{api}>)"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
