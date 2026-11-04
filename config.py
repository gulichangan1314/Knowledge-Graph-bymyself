"""Configuration loading with environment-variable overrides.

Only files inside the workspace are read. A local ``.env`` is parsed without an
extra dependency so the project remains runnable with the pinned requirements.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE lines without overwriting real environment vars."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


for _candidate in (WORKSPACE_ROOT / ".env", PROJECT_ROOT / ".env"):
    _load_dotenv(_candidate)


def _expand(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name, default if default is not None else "")

        return _ENV_PATTERN.sub(repl, value)
    return value


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load YAML config, expand env vars, and resolve project-relative paths."""
    if path is None:
        path = os.environ.get("ENTERPRISEKG_CONFIG", str(DEFAULT_CONFIG_PATH))
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    config_path = config_path.resolve()

    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    config = _expand(config)

    # Environment wins over YAML so CI and local secrets can be injected.
    config.setdefault("neo4j", {})
    for key, env_name in (
        ("uri", "NEO4J_URI"),
        ("user", "NEO4J_USER"),
        ("password", "NEO4J_PASSWORD"),
        ("database", "NEO4J_DATABASE"),
    ):
        if os.environ.get(env_name):
            config["neo4j"][key] = os.environ[env_name]

    config["_meta"] = {
        "project_root": str(PROJECT_ROOT),
        "workspace_root": str(WORKSPACE_ROOT),
        "config_path": str(config_path),
    }
    for key in ("raw_dir", "processed_dir", "output_dir"):
        raw_value = config.get("paths", {}).get(key)
        if raw_value:
            resolved = (PROJECT_ROOT / raw_value).resolve()
            config["paths"][f"{key}_abs"] = str(resolved)
    return config


def project_path(config: dict[str, Any], key: str) -> Path:
    """Return an absolute path declared under ``paths``."""
    value = config.get("paths", {}).get(f"{key}_abs")
    if not value:
        raise KeyError(f"paths.{key} is not configured")
    path = Path(value)
    path.mkdir(parents=True, exist_ok=True)
    return path


CONFIG = load_config()


def get_config() -> dict[str, Any]:
    return CONFIG
