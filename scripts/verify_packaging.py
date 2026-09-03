#!/usr/bin/env python3
"""Lightweight packaging verification for NeuroBIDS / NeuroPipeline V1.

Static checks always run. Artifact checks run when dist/release outputs exist
(typically after a native Windows or macOS build).

Usage::

    PYTHONPATH=src python scripts/verify_packaging.py
    PYTHONPATH=src python scripts/verify_packaging.py --require-artifacts
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Paths / globs that must never appear in packaging sources.
FORBIDDEN_NAME_PATTERNS = (
    re.compile(r"(^|/)\.env$", re.I),
    re.compile(r"(^|/)\.venv(/|$)", re.I),
    re.compile(r"(^|/)__pycache__(/|$)", re.I),
    re.compile(r"\.(nii|nii\.gz)$", re.I),
)
FORBIDDEN_CONTENT_HINTS = (
    "OPENAI_API_KEY=",
    "NEUROBIDS_LLM_API_KEY=sk-",
)


def _fail(errors: list[str], msg: str) -> None:
    errors.append(msg)


def check_static(errors: list[str], warnings: list[str]) -> None:
    required = [
        ROOT / "scripts" / "build_windows.ps1",
        ROOT / "scripts" / "build_macos.sh",
        ROOT / "installer" / "neuro_pipeline.spec",
        ROOT / "installer" / "setup.iss",
        ROOT / "docs" / "INSTALL.md",
        ROOT / "tools" / "README.txt",
    ]
    for path in required:
        if not path.is_file():
            _fail(errors, f"missing required file: {path.relative_to(ROOT)}")

    iss = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    if "NeuroPipeline_DICOM_Converter_Setup" not in iss:
        _fail(errors, "setup.iss must emit NeuroPipeline_DICOM_Converter_Setup.exe")
    if r"dist\NeuroPipeline\*" not in iss and "dist\\NeuroPipeline\\*" not in iss:
        _fail(errors, "setup.iss must package onedir dist\\NeuroPipeline\\*")
    if "NeuroPipeline.exe" not in iss:
        _fail(errors, "setup.iss must launch NeuroPipeline.exe")
    if "desktopicon" not in iss:
        _fail(errors, "setup.iss must offer a desktop shortcut task")
    if "{uninstallexe}" not in iss:
        _fail(errors, "setup.iss must include an uninstall shortcut")

    ps1 = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    if "neuro_pipeline.spec" not in ps1:
        _fail(errors, "build_windows.ps1 must use installer\\neuro_pipeline.spec")
    if "setup.iss" not in ps1:
        _fail(errors, "build_windows.ps1 must compile installer\\setup.iss")

    macos = (ROOT / "scripts" / "build_macos.sh").read_text(encoding="utf-8")
    if 'uname -s' not in macos or "Darwin" not in macos:
        _fail(errors, "build_macos.sh must refuse non-Darwin hosts")

    # Spec must not hard-code developer machine paths.
    spec = (ROOT / "installer" / "neuro_pipeline.spec").read_text(encoding="utf-8")
    if re.search(r"[A-Z]:\\\\Users\\\\|/home/[a-z]+/", spec):
        _fail(errors, "neuro_pipeline.spec appears to hard-code absolute user paths")
    if ".venv" in spec or "tests/" in spec:
        warnings.append("neuro_pipeline.spec mentions .venv or tests — confirm they are not bundled")

    # Spot-check repo packaging inputs for secrets / large imaging dumps.
    for rel in ("installer", "configs", "scripts", "docs"):
        base = ROOT / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel_s = str(path.relative_to(ROOT)).replace("\\", "/")
            for pat in FORBIDDEN_NAME_PATTERNS:
                if pat.search(rel_s):
                    _fail(errors, f"forbidden packaging input: {rel_s}")
            if path.suffix.lower() in {".dcm", ".nii", ".gz"} and "synthetic" not in rel_s:
                # configs/docs should not ship patient imaging
                if rel in {"installer", "configs", "scripts"}:
                    _fail(errors, f"imaging file under packaging input tree: {rel_s}")
            if path.stat().st_size < 2_000_000 and path.suffix.lower() in {
                ".ps1",
                ".iss",
                ".md",
                ".py",
                ".yaml",
                ".yml",
                ".txt",
                ".spec",
            }:
                # Skip this verifier itself (documents forbidden patterns as strings).
                if path.name == "verify_packaging.py":
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for hint in FORBIDDEN_CONTENT_HINTS:
                    if hint in text:
                        _fail(errors, f"possible secret in {rel_s}")


def check_artifacts(errors: list[str], warnings: list[str], *, require: bool) -> None:
    win_exe = ROOT / "dist" / "NeuroPipeline" / "NeuroPipeline.exe"
    win_setup = ROOT / "release" / "NeuroPipeline_DICOM_Converter_Setup.exe"
    win_dcm = ROOT / "dist" / "NeuroPipeline" / "dcm2niix.exe"
    mac_apps = [
        ROOT / "release" / "NeuroBIDS.app",
        ROOT / "release" / "NeuroPipeline.app",
        ROOT / "dist" / "NeuroBIDS.app",
        ROOT / "dist" / "NeuroPipeline.app",
    ]

    found_any = False
    if win_exe.is_file():
        found_any = True
        if not win_dcm.is_file():
            warnings.append("Windows onedir built but dcm2niix.exe is not bundled next to NeuroPipeline.exe")
        # Quick scan of onedir for obvious junk
        for path in (ROOT / "dist" / "NeuroPipeline").rglob("*"):
            name = path.name.lower()
            if name in {".env", ".gitignore"} or name.endswith(".dcm"):
                _fail(errors, f"forbidden file in Windows dist: {path.relative_to(ROOT)}")
            if name == "__pycache__" and path.is_dir():
                warnings.append("dist contains __pycache__ (prefer clean rebuild)")
        if win_setup.is_file():
            print(f"OK installer: {win_setup.relative_to(ROOT)}")
        else:
            warnings.append(
                "NeuroPipeline.exe exists but Setup.exe is missing "
                "(install Inno Setup 6 and re-run build_windows.ps1)"
            )
        print(f"OK Windows EXE: {win_exe.relative_to(ROOT)}")

    for app in mac_apps:
        if app.is_dir():
            found_any = True
            print(f"OK macOS app: {app.relative_to(ROOT)}")
            break

    if require and not found_any:
        _fail(
            errors,
            "no packaging artifacts found under dist/ or release/ "
            "(build on Windows or macOS first)",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-artifacts",
        action="store_true",
        help="Fail if Windows/macOS build outputs are absent",
    )
    args = parser.parse_args(argv)
    errors: list[str] = []
    warnings: list[str] = []
    check_static(errors, warnings)
    check_artifacts(errors, warnings, require=args.require_artifacts)

    for w in warnings:
        print(f"WARNING: {w}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        print(f"Packaging verification FAILED ({len(errors)} error(s))", file=sys.stderr)
        return 1
    print("Packaging verification PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
