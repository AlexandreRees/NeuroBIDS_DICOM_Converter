#!/usr/bin/env python3
"""Extract FreeSurfer 7.4.1 anatomy for future MRIQC T1w models M1–M4.

Reads recon-all outputs under the project SUBJECTS_DIR (FreeSurfer 7.4.1
only). Does not fit models, does not rerun MRIQC, and does not modify
``metadata/mriqc_iqm_physical_acquisition.tsv`` or completed IQM analyses.

HCP / FreeSurfer 6.0.1 trees (``aim2_processed_data``) are rejected.

On Narval, from ``study/``:

  python3 code/extract_freesurfer_anatomy.py
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import fail, require_file  # noqa: E402
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    EXPECTED_PHYSICAL_N,
    assert_unmodified,
    file_sha256,
    snapshot_protected,
    study_root_default,
)

LOGGER = logging.getLogger("mriqc_iqm.freesurfer_anatomy")

REQUIRED_FS_VERSION = "7.4.1"
FORBIDDEN_SUBJECTS_DIR_PARTS = (
    "aim2_processed_data",
    "structural_indwi",
    "sub-C01",
)
VISUAL_REGIONS = ("pericalcarine", "cuneus", "lingual", "lateraloccipital")
ANATOMY_VALUE_COLUMNS = (
    "Euler_L",
    "Euler_R",
    "Euler_mean",
    "Euler_asymmetry",
    "eTIV",
    "BrainSegVol",
    "CortexVol",
    "CerebralWhiteMatterVol",
    "mean_cortical_thickness",
    "total_cortical_volume",
    "total_cortical_surface_area",
    "pericalcarine_thickness",
    "cuneus_thickness",
    "lingual_thickness",
    "lateraloccipital_thickness",
    "visual_cortex_mean_thickness",
)
TABLE_COLUMNS = (
    "subject",
    "subject_id",
    "session",
    "cohort",
    "age",
    "sex",
    "freesurfer_id",
    "freesurfer_version",
    "freesurfer_input_run",
    "freesurfer_input_t1w",
    "processing_status",
    "FS_success",
    "aseg_stats_available",
    "lh_aparc_stats_available",
    "rh_aparc_stats_available",
    "euler_available",
    "n_anatomy_missing",
    "missing_anatomy_variables",
    "n_mriqc_physical_acq_in_session",
    *ANATOMY_VALUE_COLUMNS,
)

# Keep completed IQM artefacts and the canonical physical-acquisition table
# read-only. This list is local so the shared analysis library is unchanged.
EXTRA_PROTECTED_RELATIVE = ("metadata/mriqc_iqm_physical_acquisition.tsv",)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--study-root", type=Path, default=None)
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--subjects-dir", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--iqm-tsv", type=Path, default=None)
    parser.add_argument("--out-tsv", type=Path, default=None)
    parser.add_argument("--out-dictionary", type=Path, default=None)
    args = parser.parse_args(argv)
    study_root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    project_root = args.project_root.resolve() if args.project_root else study_root.parent
    args.study_root = study_root
    args.project_root = project_root
    args.subjects_dir = (
        args.subjects_dir.resolve()
        if args.subjects_dir
        else project_root / "derivatives" / "freesurfer"
    )
    args.manifest = (
        args.manifest.resolve()
        if args.manifest
        else project_root / "metadata" / "freesurfer_manifest.tsv"
    )
    args.iqm_tsv = (
        args.iqm_tsv.resolve()
        if args.iqm_tsv
        else study_root / "metadata" / "mriqc_iqm_physical_acquisition.tsv"
    )
    args.out_tsv = (
        args.out_tsv.resolve()
        if args.out_tsv
        else study_root / "metadata" / "freesurfer_anatomy.tsv"
    )
    args.out_dictionary = (
        args.out_dictionary.resolve()
        if args.out_dictionary
        else study_root / "metadata" / "freesurfer_anatomy_dictionary.tsv"
    )
    return args


def configure_logging() -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    LOGGER.addHandler(handler)


def snapshot_all(study_root: Path) -> dict[Path, str]:
    before = snapshot_protected(study_root)
    for rel in EXTRA_PROTECTED_RELATIVE:
        path = study_root / rel
        require_file(path, "protected table")
        before[path] = file_sha256(path)
    return before


def reject_forbidden_subjects_dir(subjects_dir: Path) -> None:
    resolved = str(subjects_dir.resolve())
    for part in FORBIDDEN_SUBJECTS_DIR_PARTS:
        if part in resolved:
            fail(
                f"Refusing SUBJECTS_DIR {subjects_dir}: path contains {part!r}. "
                "FreeSurfer 6.0.1 / HCP outputs must not be mixed with 7.4.1."
            )
    desc = subjects_dir / "dataset_description.json"
    if desc.is_file():
        try:
            payload = json.loads(desc.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"Cannot parse {desc}: {exc}")
        generated = payload.get("GeneratedBy") or []
        versions = [str(item.get("Version") or "") for item in generated if isinstance(item, dict)]
        name = str(payload.get("Name") or "")
        if "SUBC" in name.upper() or "SUBG" in name.upper():
            fail(f"Refusing SUBJECTS_DIR {subjects_dir}: dataset_description Name={name!r}")
        if versions and not any(REQUIRED_FS_VERSION in v for v in versions):
            fail(
                f"Refusing SUBJECTS_DIR {subjects_dir}: GeneratedBy versions {versions} "
                f"do not include {REQUIRED_FS_VERSION}."
            )


def is_valid_recon_all_done(path: Path) -> bool:
    """True only for a real FreeSurfer done marker, not a stub file."""
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return "SUBJECT" in text and "END_TIME" in text


def classify_status(subj: Path) -> str:
    scripts = subj / "scripts"
    done = scripts / "recon-all.done"
    if is_valid_recon_all_done(done):
        return "COMPLETED"
    if list(scripts.glob("IsRunning*")):
        return "RUNNING/UNKNOWN"
    if (scripts / "recon-all.error").is_file() or (scripts / "recon-all.log").is_file():
        return "FAILED"
    if done.is_file():
        # Stub marker (e.g. a two-byte "1") is not a successful recon-all.
        return "FAILED"
    if subj.is_dir():
        return "RUNNING/UNKNOWN"
    return "NOT_STARTED"


def freesurfer_version(subj: Path) -> str:
    stamp = subj / "scripts" / "build-stamp.txt"
    if stamp.is_file():
        text = stamp.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            return text.splitlines()[0].strip()
    return ""


def is_fs_741(version: str) -> bool:
    return REQUIRED_FS_VERSION in version


def parse_measures(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line.startswith("# Measure"):
            continue
        parts = [p.strip() for p in line[len("# Measure") :].split(",")]
        if len(parts) < 4:
            continue
        value = parts[-2]
        try:
            float(value)
        except ValueError:
            continue
        for label in parts[:-2]:
            if label:
                out[label] = value
    return out


def parse_aparc_table(path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return out
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    headers: list[str] | None = None
    for line in lines:
        if line.startswith("# ColHeaders"):
            headers = line.split()[2:]
            break
    if not headers or "StructName" not in headers:
        return out
    i_name = headers.index("StructName")
    for line in lines:
        if not line or line.startswith("#"):
            continue
        cols = line.split()
        if len(cols) <= i_name:
            continue
        rec = {}
        for idx, header in enumerate(headers):
            if idx < len(cols):
                rec[header] = cols[idx]
        out[cols[i_name]] = rec
    return out


def as_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number


def fmt_int_if_whole(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def fmt_float(value: float, digits: int = 6) -> str:
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def area_weighted_thickness(
    lh_row: dict[str, str] | None,
    rh_row: dict[str, str] | None,
) -> str:
    if not lh_row or not rh_row:
        return ""
    lh_t = as_float(lh_row.get("ThickAvg"))
    rh_t = as_float(rh_row.get("ThickAvg"))
    lh_a = as_float(lh_row.get("SurfArea"))
    rh_a = as_float(rh_row.get("SurfArea"))
    if None in (lh_t, rh_t, lh_a, rh_a):
        return ""
    if lh_a <= 0 or rh_a <= 0:
        return ""
    return fmt_float((lh_t * lh_a + rh_t * rh_a) / (lh_a + rh_a))


def load_manifest(path: Path) -> list[dict[str, str]]:
    require_file(path, "FreeSurfer manifest")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    need = {"subject_id", "session", "freesurfer_id", "t1w_path", "run"}
    missing = need - set(rows[0].keys() if rows else [])
    if not rows:
        fail(f"Empty FreeSurfer manifest: {path}")
    if missing:
        fail(f"FreeSurfer manifest missing columns: {sorted(missing)}")
    return rows


def load_iqm_demographics(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    require_file(path, "physical-acquisition IQM table")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != EXPECTED_PHYSICAL_N:
        fail(f"Expected {EXPECTED_PHYSICAL_N} IQM rows in {path}, found {len(rows)}.")
    need = {"subject_id", "session", "cohort", "age", "sex"}
    missing = need - set(rows[0].keys() if rows else [])
    if missing:
        fail(f"IQM table missing columns: {sorted(missing)}")

    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        key = (row["subject_id"].strip(), row["session"].strip())
        grouped.setdefault(key, []).append(row)

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for key, cluster in grouped.items():
        demo_keys = {(r["cohort"].strip(), r["age"].strip(), r["sex"].strip()) for r in cluster}
        if len(demo_keys) != 1:
            fail(f"Conflicting cohort/age/sex for {key}: {sorted(demo_keys)}")
        first = cluster[0]
        out[key] = {
            "cohort": first["cohort"].strip(),
            "age": first["age"].strip(),
            "sex": first["sex"].strip(),
            "n_mriqc_physical_acq_in_session": str(len(cluster)),
        }
    return out


def extract_anatomy(subj: Path) -> dict[str, str]:
    values = {name: "" for name in ANATOMY_VALUE_COLUMNS}
    aseg_path = subj / "stats" / "aseg.stats"
    lh_path = subj / "stats" / "lh.aparc.stats"
    rh_path = subj / "stats" / "rh.aparc.stats"
    aseg = parse_measures(aseg_path)
    lh_meas = parse_measures(lh_path)
    rh_meas = parse_measures(rh_path)
    lh_table = parse_aparc_table(lh_path)
    rh_table = parse_aparc_table(rh_path)

    lh_holes = as_float(aseg.get("lhSurfaceHoles"))
    rh_holes = as_float(aseg.get("rhSurfaceHoles"))
    if lh_holes is not None and rh_holes is not None:
        euler_l = 2.0 - 2.0 * lh_holes
        euler_r = 2.0 - 2.0 * rh_holes
        values["Euler_L"] = fmt_int_if_whole(euler_l)
        values["Euler_R"] = fmt_int_if_whole(euler_r)
        values["Euler_mean"] = fmt_int_if_whole((euler_l + euler_r) / 2.0)
        values["Euler_asymmetry"] = fmt_int_if_whole(abs(euler_l - euler_r))

    etiv = aseg.get("eTIV") or aseg.get("EstimatedTotalIntraCranialVol")
    brainseg = aseg.get("BrainSegVol") or aseg.get("BrainSeg")
    cortex = aseg.get("CortexVol") or aseg.get("Cortex")
    wm = aseg.get("CerebralWhiteMatterVol") or aseg.get("CerebralWhiteMatter")
    values["eTIV"] = etiv or ""
    values["BrainSegVol"] = brainseg or ""
    values["CortexVol"] = cortex or ""
    values["CerebralWhiteMatterVol"] = wm or ""
    values["total_cortical_volume"] = cortex or ""

    lh_thick = as_float(lh_meas.get("lhMeanThickness") or lh_meas.get("MeanThickness"))
    rh_thick = as_float(rh_meas.get("rhMeanThickness") or rh_meas.get("MeanThickness"))
    if lh_thick is not None and rh_thick is not None:
        values["mean_cortical_thickness"] = fmt_float((lh_thick + rh_thick) / 2.0)

    lh_area = as_float(lh_meas.get("WhiteSurfArea"))
    rh_area = as_float(rh_meas.get("WhiteSurfArea"))
    if lh_area is not None and rh_area is not None:
        values["total_cortical_surface_area"] = fmt_float(lh_area + rh_area, digits=4)

    regional: list[float] = []
    regional_ok = True
    for region in VISUAL_REGIONS:
        combined = area_weighted_thickness(lh_table.get(region), rh_table.get(region))
        values[f"{region}_thickness"] = combined
        parsed = as_float(combined)
        if parsed is None:
            regional_ok = False
        else:
            regional.append(parsed)
    if regional_ok and len(regional) == len(VISUAL_REGIONS):
        values["visual_cortex_mean_thickness"] = fmt_float(sum(regional) / len(regional))
    return values


def empty_row() -> dict[str, str]:
    return {name: "" for name in TABLE_COLUMNS}


def bool_str(flag: bool) -> str:
    return "True" if flag else "False"


def dictionary_rows() -> list[dict[str, str]]:
    version = REQUIRED_FS_VERSION
    rows = [
        {
            "variable": "subject",
            "hypothesis_level": "id",
            "role": "identifier",
            "source_file": "metadata/freesurfer_manifest.tsv; study/metadata/mriqc_iqm_physical_acquisition.tsv",
            "source_section": "subject_id",
            "unit": "label",
            "definition": "BIDS participant label (sub-XXX).",
            "derivation": "Copied from the FreeSurfer manifest; identical to subject_id.",
            "freesurfer_version": version,
            "notes": "Join key with the MRIQC physical-acquisition table.",
        },
        {
            "variable": "subject_id",
            "hypothesis_level": "id",
            "role": "identifier",
            "source_file": "metadata/freesurfer_manifest.tsv",
            "source_section": "subject_id",
            "unit": "label",
            "definition": "Same value as subject; MRIQC column name.",
            "derivation": "Copied.",
            "freesurfer_version": version,
            "notes": "Provided so the anatomy table joins on subject_id without renaming.",
        },
        {
            "variable": "session",
            "hypothesis_level": "id",
            "role": "identifier",
            "source_file": "metadata/freesurfer_manifest.tsv",
            "source_section": "session",
            "unit": "label",
            "definition": "BIDS session (ses-01 or ses-02).",
            "derivation": "Copied.",
            "freesurfer_version": version,
            "notes": "One FreeSurfer recon-all per subject×session.",
        },
        {
            "variable": "cohort",
            "hypothesis_level": "M0",
            "role": "demographic",
            "source_file": "study/metadata/mriqc_iqm_physical_acquisition.tsv",
            "source_section": "cohort",
            "unit": "label",
            "definition": "Control, Glaucoma, Data_ON, or Data_TON.",
            "derivation": "Copied from the MRIQC table; not recomputed.",
            "freesurfer_version": version,
            "notes": "The MRIQC table is not modified.",
        },
        {
            "variable": "age",
            "hypothesis_level": "M0",
            "role": "demographic",
            "source_file": "study/metadata/mriqc_iqm_physical_acquisition.tsv",
            "source_section": "age",
            "unit": "years",
            "definition": "Age used in the existing MRIQC mixed models.",
            "derivation": "Copied.",
            "freesurfer_version": version,
            "notes": "Must match within subject×session; extraction fails if it does not.",
        },
        {
            "variable": "sex",
            "hypothesis_level": "M0",
            "role": "demographic",
            "source_file": "study/metadata/mriqc_iqm_physical_acquisition.tsv",
            "source_section": "sex",
            "unit": "label",
            "definition": "Sex used in the existing MRIQC mixed models.",
            "derivation": "Copied.",
            "freesurfer_version": version,
            "notes": "",
        },
        {
            "variable": "freesurfer_id",
            "hypothesis_level": "provenance",
            "role": "identifier",
            "source_file": "metadata/freesurfer_manifest.tsv",
            "source_section": "freesurfer_id",
            "unit": "label",
            "definition": "SUBJECTS_DIR folder name (sub-XXX_ses-YY).",
            "derivation": "Copied.",
            "freesurfer_version": version,
            "notes": "Never a SUBC/SUBG HCP identifier.",
        },
        {
            "variable": "freesurfer_version",
            "hypothesis_level": "QC",
            "role": "provenance",
            "source_file": "scripts/build-stamp.txt",
            "source_section": "first line",
            "unit": "label",
            "definition": "FreeSurfer build stamp of this recon-all.",
            "derivation": "Copied. Anatomy is extracted only if the stamp contains 7.4.1.",
            "freesurfer_version": version,
            "notes": "FreeSurfer 6.0.1 / HCP outputs are never used.",
        },
        {
            "variable": "freesurfer_input_run",
            "hypothesis_level": "provenance",
            "role": "provenance",
            "source_file": "metadata/freesurfer_manifest.tsv",
            "source_section": "run",
            "unit": "label",
            "definition": "BIDS run of the T1w used as recon-all -i.",
            "derivation": "Copied.",
            "freesurfer_version": version,
            "notes": "Often the lowest T1w_MPR run (frequently non-NORM). The MRIQC table prefers NORM when a pair exists. Anatomy is session-level, not reconstruction-level.",
        },
        {
            "variable": "freesurfer_input_t1w",
            "hypothesis_level": "provenance",
            "role": "provenance",
            "source_file": "metadata/freesurfer_manifest.tsv",
            "source_section": "t1w_path",
            "unit": "path",
            "definition": "Original bids/ T1w NIfTI passed to recon-all.",
            "derivation": "Copied.",
            "freesurfer_version": version,
            "notes": "Source T1w is not defaced; this is the 7.4.1 campaign input, not the release T1w.",
        },
        {
            "variable": "processing_status",
            "hypothesis_level": "QC",
            "role": "qc_flag",
            "source_file": "scripts/recon-all.done; scripts/recon-all.log; scripts/IsRunning*",
            "source_section": "file presence",
            "unit": "label",
            "definition": "COMPLETED, FAILED, RUNNING/UNKNOWN, or NOT_STARTED.",
            "derivation": "COMPLETED only if scripts/recon-all.done contains SUBJECT and END_TIME. A stub done file (e.g. '1') with recon-all.error is FAILED.",
            "freesurfer_version": version,
            "notes": "Stricter than code/check_freesurfer_status.py, which treats any recon-all.done as complete. Failed rows are retained with missing anatomy. No Euler exclusion.",
        },
        {
            "variable": "FS_success",
            "hypothesis_level": "QC",
            "role": "qc_flag",
            "source_file": "scripts/recon-all.done; scripts/build-stamp.txt",
            "source_section": "file presence + version",
            "unit": "boolean",
            "definition": "True if recon-all finished (valid done marker) and the build stamp contains 7.4.1.",
            "derivation": "processing_status==COMPLETED and version contains 7.4.1.",
            "freesurfer_version": version,
            "notes": "Does not imply every stats file is present. No automatic row drop.",
        },
        {
            "variable": "aseg_stats_available",
            "hypothesis_level": "QC",
            "role": "qc_flag",
            "source_file": "stats/aseg.stats",
            "source_section": "file presence",
            "unit": "boolean",
            "definition": "True if aseg.stats exists.",
            "derivation": "Path.is_file().",
            "freesurfer_version": version,
            "notes": "",
        },
        {
            "variable": "lh_aparc_stats_available",
            "hypothesis_level": "QC",
            "role": "qc_flag",
            "source_file": "stats/lh.aparc.stats",
            "source_section": "file presence",
            "unit": "boolean",
            "definition": "True if lh.aparc.stats (Desikan-Killiany) exists.",
            "derivation": "Path.is_file().",
            "freesurfer_version": version,
            "notes": "DKT and a2009s parcellations are not used.",
        },
        {
            "variable": "rh_aparc_stats_available",
            "hypothesis_level": "QC",
            "role": "qc_flag",
            "source_file": "stats/rh.aparc.stats",
            "source_section": "file presence",
            "unit": "boolean",
            "definition": "True if rh.aparc.stats (Desikan-Killiany) exists.",
            "derivation": "Path.is_file().",
            "freesurfer_version": version,
            "notes": "",
        },
        {
            "variable": "euler_available",
            "hypothesis_level": "QC",
            "role": "qc_flag",
            "source_file": "stats/aseg.stats",
            "source_section": "# Measure lhSurfaceHoles / rhSurfaceHoles",
            "unit": "boolean",
            "definition": "True if both Euler_L and Euler_R could be derived.",
            "derivation": "Both SurfaceHoles measures parse as finite numbers.",
            "freesurfer_version": version,
            "notes": "No Euler threshold is applied.",
        },
        {
            "variable": "n_anatomy_missing",
            "hypothesis_level": "QC",
            "role": "qc_flag",
            "source_file": "derived",
            "source_section": "",
            "unit": "count",
            "definition": "Number of anatomy value columns that are empty.",
            "derivation": "Count of empty ANATOMY_VALUE_COLUMNS.",
            "freesurfer_version": version,
            "notes": "Failed reconstructions typically miss all anatomy values.",
        },
        {
            "variable": "missing_anatomy_variables",
            "hypothesis_level": "QC",
            "role": "qc_flag",
            "source_file": "derived",
            "source_section": "",
            "unit": "label_list",
            "definition": "Semicolon-separated anatomy columns that are empty.",
            "derivation": "Join of empty ANATOMY_VALUE_COLUMNS names.",
            "freesurfer_version": version,
            "notes": "Empty string if none missing.",
        },
        {
            "variable": "n_mriqc_physical_acq_in_session",
            "hypothesis_level": "join",
            "role": "join_note",
            "source_file": "study/metadata/mriqc_iqm_physical_acquisition.tsv",
            "source_section": "row count per subject×session",
            "unit": "count",
            "definition": "How many MRIQC physical-acquisition rows share this session.",
            "derivation": "Count of IQM rows with the same subject_id and session.",
            "freesurfer_version": version,
            "notes": "Equals 2 only for sub-043 ses-02. Anatomy stays one row per session.",
        },
        {
            "variable": "Euler_L",
            "hypothesis_level": "M1",
            "role": "reconstruction_quality",
            "source_file": "stats/aseg.stats",
            "source_section": "# Measure lhSurfaceHoles",
            "unit": "unitless",
            "definition": "Left-hemisphere Euler number of the orig surface before topology fix.",
            "derivation": "Euler_L = 2 - 2 * lhSurfaceHoles. Matches mris_euler_number on surf/lh.orig.nofix.",
            "freesurfer_version": version,
            "notes": "Do not enter Euler_L, Euler_R, and Euler_mean in the same model. Primary M1 covariate is Euler_mean.",
        },
        {
            "variable": "Euler_R",
            "hypothesis_level": "M1",
            "role": "reconstruction_quality",
            "source_file": "stats/aseg.stats",
            "source_section": "# Measure rhSurfaceHoles",
            "unit": "unitless",
            "definition": "Right-hemisphere Euler number before topology fix.",
            "derivation": "Euler_R = 2 - 2 * rhSurfaceHoles.",
            "freesurfer_version": version,
            "notes": "Secondary to Euler_mean. Not a default co-entered term.",
        },
        {
            "variable": "Euler_mean",
            "hypothesis_level": "M1",
            "role": "primary_reconstruction_quality",
            "source_file": "stats/aseg.stats",
            "source_section": "lhSurfaceHoles and rhSurfaceHoles",
            "unit": "unitless",
            "definition": "Mean of left and right pre-fix Euler numbers.",
            "derivation": "(Euler_L + Euler_R) / 2.",
            "freesurfer_version": version,
            "notes": "Primary M1 covariate. A sphere has Euler 2; more negative values indicate more topological defects.",
        },
        {
            "variable": "Euler_asymmetry",
            "hypothesis_level": "M1",
            "role": "secondary_reconstruction_quality",
            "source_file": "stats/aseg.stats",
            "source_section": "derived from Euler_L and Euler_R",
            "unit": "unitless",
            "definition": "Absolute left–right Euler difference.",
            "derivation": "|Euler_L - Euler_R|.",
            "freesurfer_version": version,
            "notes": "Secondary only. Not auto-selected as the M1 primary term.",
        },
        {
            "variable": "eTIV",
            "hypothesis_level": "M2",
            "role": "primary_global_brain_size",
            "source_file": "stats/aseg.stats",
            "source_section": "# Measure EstimatedTotalIntraCranialVol, eTIV",
            "unit": "mm^3",
            "definition": "Estimated total intracranial volume.",
            "derivation": "FreeSurfer atlas scaling (eTIV), not BrainSegVol.",
            "freesurfer_version": version,
            "notes": "Primary M2 global-size covariate when a single size term is appropriate. Do not enter eTIV together with BrainSegVol/CortexVol/CerebralWhiteMatterVol by default.",
        },
        {
            "variable": "BrainSegVol",
            "hypothesis_level": "M2",
            "role": "global_brain_size",
            "source_file": "stats/aseg.stats",
            "source_section": "# Measure BrainSeg, BrainSegVol",
            "unit": "mm^3",
            "definition": "Brain segmentation volume (includes ventricles).",
            "derivation": "Copied from aseg Measure BrainSegVol.",
            "freesurfer_version": version,
            "notes": "Available; not the default M2 term. Highly related to eTIV.",
        },
        {
            "variable": "CortexVol",
            "hypothesis_level": "M2",
            "role": "global_brain_size",
            "source_file": "stats/aseg.stats",
            "source_section": "# Measure Cortex, CortexVol",
            "unit": "mm^3",
            "definition": "Total cortical gray-matter volume (both hemispheres).",
            "derivation": "Copied from aseg Measure CortexVol.",
            "freesurfer_version": version,
            "notes": "Same FreeSurfer quantity as total_cortical_volume. Listed under M2 as a global size candidate and under M3 as cortical morphometry. Do not enter both columns in one model.",
        },
        {
            "variable": "CerebralWhiteMatterVol",
            "hypothesis_level": "M2",
            "role": "global_brain_size",
            "source_file": "stats/aseg.stats",
            "source_section": "# Measure CerebralWhiteMatter, CerebralWhiteMatterVol",
            "unit": "mm^3",
            "definition": "Total cerebral white-matter volume.",
            "derivation": "Copied from aseg Measure CerebralWhiteMatterVol.",
            "freesurfer_version": version,
            "notes": "Available; not the default M2 term.",
        },
        {
            "variable": "mean_cortical_thickness",
            "hypothesis_level": "M3",
            "role": "primary_cortical_morphology",
            "source_file": "stats/lh.aparc.stats; stats/rh.aparc.stats",
            "source_section": "# Measure Cortex, MeanThickness",
            "unit": "mm",
            "definition": "Whole-cortex mean thickness, unweighted mean of the two hemispheres.",
            "derivation": "(lh MeanThickness + rh MeanThickness) / 2.",
            "freesurfer_version": version,
            "notes": "Primary M3 covariate. Do not automatically co-enter with total_cortical_volume or total_cortical_surface_area.",
        },
        {
            "variable": "total_cortical_volume",
            "hypothesis_level": "M3",
            "role": "cortical_morphology",
            "source_file": "stats/aseg.stats",
            "source_section": "# Measure Cortex, CortexVol",
            "unit": "mm^3",
            "definition": "Total cortical gray-matter volume.",
            "derivation": "Identical source value to CortexVol.",
            "freesurfer_version": version,
            "notes": "Kept as a separate M3 column by design. Not a second independent volume measure.",
        },
        {
            "variable": "total_cortical_surface_area",
            "hypothesis_level": "M3",
            "role": "cortical_morphology",
            "source_file": "stats/lh.aparc.stats; stats/rh.aparc.stats",
            "source_section": "# Measure Cortex, WhiteSurfArea",
            "unit": "mm^2",
            "definition": "Total white-surface area (both hemispheres).",
            "derivation": "lh WhiteSurfArea + rh WhiteSurfArea.",
            "freesurfer_version": version,
            "notes": "White/gray boundary area, not pial. Not a default co-entered M3 term.",
        },
        {
            "variable": "pericalcarine_thickness",
            "hypothesis_level": "M4",
            "role": "visual_cortex_thickness",
            "source_file": "stats/lh.aparc.stats; stats/rh.aparc.stats",
            "source_section": "Desikan-Killiany row pericalcarine, column ThickAvg (area-weighted across hemispheres)",
            "unit": "mm",
            "definition": "Bilateral pericalcarine mean cortical thickness.",
            "derivation": "(lh.ThickAvg*lh.SurfArea + rh.ThickAvg*rh.SurfArea) / (lh.SurfArea + rh.SurfArea).",
            "freesurfer_version": version,
            "notes": "Secondary visual analysis only. No mass-univariate DK sweep.",
        },
        {
            "variable": "cuneus_thickness",
            "hypothesis_level": "M4",
            "role": "visual_cortex_thickness",
            "source_file": "stats/lh.aparc.stats; stats/rh.aparc.stats",
            "source_section": "Desikan-Killiany row cuneus, ThickAvg",
            "unit": "mm",
            "definition": "Bilateral cuneus mean cortical thickness.",
            "derivation": "Area-weighted mean of lh/rh ThickAvg.",
            "freesurfer_version": version,
            "notes": "Secondary.",
        },
        {
            "variable": "lingual_thickness",
            "hypothesis_level": "M4",
            "role": "visual_cortex_thickness",
            "source_file": "stats/lh.aparc.stats; stats/rh.aparc.stats",
            "source_section": "Desikan-Killiany row lingual, ThickAvg",
            "unit": "mm",
            "definition": "Bilateral lingual mean cortical thickness.",
            "derivation": "Area-weighted mean of lh/rh ThickAvg.",
            "freesurfer_version": version,
            "notes": "Secondary.",
        },
        {
            "variable": "lateraloccipital_thickness",
            "hypothesis_level": "M4",
            "role": "visual_cortex_thickness",
            "source_file": "stats/lh.aparc.stats; stats/rh.aparc.stats",
            "source_section": "Desikan-Killiany row lateraloccipital, ThickAvg",
            "unit": "mm",
            "definition": "Bilateral lateral occipital mean cortical thickness.",
            "derivation": "Area-weighted mean of lh/rh ThickAvg.",
            "freesurfer_version": version,
            "notes": "Secondary. This region is larger than the other three; the composite below uses equal region weights, not vertex weights.",
        },
        {
            "variable": "visual_cortex_mean_thickness",
            "hypothesis_level": "M4",
            "role": "primary_visual_composite",
            "source_file": "stats/lh.aparc.stats; stats/rh.aparc.stats",
            "source_section": "pre-specified mean of four DK visual regions",
            "unit": "mm",
            "definition": "Equal-weight mean of pericalcarine, cuneus, lingual, and lateraloccipital bilateral thicknesses.",
            "derivation": "Mean of the four regional thickness columns. Missing if any of the four is missing.",
            "freesurfer_version": version,
            "notes": "Primary M4 term. Secondary/pathology-relevant analysis. Do not interpret an IQM association as a visual-system disease effect.",
        },
    ]
    return rows


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()
    before = snapshot_all(args.study_root)
    reject_forbidden_subjects_dir(args.subjects_dir)
    require_file(args.subjects_dir / "dataset_description.json", "FreeSurfer dataset_description")

    manifest = load_manifest(args.manifest)
    demographics = load_iqm_demographics(args.iqm_tsv)

    rows: list[dict[str, str]] = []
    n_success = 0
    n_wrong_version = 0
    n_completed_missing = 0

    for item in manifest:
        subject = item["subject_id"].strip()
        session = item["session"].strip()
        fs_id = item["freesurfer_id"].strip()
        key = (subject, session)
        if key not in demographics:
            fail(f"Manifest session {key} is absent from the MRIQC physical-acquisition table.")
        demo = demographics[key]
        subj = args.subjects_dir / fs_id
        status = classify_status(subj)
        version = freesurfer_version(subj)
        version_ok = is_fs_741(version)
        if version and not version_ok:
            n_wrong_version += 1
            LOGGER.warning("Skipping anatomy for %s: version %s is not %s", fs_id, version, REQUIRED_FS_VERSION)

        rec = empty_row()
        rec.update(
            {
                "subject": subject,
                "subject_id": subject,
                "session": session,
                "cohort": demo["cohort"],
                "age": demo["age"],
                "sex": demo["sex"],
                "freesurfer_id": fs_id,
                "freesurfer_version": version,
                "freesurfer_input_run": item.get("run", "").strip(),
                "freesurfer_input_t1w": item.get("t1w_path", "").strip(),
                "processing_status": status,
                "n_mriqc_physical_acq_in_session": demo["n_mriqc_physical_acq_in_session"],
            }
        )
        aseg_ok = (subj / "stats" / "aseg.stats").is_file()
        lh_ok = (subj / "stats" / "lh.aparc.stats").is_file()
        rh_ok = (subj / "stats" / "rh.aparc.stats").is_file()
        rec["aseg_stats_available"] = bool_str(aseg_ok)
        rec["lh_aparc_stats_available"] = bool_str(lh_ok)
        rec["rh_aparc_stats_available"] = bool_str(rh_ok)

        fs_success = status == "COMPLETED" and version_ok
        rec["FS_success"] = bool_str(fs_success)
        if fs_success:
            rec.update(extract_anatomy(subj))
            n_success += 1
        rec["euler_available"] = bool_str(rec["Euler_L"] != "" and rec["Euler_R"] != "")
        missing = [name for name in ANATOMY_VALUE_COLUMNS if rec[name] == ""]
        rec["n_anatomy_missing"] = str(len(missing))
        rec["missing_anatomy_variables"] = ";".join(missing)
        if fs_success and missing:
            n_completed_missing += 1
            LOGGER.warning("Incomplete anatomy for %s: %s", fs_id, rec["missing_anatomy_variables"])
        rows.append(rec)

    write_tsv(args.out_tsv, list(TABLE_COLUMNS), rows)
    write_tsv(
        args.out_dictionary,
        [
            "variable",
            "hypothesis_level",
            "role",
            "source_file",
            "source_section",
            "unit",
            "definition",
            "derivation",
            "freesurfer_version",
            "notes",
        ],
        dictionary_rows(),
    )
    assert_unmodified(before)

    print(f"Wrote {args.out_tsv}")
    print(f"Wrote {args.out_dictionary}")
    print(f"SUBJECTS_DIR: {args.subjects_dir}")
    print(f"N rows (subject×session): {len(rows)}")
    print(f"N FS_success (recon-all.done + {REQUIRED_FS_VERSION}): {n_success}")
    print(f"N completed with missing anatomy values: {n_completed_missing}")
    print(f"N non-{REQUIRED_FS_VERSION} stamps skipped: {n_wrong_version}")
    print("No statistical models were fit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
