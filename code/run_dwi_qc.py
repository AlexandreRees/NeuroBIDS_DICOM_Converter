#!/usr/bin/env python3
"""Read-only DWI quality control for a BIDS dataset (Scientific Data validation).

Never modifies BIDS NIfTI, bval, bvec, or JSON files. All outputs are written
under the configured report directory (default: reports/dwi_qc/).

Example:
  python code/run_dwi_qc.py --bids-dir /home/alexrees/scratch/bids
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
import pandas as pd


def log(msg: str) -> None:
    print(msg, flush=True)

B0_THRESHOLD = 50.0
DEFAULT_OUTPUT = Path("/home/alexrees/scratch/reports/dwi_qc")
ENTITY_RE = re.compile(
    r"(?P<subject>sub-[^_/]+)(?:_(?P<session>ses-[^_/]+))?(?:_.*)?_dwi\.nii\.gz$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only DWI QC pipeline for BIDS diffusion data."
    )
    parser.add_argument(
        "--bids-dir",
        type=Path,
        required=True,
        help="Path to the BIDS dataset root (read-only).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Report output directory (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--max-scans",
        type=int,
        default=None,
        help="Optional limit on number of DWI scans (for testing).",
    )
    parser.add_argument(
        "--skip-gradcheck",
        action="store_true",
        help="Skip dwigradcheck (faster; not for final publication run).",
    )
    parser.add_argument(
        "--fill-missing-masks",
        action="store_true",
        help=(
            "Resume mode: keep existing inventory/gradcheck TSVs and only "
            "re-run dwi2mask/signal/figures for rows with missing mask metrics."
        ),
    )
    return parser.parse_args()


def ensure_tools() -> None:
    missing = [t for t in ("dwigradcheck", "dwi2mask") if shutil.which(t) is None]
    if missing:
        raise SystemExit(
            "Missing required MRtrix3 tools: "
            + ", ".join(missing)
            + ". Load mrtrix (e.g. `module load mrtrix`) and retry."
        )


def parse_entities(nifti: Path) -> tuple[str, str]:
    match = ENTITY_RE.search(nifti.name)
    if not match:
        parts = nifti.parts
        subject = next((p for p in parts if p.startswith("sub-")), "unknown")
        session = next((p for p in parts if p.startswith("ses-")), "n/a")
        return subject, session
    subject = match.group("subject")
    session = match.group("session") or "n/a"
    return subject, session


def sidecar_paths(nifti: Path) -> tuple[Path, Path, Path]:
    stem = nifti.name[: -len(".nii.gz")]
    parent = nifti.parent
    return parent / f"{stem}.bval", parent / f"{stem}.bvec", parent / f"{stem}.json"


def inventory_status(bval: Path, bvec: Path, json_path: Path) -> str:
    missing = []
    if not bval.is_file():
        missing.append("bval")
    if not bvec.is_file():
        missing.append("bvec")
    if not json_path.is_file():
        missing.append("json")
    if missing:
        return "MISSING_" + "_".join(m.upper() for m in missing)
    return "OK"


def build_inventory(bids_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for nifti in sorted(bids_dir.rglob("*_dwi.nii.gz")):
        if "/derivatives/" in str(nifti):
            continue
        subject, session = parse_entities(nifti)
        bval, bvec, json_path = sidecar_paths(nifti)
        rows.append(
            {
                "subject": subject,
                "session": session,
                "nifti": str(nifti),
                "bval": str(bval),
                "bvec": str(bvec),
                "json": str(json_path),
                "status": inventory_status(bval, bvec, json_path),
            }
        )
    return pd.DataFrame(
        rows,
        columns=["subject", "session", "nifti", "bval", "bvec", "json", "status"],
    )


def load_bval(path: Path) -> np.ndarray:
    return np.loadtxt(path).astype(float).ravel()


def load_bvec(path: Path) -> np.ndarray:
    arr = np.loadtxt(path).astype(float)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    # Prefer FSL layout: 3 x N
    if arr.shape[0] == 3:
        return arr
    if arr.shape[1] == 3:
        return arr.T
    return arr


def nifti_n_volumes(img: nib.spatialimages.SpatialImage) -> int:
    shape = img.shape
    if len(shape) < 4:
        return 1
    return int(shape[3])


def check_gradient_consistency(row: pd.Series) -> dict:
    subject, session = row["subject"], row["session"]
    result = {
        "subject": subject,
        "session": session,
        "n_volumes": np.nan,
        "n_bvals": np.nan,
        "n_bvec_columns": np.nan,
        "status": "FAIL",
    }
    try:
        if row["status"] != "OK":
            result["status"] = "FAIL"
            return result
        img = nib.load(row["nifti"])
        bvals = load_bval(Path(row["bval"]))
        bvecs = load_bvec(Path(row["bvec"]))
        n_vol = nifti_n_volumes(img)
        n_bvals = int(bvals.size)
        n_bvec = int(bvecs.shape[1])
        result.update(
            {
                "n_volumes": n_vol,
                "n_bvals": n_bvals,
                "n_bvec_columns": n_bvec,
                "status": "PASS" if n_vol == n_bvals == n_bvec else "FAIL",
            }
        )
    except Exception as exc:  # noqa: BLE001
        result["status"] = "FAIL"
        result["error"] = str(exc)
    return result


def bvalue_summary(row: pd.Series) -> dict:
    subject, session = row["subject"], row["session"]
    out = {
        "subject": subject,
        "session": session,
        "unique_bvals": "",
        "n_b0": np.nan,
        "n_diffusion": np.nan,
        "max_bvalue": np.nan,
    }
    try:
        bvals = load_bval(Path(row["bval"]))
        rounded = np.rint(bvals).astype(int)
        unique = sorted(int(v) for v in np.unique(rounded))
        is_b0 = bvals < B0_THRESHOLD
        out.update(
            {
                "unique_bvals": ",".join(str(v) for v in unique),
                "n_b0": int(np.sum(is_b0)),
                "n_diffusion": int(np.sum(~is_b0)),
                "max_bvalue": float(np.max(bvals)) if bvals.size else np.nan,
            }
        )
    except Exception:  # noqa: BLE001
        pass
    return out


def interpret_dwigradcheck(text: str) -> str:
    """Classify dwigradcheck table output.

    The first data row is the best-scoring orientation. Identity (no axis flip,
    permutation (0, 1, 2)) is PASS; any other top-ranked transform is REVIEW.
    """
    for line in text.splitlines():
        # Data rows look like: 45.42  none  (0, 1, 2)  scanner
        m = re.match(
            r"^\s*([0-9.+-eE]+)\s+(\S+)\s+(\([^)]*\))\s+(\S+)\s*$",
            line,
        )
        if not m:
            continue
        flipped = m.group(2).lower()
        perm = re.sub(r"\s+", "", m.group(3))
        if flipped in {"none", "0", "-"} and perm in {"(0,1,2)", "(0, 1, 2)"}:
            return "PASS"
        return "REVIEW"
    # Fallback: explicit correction language without a parseable table
    if re.search(r"error|fail|unable|invalid", text, flags=re.IGNORECASE):
        return "FAIL"
    return "REVIEW"


def run_dwigradcheck(row: pd.Series, timeout: int = 900) -> dict:
    subject, session = row["subject"], row["session"]
    out = {"subject": subject, "session": session, "status": "FAIL", "output": ""}
    if row["status"] != "OK":
        out["output"] = f"Skipped: inventory status {row['status']}"
        return out
    # Fewer tracks than default keeps QC practical for large cohorts while
    # still ranking orientation hypotheses.
    cmd = [
        "dwigradcheck",
        row["nifti"],
        "-fslgrad",
        row["bvec"],
        row["bval"],
        "-number",
        "100",
        "-quiet",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        text = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
        text = text.strip()
        if proc.returncode != 0:
            status = "FAIL"
        else:
            status = interpret_dwigradcheck(text)
        out.update({"status": status, "output": text or f"exit_code={proc.returncode}"})
    except subprocess.TimeoutExpired:
        out.update({"status": "FAIL", "output": f"Timeout after {timeout}s"})
    except Exception as exc:  # noqa: BLE001
        out.update({"status": "FAIL", "output": str(exc)})
    return out


def run_dwi2mask(row: pd.Series, tmp_dir: Path, timeout: int = 900) -> Path | None:
    stem = Path(row["nifti"]).name.replace(".nii.gz", "")
    mask_path = tmp_dir / f"{stem}_mask.nii.gz"
    if mask_path.is_file():
        try:
            # Reuse only if loadable and non-empty; otherwise regenerate.
            data = np.asanyarray(nib.load(str(mask_path)).dataobj)
            if data.size and np.any(data):
                return mask_path
        except Exception:  # noqa: BLE001
            pass
        mask_path.unlink(missing_ok=True)
    cmd = [
        "dwi2mask",
        row["nifti"],
        str(mask_path),
        "-fslgrad",
        row["bvec"],
        row["bval"],
        "-quiet",
        "-force",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0 or not mask_path.is_file():
        err = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        raise RuntimeError(err or f"dwi2mask failed with code {proc.returncode}")
    return mask_path


def mask_metrics(row: pd.Series, mask_path: Path) -> dict:
    mask = np.asanyarray(nib.load(str(mask_path)).dataobj) > 0
    img = nib.load(row["nifti"])
    shape = img.shape[:3]
    n_vox = int(mask.sum())
    brain_fraction = float(n_vox / float(np.prod(shape))) if np.prod(shape) else np.nan
    return {
        "subject": row["subject"],
        "session": row["session"],
        "mask_voxels": n_vox,
        "brain_fraction": brain_fraction,
    }


def signal_metrics(row: pd.Series, mask_path: Path) -> dict:
    """Compute masked signal stats from one 4D load (float32).

    Do not stream volume-by-volume from ``.nii.gz`` (gzip is not seekable and is
    extremely slow). Memory spikes are handled by running at most one fill worker
    at a time on login nodes, or with adequate Slurm ``--mem``.
    """
    img = nib.load(row["nifti"])
    mask = np.asanyarray(nib.load(str(mask_path)).dataobj) > 0
    data = np.asanyarray(img.dataobj, dtype=np.float32)
    if data.ndim == 3:
        data = data[..., np.newaxis]
    if mask.shape != data.shape[:3]:
        raise ValueError(f"Mask/data shape mismatch: {mask.shape} vs {data.shape[:3]}")
    bvals = load_bval(Path(row["bval"]))
    if bvals.size != data.shape[3]:
        raise ValueError("bval length does not match number of volumes")

    masked = data[mask]  # (n_vox, n_vol)
    del data  # free the dense 4D copy ASAP
    flat = masked.ravel()
    is_b0 = bvals < B0_THRESHOLD
    b0_vals = masked[:, is_b0].ravel() if np.any(is_b0) else np.array([], dtype=np.float32)
    diff_vals = masked[:, ~is_b0].ravel() if np.any(~is_b0) else np.array([], dtype=np.float32)

    if flat.size:
        # Exact median on full flat array can be very slow for long shells;
        # subsample densely (every k-th value) while keeping exact mean/std.
        if flat.size > 2_000_000:
            step = max(1, flat.size // 2_000_000)
            median = float(np.median(flat[::step]))
        else:
            median = float(np.median(flat))
        mean = float(np.mean(flat))
        std = float(np.std(flat))
    else:
        median = mean = std = np.nan

    return {
        "subject": row["subject"],
        "session": row["session"],
        "mean_signal": mean,
        "median_signal": median,
        "std_signal": std,
        "mean_b0_signal": float(np.mean(b0_vals)) if b0_vals.size else np.nan,
        "mean_diffusion_signal": float(np.mean(diff_vals)) if diff_vals.size else np.nan,
    }


def make_figure(row: pd.Series, fig_dir: Path) -> Path | None:
    nifti = Path(row["nifti"])
    stem = nifti.name.replace(".nii.gz", "")
    out_path = fig_dir / f"{stem}_qc.png"
    img = nib.load(str(nifti))
    data = img.dataobj
    shape = img.shape
    if len(shape) < 4:
        return None
    bvals = load_bval(Path(row["bval"]))
    b0_idx = np.where(bvals < B0_THRESHOLD)[0]
    diff_idx = np.where(bvals >= B0_THRESHOLD)[0]
    if b0_idx.size == 0 or diff_idx.size == 0:
        return None
    z = shape[2] // 2
    b0_vol = np.asanyarray(data[..., int(b0_idx[0])], dtype=np.float32)
    diff_vol = np.asanyarray(data[..., int(diff_idx[0])], dtype=np.float32)
    b0_slice = np.rot90(b0_vol[:, :, z])
    diff_slice = np.rot90(diff_vol[:, :, z])

    fig, axes = plt.subplots(1, 2, figsize=(8, 4))
    axes[0].imshow(b0_slice, cmap="gray")
    axes[0].set_title(f"b0 (vol {int(b0_idx[0])})")
    axes[0].axis("off")
    axes[1].imshow(diff_slice, cmap="gray")
    axes[1].set_title(f"diffusion (vol {int(diff_idx[0])}, b≈{int(round(bvals[diff_idx[0]]))})")
    axes[1].axis("off")
    fig.suptitle(f"{row['subject']} {row['session']} — central axial", fontsize=11)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def write_tsv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, sep="\t", index=False)


def summarize_directions(inventory: pd.DataFrame) -> str:
    counts: list[int] = []
    for _, row in inventory.iterrows():
        if row["status"] != "OK":
            continue
        try:
            bvecs = load_bvec(Path(row["bvec"]))
            bvals = load_bval(Path(row["bval"]))
            n_dir = int(np.sum(bvals >= B0_THRESHOLD))
            counts.append(n_dir)
        except Exception:  # noqa: BLE001
            continue
    if not counts:
        return "No gradient direction counts available."
    uniq, freq = np.unique(counts, return_counts=True)
    parts = [f"{int(u)} directions ({int(f)} scans)" for u, f in zip(uniq, freq)]
    return "; ".join(parts)


def write_report(
    output_dir: Path,
    inventory: pd.DataFrame,
    consistency: pd.DataFrame,
    bvals_df: pd.DataFrame,
    gradcheck: pd.DataFrame,
    masks: pd.DataFrame,
    signals: pd.DataFrame,
) -> Path:
    n_scans = len(inventory)
    n_subjects = inventory["subject"].nunique() if n_scans else 0
    n_sessions = (
        inventory[["subject", "session"]].drop_duplicates().shape[0] if n_scans else 0
    )
    missing = inventory[inventory["status"] != "OK"]
    fail_cons = consistency[consistency["status"] != "PASS"]
    bval_counts = (
        bvals_df["unique_bvals"].value_counts(dropna=False)
        if not bvals_df.empty
        else pd.Series(dtype=int)
    )
    grad_pass = int((gradcheck["status"] == "PASS").sum()) if not gradcheck.empty else 0
    grad_review = int((gradcheck["status"] == "REVIEW").sum()) if not gradcheck.empty else 0
    grad_fail = int((gradcheck["status"] == "FAIL").sum()) if not gradcheck.empty else 0

    masks_ok = (
        masks[masks["brain_fraction"].notna()] if not masks.empty else masks
    )
    signals_ok = (
        signals[signals["mean_signal"].notna()] if not signals.empty else signals
    )
    mask_mean = (
        float(masks_ok["brain_fraction"].mean()) if not masks_ok.empty else float("nan")
    )
    mask_med = (
        float(masks_ok["brain_fraction"].median()) if not masks_ok.empty else float("nan")
    )
    sig_mean = (
        float(signals_ok["mean_signal"].mean()) if not signals_ok.empty else float("nan")
    )
    sig_b0 = (
        float(signals_ok["mean_b0_signal"].mean()) if not signals_ok.empty else float("nan")
    )
    sig_diff = (
        float(signals_ok["mean_diffusion_signal"].mean())
        if not signals_ok.empty
        else float("nan")
    )

    lines = [
        "# Diffusion MRI technical validation",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Dataset",
        "",
        f"- Number of subjects: **{n_subjects}**",
        f"- Number of sessions (subject×session): **{n_sessions}**",
        f"- Number of DWI scans: **{n_scans}**",
        "",
        "## Integrity",
        "",
        f"- Missing gradients / sidecars: **{len(missing)}** "
        f"(see `dwi_inventory.tsv`)",
        f"- Volume / bval / bvec mismatches: **{len(fail_cons)}** "
        f"(see `dwi_gradient_consistency.tsv`)",
        "",
    ]
    if len(missing):
        lines.append("Missing sidecar examples:")
        for _, r in missing.head(10).iterrows():
            lines.append(f"- `{r['nifti']}` → `{r['status']}`")
        lines.append("")

    lines.extend(
        [
            "## Diffusion scheme",
            "",
            "### b-values distribution",
            "",
        ]
    )
    if bval_counts.empty:
        lines.append("- No b-value summaries available.")
    else:
        for scheme, count in bval_counts.items():
            lines.append(f"- `{scheme}`: {int(count)} scans")
    lines.extend(
        [
            "",
            "### Directions distribution",
            "",
            f"- {summarize_directions(inventory)}",
            "",
            "## Gradient QC",
            "",
            f"- `dwigradcheck` PASS: **{grad_pass}**",
            f"- `dwigradcheck` REVIEW (suggested correction reported, not applied): "
            f"**{grad_review}**",
            f"- `dwigradcheck` FAIL: **{grad_fail}**",
            "",
            "No gradient corrections were applied to the distributed dataset.",
            "",
            "## Image quality",
            "",
            "### Mask coverage",
            "",
            f"- Scans with automated masks: **{len(masks_ok)}** / {len(masks)}",
            f"- Mean brain fraction: **{mask_mean:.4f}**",
            f"- Median brain fraction: **{mask_med:.4f}**",
            "",
            "### Signal metrics (within mask)",
            "",
            f"- Mean overall signal (cohort mean): **{sig_mean:.2f}**",
            f"- Mean b0 signal (cohort mean): **{sig_b0:.2f}**",
            f"- Mean diffusion signal (cohort mean): **{sig_diff:.2f}**",
            "",
            "Visual snapshots (central axial b0 and diffusion slices) are stored in "
            "`figures/`.",
            "",
            "## Conclusion",
            "",
            "Diffusion MRI data were technically validated through BIDS consistency "
            "checks, diffusion gradient verification, b-value assessment and automated "
            "signal quality metrics. No modifications were applied to the distributed "
            "dataset.",
            "",
            "## Output files",
            "",
            "- `dwi_inventory.tsv`",
            "- `dwi_gradient_consistency.tsv`",
            "- `dwi_bvalue_summary.tsv`",
            "- `dwigradcheck_results.tsv`",
            "- `dwi_mask_metrics.tsv`",
            "- `dwi_signal_metrics.tsv`",
            "- `figures/`",
            "- `tmp/` (temporary masks; not part of the BIDS release)",
            "",
        ]
    )
    report_path = output_dir / "DWI_QC_REPORT.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def scan_needs_review(
    inv_status: str,
    cons_status: str,
    grad_status: str,
    mask_voxels: float | None,
) -> bool:
    if inv_status != "OK":
        return True
    if cons_status != "PASS":
        return True
    if grad_status in {"FAIL", "REVIEW"}:
        return True
    if mask_voxels is None or not np.isfinite(mask_voxels) or mask_voxels <= 0:
        return True
    return False


def fill_missing_masks(args: argparse.Namespace) -> int:
    """Re-run only mask/signal/figure steps for rows with NaN mask metrics."""
    bids_dir = args.bids_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not bids_dir.is_dir():
        print(f"ERROR: BIDS directory not found: {bids_dir}", file=sys.stderr, flush=True)
        return 1

    required = [
        "dwi_inventory.tsv",
        "dwi_gradient_consistency.tsv",
        "dwi_bvalue_summary.tsv",
        "dwigradcheck_results.tsv",
        "dwi_mask_metrics.tsv",
        "dwi_signal_metrics.tsv",
    ]
    missing_files = [name for name in required if not (output_dir / name).is_file()]
    if missing_files:
        print(
            "ERROR: --fill-missing-masks requires existing TSVs: "
            + ", ".join(missing_files),
            file=sys.stderr,
            flush=True,
        )
        return 1

    ensure_tools()
    tmp_dir = output_dir / "tmp"
    fig_dir = output_dir / "figures"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    inventory = pd.read_csv(output_dir / "dwi_inventory.tsv", sep="\t")
    consistency_df = pd.read_csv(output_dir / "dwi_gradient_consistency.tsv", sep="\t")
    bvals_df = pd.read_csv(output_dir / "dwi_bvalue_summary.tsv", sep="\t")
    grad_df = pd.read_csv(output_dir / "dwigradcheck_results.tsv", sep="\t")
    masks_df = pd.read_csv(output_dir / "dwi_mask_metrics.tsv", sep="\t")
    signals_df = pd.read_csv(output_dir / "dwi_signal_metrics.tsv", sep="\t")

    n = len(inventory)
    for name, df in (
        ("consistency", consistency_df),
        ("bvals", bvals_df),
        ("gradcheck", grad_df),
        ("masks", masks_df),
        ("signals", signals_df),
    ):
        if len(df) != n:
            print(
                f"ERROR: row count mismatch for {name}: {len(df)} vs inventory {n}",
                file=sys.stderr,
                flush=True,
            )
            return 1

    todo_idx = masks_df.index[masks_df["brain_fraction"].isna()].tolist()
    log(
        f"Fill-missing-masks: {len(todo_idx)} / {n} scans need dwi2mask "
        f"(inode quota should be free)."
    )
    if not todo_idx:
        log("Nothing to do — regenerating report only.")
    else:
        first = inventory.loc[todo_idx[0]]
        last = inventory.loc[todo_idx[-1]]
        log(
            f"First pending: {first['subject']} {first['session']} "
            f"({Path(first['nifti']).name})"
        )
        log(
            f"Last pending:  {last['subject']} {last['session']} "
            f"({Path(last['nifti']).name})"
        )

    n_done = 0
    n_fail = 0
    for k, idx in enumerate(todo_idx, start=1):
        row = inventory.loc[idx]
        cons = consistency_df.loc[idx]
        label = f"{row['subject']} {row['session']} ({k}/{len(todo_idx)}; idx={idx})"
        log(f"\n[{label}]")

        if row["status"] != "OK" or cons.get("status") != "PASS":
            log("  Skipped (inventory or consistency not OK/PASS)")
            n_fail += 1
            continue

        try:
            log("  dwi2mask…")
            mask_path = run_dwi2mask(row, tmp_dir)
            mstats = mask_metrics(row, mask_path)
            masks_df.loc[idx, ["mask_voxels", "brain_fraction"]] = [
                mstats["mask_voxels"],
                mstats["brain_fraction"],
            ]

            log("  signal metrics…")
            sstats = signal_metrics(row, mask_path)
            for key, val in sstats.items():
                if key in ("subject", "session"):
                    continue
                signals_df.loc[idx, key] = val

            log("  figure…")
            make_figure(row, fig_dir)
            n_done += 1
        except Exception as exc:  # noqa: BLE001
            log(f"  WARNING: still failing: {exc}")
            traceback.print_exc()
            n_fail += 1

        if k % 5 == 0 or k == len(todo_idx):
            write_tsv(masks_df, output_dir / "dwi_mask_metrics.tsv")
            write_tsv(signals_df, output_dir / "dwi_signal_metrics.tsv")
            log(f"  checkpoint: filled={n_done} failed={n_fail}")

    write_tsv(masks_df, output_dir / "dwi_mask_metrics.tsv")
    write_tsv(signals_df, output_dir / "dwi_signal_metrics.tsv")

    n_pass = 0
    n_review = 0
    for idx, row in inventory.iterrows():
        mask_vox = masks_df.loc[idx, "mask_voxels"]
        try:
            mask_vox_f = float(mask_vox)
        except (TypeError, ValueError):
            mask_vox_f = float("nan")
        needs_review = scan_needs_review(
            row["status"],
            str(consistency_df.loc[idx, "status"]),
            str(grad_df.loc[idx, "status"]),
            mask_vox_f if np.isfinite(mask_vox_f) else None,
        )
        if needs_review:
            n_review += 1
        else:
            n_pass += 1

    log("\nWriting DWI_QC_REPORT.md…")
    write_report(
        output_dir,
        inventory,
        consistency_df,
        bvals_df,
        grad_df,
        masks_df,
        signals_df,
    )

    still_nan = int(masks_df["brain_fraction"].isna().sum())
    meta = {
        "mode": "fill-missing-masks",
        "bids_dir": str(bids_dir),
        "output_dir": str(output_dir),
        "n_dwi_scans": n,
        "n_pending_at_start": len(todo_idx),
        "n_filled": n_done,
        "n_still_failed": n_fail,
        "n_masks_still_nan": still_nan,
        "n_pass": n_pass,
        "n_requiring_review": n_review,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "read_only_bids": True,
    }
    (output_dir / "run_metadata_fill_masks.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )

    log("\n========== DWI QC FILL-MISSING SUMMARY ==========")
    log(f"Filled successfully: {n_done}")
    log(f"Still missing masks: {still_nan}")
    log(f"Number PASS: {n_pass}")
    log(f"Number requiring review: {n_review}")
    log(f"Location of reports: {output_dir}")
    return 0 if still_nan == 0 else 2


def main() -> int:
    args = parse_args()
    if args.fill_missing_masks:
        return fill_missing_masks(args)

    bids_dir = args.bids_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not bids_dir.is_dir():
        print(f"ERROR: BIDS directory not found: {bids_dir}", file=sys.stderr, flush=True)
        return 1

    ensure_tools()
    output_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_dir / "tmp"
    fig_dir = output_dir / "figures"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    log(f"BIDS root (read-only): {bids_dir}")
    log(f"Output directory: {output_dir}")
    log("1/8 Inventory…")
    inventory = build_inventory(bids_dir)
    if args.max_scans is not None:
        inventory = inventory.iloc[: max(0, args.max_scans)].copy()
    write_tsv(inventory, output_dir / "dwi_inventory.tsv")
    n_scans = len(inventory)
    log(f"   Found {n_scans} DWI scans")

    consistency_rows: list[dict] = []
    bvalue_rows: list[dict] = []
    grad_rows: list[dict] = []
    mask_rows: list[dict] = []
    signal_rows: list[dict] = []
    n_pass = 0
    n_review = 0

    for idx, (_, row) in enumerate(inventory.iterrows(), start=1):
        label = f"{row['subject']} {row['session']} ({idx}/{n_scans})"
        log(f"\n[{label}]")

        log("  2/8 Gradient consistency…")
        cons = check_gradient_consistency(row)
        consistency_rows.append(
            {k: cons[k] for k in [
                "subject", "session", "n_volumes", "n_bvals", "n_bvec_columns", "status"
            ]}
        )

        log("  3/8 b-value summary…")
        bvalue_rows.append(bvalue_summary(row))

        log("  4/8 dwigradcheck…")
        if args.skip_gradcheck:
            grad = {
                "subject": row["subject"],
                "session": row["session"],
                "status": "SKIPPED",
                "output": "dwigradcheck skipped (--skip-gradcheck)",
            }
        else:
            grad = run_dwigradcheck(row)
        grad_rows.append(grad)

        mask_path = None
        mask_vox: float | None = None
        if row["status"] == "OK" and cons.get("status") == "PASS":
            try:
                log("  5/8 dwi2mask…")
                mask_path = run_dwi2mask(row, tmp_dir)
                mstats = mask_metrics(row, mask_path)
                mask_rows.append(mstats)
                mask_vox = float(mstats["mask_voxels"])

                log("  6/8 Signal metrics…")
                signal_rows.append(signal_metrics(row, mask_path))

                log("  7/8 Figure…")
                make_figure(row, fig_dir)
            except Exception as exc:  # noqa: BLE001
                log(f"  WARNING: mask/signal/figure failed: {exc}")
                traceback.print_exc()
                mask_rows.append(
                    {
                        "subject": row["subject"],
                        "session": row["session"],
                        "mask_voxels": np.nan,
                        "brain_fraction": np.nan,
                    }
                )
                signal_rows.append(
                    {
                        "subject": row["subject"],
                        "session": row["session"],
                        "mean_signal": np.nan,
                        "median_signal": np.nan,
                        "std_signal": np.nan,
                        "mean_b0_signal": np.nan,
                        "mean_diffusion_signal": np.nan,
                    }
                )
        else:
            log("  5–7/8 Skipped (inventory or consistency failed)")
            mask_rows.append(
                {
                    "subject": row["subject"],
                    "session": row["session"],
                    "mask_voxels": np.nan,
                    "brain_fraction": np.nan,
                }
            )
            signal_rows.append(
                {
                    "subject": row["subject"],
                    "session": row["session"],
                    "mean_signal": np.nan,
                    "median_signal": np.nan,
                    "std_signal": np.nan,
                    "mean_b0_signal": np.nan,
                    "mean_diffusion_signal": np.nan,
                }
            )

        needs_review = scan_needs_review(
            row["status"], cons.get("status", "FAIL"), grad.get("status", "FAIL"), mask_vox
        )
        if needs_review:
            n_review += 1
        else:
            n_pass += 1

        # Checkpoint TSVs periodically
        if idx % 10 == 0 or idx == n_scans:
            write_tsv(pd.DataFrame(consistency_rows), output_dir / "dwi_gradient_consistency.tsv")
            write_tsv(pd.DataFrame(bvalue_rows), output_dir / "dwi_bvalue_summary.tsv")
            write_tsv(pd.DataFrame(grad_rows), output_dir / "dwigradcheck_results.tsv")
            write_tsv(pd.DataFrame(mask_rows), output_dir / "dwi_mask_metrics.tsv")
            write_tsv(pd.DataFrame(signal_rows), output_dir / "dwi_signal_metrics.tsv")

    consistency_df = pd.DataFrame(consistency_rows)
    bvals_df = pd.DataFrame(bvalue_rows)
    grad_df = pd.DataFrame(grad_rows)
    masks_df = pd.DataFrame(mask_rows)
    signals_df = pd.DataFrame(signal_rows)

    write_tsv(consistency_df, output_dir / "dwi_gradient_consistency.tsv")
    write_tsv(bvals_df, output_dir / "dwi_bvalue_summary.tsv")
    write_tsv(grad_df, output_dir / "dwigradcheck_results.tsv")
    write_tsv(masks_df, output_dir / "dwi_mask_metrics.tsv")
    write_tsv(signals_df, output_dir / "dwi_signal_metrics.tsv")

    log("\n8/8 Writing DWI_QC_REPORT.md…")
    write_report(
        output_dir,
        inventory,
        consistency_df,
        bvals_df,
        grad_df,
        masks_df,
        signals_df,
    )

    # Lightweight provenance sidecar (not required, but useful)
    meta = {
        "bids_dir": str(bids_dir),
        "output_dir": str(output_dir),
        "n_dwi_scans": n_scans,
        "n_pass": n_pass,
        "n_requiring_review": n_review,
        "b0_threshold": B0_THRESHOLD,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "read_only_bids": True,
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )

    log("\n========== DWI QC SUMMARY ==========")
    log(f"Number of DWI scans analyzed: {n_scans}")
    log(f"Number PASS: {n_pass}")
    log(f"Number requiring review: {n_review}")
    log(f"Location of reports: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
