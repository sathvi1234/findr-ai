"""Load a local .env file without overriding variables already set in the process."""

import os
from pathlib import Path


def load_env_file(path: Path | None = None) -> None:
    """Read KEY=value lines. Blank lines and comments are ignored. Secrets stay out of logs."""
    env_path = path or Path(".env")
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def mongodb_settings() -> tuple[str | None, str]:
    """Return the Atlas URI and database name. No connection string is built in code."""
    load_env_file()
    uri = (os.environ.get("MONGODB_URI") or "").strip() or None
    database = (os.environ.get("MONGODB_DB") or "findr_ai").strip() or "findr_ai"
    return uri, database
