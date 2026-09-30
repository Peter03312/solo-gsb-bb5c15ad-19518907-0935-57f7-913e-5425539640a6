"""On-disk local storage for uploaded sources and generated parts."""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
SOURCES_DIR = DATA_DIR / "sources"
OUTPUTS_DIR = DATA_DIR / "outputs"

# Ensure directories exist on import as well (covers embedded ASGI test
# clients that do not fire the startup event).
SOURCES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def init_storage(max_age_seconds: int = 24 * 3600) -> None:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    purge(max_age_seconds)


def purge(max_age_seconds: int) -> None:
    cutoff = time.time() - max_age_seconds
    for directory in (SOURCES_DIR, OUTPUTS_DIR):
        if not directory.exists():
            continue
        for entry in directory.iterdir():
            try:
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    entry.unlink()
            except OSError:
                pass


def save_source(data: bytes, suffix: str) -> str:
    file_id = uuid.uuid4().hex
    (SOURCES_DIR / f"{file_id}{suffix}").write_bytes(data)
    return file_id


def source_path(file_id: str) -> Path | None:
    matches = list(SOURCES_DIR.glob(f"{file_id}.*"))
    return matches[0] if matches else None


def load_source(file_id: str) -> bytes:
    path = source_path(file_id)
    if path is None:
        raise FileNotFoundError(file_id)
    return path.read_bytes()


def save_output(file_id: str, data: bytes) -> Path:
    path = OUTPUTS_DIR / f"{file_id}.musicxml"
    path.write_bytes(data)
    return path


def output_path(file_id: str) -> Path | None:
    path = OUTPUTS_DIR / f"{file_id}.musicxml"
    return path if path.exists() else None
