from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml


class ConfigError(RuntimeError):
    """Raised when the user configuration is missing required values."""


def _get_value(cfg: Dict[str, Any], key: str, env_key: str | None = None) -> Any:
    """Get value from env var (upper case) or config dict."""
    if env_key:
         val = os.getenv(env_key)
         if val is not None:
             return val
    return cfg.get(key)


def _require_str(cfg: Dict[str, Any], key: str) -> str:
    val = _get_value(cfg, key, key.upper())
    value = str(val or "").strip()
    if not value:
        raise ConfigError(f"Missing `{key}` in config.yaml or {key.upper()} env var")
    return value


def _require_int(
    cfg: Dict[str, Any],
    key: str,
    *,
    positive: bool = False,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    val = _get_value(cfg, key, key.upper())
    try:
        value = int(val)
    except (TypeError, ValueError):
        raise ConfigError(f"`{key}` must be an integer (got {val})")
    if positive and value <= 0:
        raise ConfigError(f"`{key}` must be > 0")
    if minimum is not None and value < minimum:
        raise ConfigError(f"`{key}` must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"`{key}` must be <= {maximum}")
    return value


def load_config(path: str = "config.yaml") -> dict:
    cfg = {}
    config_path = Path(path)
    
    # It's okay if config.yaml doesn't exist IF all env vars are present, 
    # but for simplicity let's try to load it if it exists.
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    
    # We build the final config dict
    final_cfg = {}

    final_cfg["telegram_token"] = _require_str(cfg, "telegram_token")
    final_cfg["admin_id"] = _require_int(cfg, "admin_id")
    final_cfg["daily_limit"] = _require_int(cfg, "daily_limit", positive=True)
    final_cfg["upload_interval_minutes"] = _require_int(cfg, "upload_interval_minutes", positive=True)
    final_cfg["upload_start_hour"] = _require_int(cfg, "upload_start_hour", minimum=0, maximum=23)

    # Paths - allow overriding via env or config, default to relative
    channels_path_str = _get_value(cfg, "channels_path", "CHANNELS_PATH") or "channels"
    channels_path = Path(channels_path_str).expanduser().resolve()
    channels_path.mkdir(parents=True, exist_ok=True)
    final_cfg["channels_path"] = str(channels_path)

    db_path_str = _get_value(cfg, "db_path", "DB_PATH") or "uploads.db"
    db_path = Path(db_path_str).expanduser().resolve()
    db_dir = db_path.parent
    db_dir.mkdir(parents=True, exist_ok=True)
    final_cfg["db_path"] = str(db_path)

    return final_cfg
