"""Deterministic DICOM UID remapping for de-identification."""

from __future__ import annotations

import hashlib
import re

# DICOM UID max length is 64 characters.
_MAX_UID_LENGTH: int = 64


class UidRemapper:
    """Map original UIDs to deterministic anonymized UIDs within one subject."""

    def __init__(self, namespace: str) -> None:
        """Initialize remapper scoped to *namespace* (typically anonymized subject ID)."""
        self._namespace = namespace
        self._cache: dict[str, str] = {}

    def remap(self, original_uid: str) -> str:
        """Return a stable remapped UID for *original_uid*."""
        uid = original_uid.strip()
        if not uid:
            return uid
        if uid in self._cache:
            return self._cache[uid]
        remapped = self._generate_uid(uid)
        self._cache[uid] = remapped
        return remapped

    @property
    def mapping(self) -> dict[str, str]:
        """Return a copy of the original→remapped UID table."""
        return dict(self._cache)

    def _generate_uid(self, original_uid: str) -> str:
        """Generate a DICOM-compliant UID using SHA-256 (2.25.* OID style)."""
        digest = hashlib.sha256(
            f"{self._namespace}|{original_uid}".encode("utf-8")
        ).hexdigest()
        # 2.25.{integer} — UUID-based OID representation per DICOM convention.
        integer = int(digest, 16)
        candidate = f"2.25.{integer}"
        if len(candidate) <= _MAX_UID_LENGTH:
            return candidate
        return candidate[:_MAX_UID_LENGTH]


def is_valid_dicom_uid(uid: str) -> bool:
    """Return True if *uid* matches DICOM UID syntax (basic check)."""
    if not uid or len(uid) > _MAX_UID_LENGTH:
        return False
    return bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", uid))
