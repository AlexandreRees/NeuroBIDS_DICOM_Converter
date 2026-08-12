"""SHA-256 hashing helpers for reproducible conversions."""

from __future__ import annotations

import hashlib
from pathlib import Path


class HashManager:
    """Compute SHA-256 digests for files and folder contents."""

    CHUNK = 1024 * 1024

    def hash_file(self, path: Path | str) -> str:
        path = Path(path)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(self.CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def hash_folder(
        self,
        root: Path | str,
        *,
        include_extensions: set[str] | None = None,
        max_files: int | None = None,
    ) -> tuple[str, list[dict[str, str]]]:
        """Hash a directory tree.

        Returns ``(aggregate_sha256, [{path, hash}, ...])`` using relative paths
        sorted for reproducibility. Source data is never modified.
        """
        root_path = Path(root)
        if not root_path.exists():
            return "", []

        records: list[dict[str, str]] = []
        aggregate = hashlib.sha256()
        files = sorted(
            p for p in root_path.rglob("*") if p.is_file() and not p.name.startswith(".")
        )
        if include_extensions is not None:
            norm = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in include_extensions}
            files = [p for p in files if p.suffix.lower() in norm or "".join(p.suffixes[-2:]).lower() in norm]

        if max_files is not None:
            files = files[:max_files]

        for path in files:
            rel = path.relative_to(root_path).as_posix()
            file_hash = self.hash_file(path)
            records.append({"path": rel, "hash": file_hash})
            aggregate.update(rel.encode("utf-8"))
            aggregate.update(b"\0")
            aggregate.update(file_hash.encode("utf-8"))
            aggregate.update(b"\0")

        return aggregate.hexdigest(), records
