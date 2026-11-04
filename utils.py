"""Small shared helpers: normalization, stable IDs, JSON/CSV I/O."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

CREDIT_CODE_RE = re.compile(r"^[0-9A-HJ-NP-RT-UW-Y]{18}$")


def normalize_name(value: Any) -> str:
    """NFKC-normalize a Chinese entity name and remove spacing punctuation."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("〔", "(").replace("〕", ")")
    text = re.sub(r"[\s\u3000]+", "", text)
    text = text.replace("·", "").replace("•", "")
    return text.strip().lower()


def normalize_credit_code(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[\s\-]+", "", text).upper()
    return text


def is_valid_credit_code(value: str) -> bool:
    return bool(CREDIT_CODE_RE.fullmatch(normalize_credit_code(value)))


def stable_id(prefix: str, *parts: Any, length: int = 10) -> str:
    payload = "|".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:length].upper()
    return f"{prefix}-{digest}"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=_json_default)
        handle.write("\n")


def json_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def to_native(value: Any) -> Any:
    """Convert numpy/pandas scalar values into JSON-friendly Python values."""
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and value != value:  # NaN
        return None
    return value


def row_to_dict(row: Any) -> dict[str, Any]:
    return {str(key): to_native(value) for key, value in dict(row).items()}


def flags_to_text(flags: Iterable[str]) -> str:
    return "|".join(str(flag) for flag in flags if flag)


def text_to_flags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [part for part in str(value or "").split("|") if part]


def pct(value: float, digits: int = 2) -> str:
    return f"{float(value):.{digits}f}%"


def ensure_within_workspace(path: Path, workspace: Path) -> Path:
    """Fail closed if a caller tries to write outside the workspace."""
    resolved = path.resolve()
    workspace_resolved = workspace.resolve()
    if resolved != workspace_resolved and workspace_resolved not in resolved.parents:
        raise PermissionError(f"Refusing to write outside workspace: {resolved}")
    return resolved
