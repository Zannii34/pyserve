"""Configuration loading — YAML files + defaults."""
import os
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8000,
    "workers": 8,
    "static_root": "public",
    "log_file": None,
    "max_connections_per_ip": 20,
    "rate_limit": {
        "enabled": True,
        "rate": 60,
        "per": 60,
        "burst": 10,
    },
    "cors": {
        "enabled": False,
        "origin": "*",
    },
    "compression": {
        "enabled": True,
        "min_size": 512,
    },
    "ssl": {
        "cert": None,
        "key": None,
    },
}


def _merge(base: Dict, override: Dict) -> Dict:
    """Recursively merge override into base (override wins)."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load config from a YAML file, merged with defaults.

    If path is None, tries ./pyserve.yml then ./pyserve.yaml.
    """
    config = dict(DEFAULT_CONFIG)

    if path is None:
        for candidate in ("pyserve.yml", "pyserve.yaml", ".pyserve.yml"):
            if Path(candidate).exists():
                path = candidate
                break

    if path and Path(path).exists():
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
            config = _merge(config, user_config)
        except ImportError:
            # Fallback: try JSON
            import json
            with open(path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            config = _merge(config, user_config)
        except Exception as e:
            raise RuntimeError(f"Failed to load config {path}: {e}")

    # Environment variable overrides
    if os.environ.get("PYSERVE_HOST"):
        config["host"] = os.environ["PYSERVE_HOST"]
    if os.environ.get("PYSERVE_PORT"):
        try:
            config["port"] = int(os.environ["PYSERVE_PORT"])
        except ValueError:
            pass
    if os.environ.get("PYSERVE_WORKERS"):
        try:
            config["workers"] = int(os.environ["PYSERVE_WORKERS"])
        except ValueError:
            pass
    if os.environ.get("PORT"):
        # Render/Heroku convention
        try:
            config["port"] = int(os.environ["PORT"])
            config["host"] = "0.0.0.0"
        except ValueError:
            pass

    return config