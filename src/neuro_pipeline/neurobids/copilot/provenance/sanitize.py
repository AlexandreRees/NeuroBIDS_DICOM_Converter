"""Privacy scrubbing for Copilot provenance payloads."""

from __future__ import annotations

import hashlib
import re
from typing import Any

_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "bearer",
    "token",
    "password",
    "secret",
    "access_key",
    "private_key",
}
_PHI_KEYS = {
    "patientname",
    "patient_name",
    "patient_birth_date",
    "patientbirthdate",
    "patient_sex",
    "patientssex",
    "patient_id_raw",
}
_BINARY_KEYS = {
    "pixels",
    "pixel_data",
    "pixeldata",
    "dicom_bytes",
    "raw_bytes",
    "image_bytes",
    "blob",
}
_PATH_KEYS = {
    "path",
    "filepath",
    "file_path",
    "source_dir",
    "sample_file",
    "dataset_root",
    "output_root",
    "dicom_root",
}

_MAX_STRING = 2000
_MAX_LIST = 50
_MAX_DEPTH = 6


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def looks_like_absolute_path(value: str) -> bool:
    if value.startswith("/") and "/" in value[1:]:
        return True
    if len(value) > 2 and value[1] == ":" and value[0].isalpha():
        return True
    return False


def looks_like_secret(value: str) -> bool:
    low = value.lower()
    if low.startswith("sk-") or low.startswith("bearer "):
        return True
    if "api_key" in low or "authorization" in low:
        return True
    return False


def sanitize_for_provenance(value: Any, *, depth: int = 0) -> Any:
    """Return a JSON-serializable, privacy-scrubbed copy of ``value``."""
    if depth > _MAX_DEPTH:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, bytes):
        return f"[binary:{len(value)}B]"
    if isinstance(value, str):
        if looks_like_secret(value):
            return "[redacted_secret]"
        if looks_like_absolute_path(value):
            return "[redacted_path]"
        if len(value) > _MAX_STRING:
            return value[:_MAX_STRING] + "…[truncated]"
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            key_l = key_s.lower().replace("-", "_")
            if key_l in _SECRET_KEYS or key_l in _PHI_KEYS:
                out[key_s] = "[redacted]"
                continue
            if key_l in _BINARY_KEYS:
                out[key_s] = "[binary_omitted]"
                continue
            if key_l in _PATH_KEYS or key_l.endswith("_path") or key_l.endswith("_dir"):
                out[key_s] = "[redacted_path]"
                continue
            if key_l == "changeset":
                # Prefer compact dict forms only
                continue
            out[key_s] = sanitize_for_provenance(item, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        items = list(value)[:_MAX_LIST]
        cleaned = [sanitize_for_provenance(v, depth=depth + 1) for v in items]
        if len(value) > _MAX_LIST:
            cleaned.append(f"[truncated:{len(value) - _MAX_LIST}_more]")
        return cleaned
    # Drop live objects (ChangeSet, Path, Qt, etc.)
    name = type(value).__name__
    if name in {"ChangeSet", "Path", "PosixPath", "WindowsPath"}:
        return f"[{name}]"
    return str(value)[:_MAX_STRING]


def scrub_text(text: str, *secrets: str) -> str:
    out = str(text or "")
    for secret in secrets:
        if secret and secret in out:
            out = out.replace(secret, "[redacted_secret]")
    # Common secret patterns
    out = re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-]+", "Bearer [redacted_secret]", out)
    out = re.sub(r"\bsk-[A-Za-z0-9]{8,}\b", "[redacted_secret]", out)
    return out
