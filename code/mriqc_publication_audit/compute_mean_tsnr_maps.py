#!/usr/bin/env python3
"""Compute subject-level and group-mean voxelwise tSNR maps (AOMIC Fig. 6 style).

Adapted from NILAB-UvA/AOMIC-common-scripts/misc_qc/compute_tsnr_fmri.py
for this dataset. Read-only w.r.t. BIDS raw; writes only under derivatives/tsnr
or --out-dir.

Requires fMRIPrep (or equivalent) motion-corrected, spatially normalized BOLD:
  sub-*/ses-*/func/*_space-{SPACE}_desc-preproc_bold.nii.gz

Example:
  python3 compute_mean_tsnr_maps.py \\
      --fmriprep-dir /path/to/derivatives/fmriprep \\
      --out-dir /home/alexrees/scratch/derivatives/tsnr \\
      --n-jobs 8

If fMRIPrep derivatives are missing, the script exits with a clear status and
does not invent maps from raw BIDS (raw BOLD is not motion/MNI-normalized).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

LOGGER = logging.getLogger("mean_tsnr")

DEFAULT_SPACES = (
    "MNI152NLin2009cAsym_desc-preproc_bold.nii.gz",
    "MNI152NLin6Asym_desc-preproc_bold.nii.gz",
)


def _find_bolds(fmriprep_dir: Path, space_suffix: str) -> list[Path]:
    return sorted(fmriprep_dir.glob(f"sub-*/ses-*/func/*{space_suffix}"))


def _tsnr_nii(in_bold: Path, out_tsnr: Path) -> Path:
    import nibabel as nib
    import numpy as np

    img = nib.load(str(in_bold))
    data = img.get_fdata(dtype=np.float32)
    if data.ndim != 4 or data.shape[-1] < 5:
        raise ValueError(f"Expected 4D BOLD with ≥5 volumes, got {data.shape} for {in_bold}")
    mean = data.mean(axis=-1)
    std = data.std(axis=-1)
    with np.errstate(divide="ignore", invalid="ignore"):
        tsnr = np.where(std > 0, mean / std, 0.0).astype(np.float32)
    out_tsnr.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(tsnr, img.affine, img.header), str(out_tsnr))
    return out_tsnr


def _mean_maps(tsnr_files: list[Path], out_mean: Path) -> Path:
    import nibabel as nib
    import numpy as np

    if not tsnr_files:
        raise ValueError("No tSNR files to average")
    ref = nib.load(str(tsnr_files[0]))
    acc = np.zeros(ref.shape, dtype=np.float64)
    n = 0
    for p in tsnr_files:
        img = nib.load(str(p))
        if img.shape != ref.shape:
            LOGGER.warning("Skip shape mismatch %s %s vs %s", p, img.shape, ref.shape)
            continue
        acc += img.get_fdata(dtype=np.float32)
        n += 1
    if n == 0:
        raise RuntimeError("No compatible tSNR maps to average")
    mean = (acc / n).astype(np.float32)
    out_mean.parent.mkdir(parents=True, exist_ok=True)
    hdr = ref.header.copy()
    hdr["descrip"] = f"mean tSNR across {n} runs"
    nib.save(nib.Nifti1Image(mean, ref.affine, hdr), str(out_mean))
    LOGGER.info("Wrote mean tSNR (%d runs) → %s", n, out_mean)
    return out_mean


def _plot_orthoviews(mean_tsnr: Path, out_png: Path, title: str) -> Path:
    """Simple orthographic mosaic (AOMIC Fig. 6 inspired, publication-light)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import nibabel as nib
    import numpy as np

    img = nib.load(str(mean_tsnr))
    data = img.get_fdata(dtype=np.float32)
    # Crop empty borders lightly
    mask = data > 0
    if mask.any():
        coords = np.array(np.where(mask))
        xmin, ymin, zmin = coords.min(axis=1)
        xmax, ymax, zmax = coords.max(axis=1)
        data = data[xmin : xmax + 1, ymin : ymax + 1, zmin : zmax + 1]

    x, y, z = [s // 2 for s in data.shape]
    slices = [
        ("Sagittal", np.rot90(data[x, :, :])),
        ("Coronal", np.rot90(data[:, y, :])),
        ("Axial", np.rot90(data[:, :, z])),
    ]
    vmax = float(np.percentile(data[data > 0], 99)) if (data > 0).any() else 1.0

    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6))
    for ax, (name, slc) in zip(axes, slices):
        im = ax.imshow(slc, cmap="hot", vmin=0, vmax=vmax, origin="lower")
        ax.set_title(name, color="#1a1a1a")
        ax.axis("off")
    fig.colorbar(im, ax=axes.tolist(), fraction=0.025, pad=0.02, label="tSNR")
    fig.suptitle(title, color="#1a1a1a", y=1.02)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(out_png.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)
    LOGGER.info("Wrote %s", out_png)
    return out_png


def run(fmriprep_dir: Path, out_dir: Path, space_suffix: str, n_jobs: int, plot_only_mean: bool) -> int:
    bolds = _find_bolds(fmriprep_dir, space_suffix)
    if not bolds:
        LOGGER.error(
            "No preproc BOLD found under %s matching *%s\n"
            "AOMIC Fig. 6–style maps need motion-corrected, MNI-normalized BOLD "
            "(typically fMRIPrep). This workspace currently has MRIQC IQMs but no "
            "fMRIPrep derivatives — re-run after fMRIPrep is available.",
            fmriprep_dir,
            space_suffix,
        )
        return 2

    LOGGER.info("Found %d preproc BOLD files", len(bolds))
    out_dir.mkdir(parents=True, exist_ok=True)

    def one(bold: Path) -> Path:
        sub = bold.parts[-4] if "ses-" in bold.parts[-3] else bold.parts[-3]
        ses = bold.parts[-3] if bold.parts[-3].startswith("ses-") else "ses-unknown"
        stem = bold.name.replace("_desc-preproc_bold.nii.gz", "").replace(".nii.gz", "")
        out = out_dir / sub / ses / f"{stem}_desc-tsnr.nii.gz"
        if out.is_file():
            return out
        return _tsnr_nii(bold, out)

    if n_jobs > 1:
        from joblib import Parallel, delayed
        from tqdm import tqdm

        tsnr_files = Parallel(n_jobs=n_jobs)(
            delayed(one)(b) for b in tqdm(bolds, desc="tSNR")
        )
    else:
        tsnr_files = [one(b) for b in bolds]

    tsnr_files = [Path(p) for p in tsnr_files]
    mean_path = out_dir / "group" / f"group_space-{space_suffix.split('_')[0]}_desc-meanTSNR.nii.gz"
    _mean_maps(tsnr_files, mean_path)

    fig_dir = Path("/home/alexrees/scratch/reports/mriqc_publication_audit/figures")
    _plot_orthoviews(
        mean_path,
        fig_dir / "Fig06b_mean_tsnr_orthoviews.png",
        title=f"Group-mean tSNR ({len(tsnr_files)} runs) — AOMIC Fig. 6 style",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--fmriprep-dir",
        type=Path,
        default=Path("/home/alexrees/scratch/derivatives/fmriprep"),
        help="fMRIPrep derivatives root",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/home/alexrees/scratch/derivatives/tsnr"),
        help="Output directory for tSNR NIfTIs",
    )
    p.add_argument(
        "--space-suffix",
        default=DEFAULT_SPACES[0],
        help="Filename suffix identifying normalized preproc BOLD",
    )
    p.add_argument("--n-jobs", type=int, default=4)
    p.add_argument(
        "--plot-only-mean",
        action="store_true",
        help="Only plot an existing group mean map (skip recompute)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if args.plot_only_mean:
        mean_path = (
            args.out_dir
            / "group"
            / f"group_space-{args.space_suffix.split('_')[0]}_desc-meanTSNR.nii.gz"
        )
        if not mean_path.is_file():
            LOGGER.error("Missing %s", mean_path)
            return 2
        fig_dir = Path("/home/alexrees/scratch/reports/mriqc_publication_audit/figures")
        _plot_orthoviews(
            mean_path,
            fig_dir / "Fig06b_mean_tsnr_orthoviews.png",
            title="Group-mean tSNR — AOMIC Fig. 6 style",
        )
        return 0

    if not args.fmriprep_dir.is_dir():
        # Try common alternate roots before failing
        alts = [
            Path("/lustre07/scratch/alexrees/derivatives/fmriprep"),
            Path("/home/alexrees/scratch/derivatives/fmriprep"),
        ]
        found = next((p for p in alts if p.is_dir()), None)
        if found is None:
            LOGGER.error(
                "fMRIPrep directory not found (%s). "
                "Cannot build AOMIC Fig. 6–style mean tSNR maps yet. "
                "BOLD/T1 IQM boards do not require fMRIPrep and can be used now.",
                args.fmriprep_dir,
            )
            return 2
        args.fmriprep_dir = found

    return run(
        fmriprep_dir=args.fmriprep_dir,
        out_dir=args.out_dir,
        space_suffix=args.space_suffix,
        n_jobs=args.n_jobs,
        plot_only_mean=False,
    )


if __name__ == "__main__":
    sys.exit(main())
