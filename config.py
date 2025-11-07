from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


class ConfigError(RuntimeError):
    """Raised when the user configuration is missing required values."""


def _require_str(cfg: Dict[str, Any], key: str) -> str:
    value = str(cfg.get(key, "")).strip()
    if not value:
        raise ConfigError(f"Missing `{key}` in config.yaml")
    return value


def _require_int(
    cfg: Dict[str, Any],
    key: str,
    *,
    positive: bool = False,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        value = int(cfg.get(key))
    except (TypeError, ValueError):
        raise ConfigError(f"`{key}` must be an integer in config.yaml")
    if positive and value <= 0:
        raise ConfigError(f"`{key}` must be > 0 in config.yaml")
    if minimum is not None and value < minimum:
        raise ConfigError(f"`{key}` must be >= {minimum} in config.yaml")
    if maximum is not None and value > maximum:
        raise ConfigError(f"`{key}` must be <= {maximum} in config.yaml")
    return value


def load_config(path: str = "config.yaml") -> dict:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    cfg["telegram_token"] = _require_str(cfg, "telegram_token")
    cfg["admin_id"] = _require_int(cfg, "admin_id")
    cfg["daily_limit"] = _require_int(cfg, "daily_limit", positive=True)
    cfg["upload_interval_minutes"] = _require_int(cfg, "upload_interval_minutes", positive=True)
    cfg["upload_start_hour"] = _require_int(cfg, "upload_start_hour", minimum=0, maximum=23)

    channels_path = Path(cfg.get("channels_path") or "channels").expanduser().resolve()
    channels_path.mkdir(parents=True, exist_ok=True)
    cfg["channels_path"] = str(channels_path)

    db_path = Path(cfg.get("db_path") or "uploads.db").expanduser().resolve()
    db_dir = db_path.parent
    db_dir.mkdir(parents=True, exist_ok=True)
    cfg["db_path"] = str(db_path)

    return cfg
