from __future__ import annotations

from dotenv import load_dotenv


load_dotenv()


TRUE_VALUES = {"1", "true", "yes", "on"}


def env_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in TRUE_VALUES
