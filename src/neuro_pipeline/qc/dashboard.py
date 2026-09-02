"""Professional HTML QC dashboard for conversion sessions."""

from __future__ import annotations

import base64
import html
import io
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from neuro_pipeline import __version__
from neuro_pipeline.models import ConversionResult
from neuro_pipeline.validation.models import ValidationSummary

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class QCDashboardContext:
    """Inputs for ``qc_report.html``."""

    conversion_results: Sequence[ConversionResult]
    validation: ValidationSummary | None = None
    output_folder: Path | None = None
    input_folder: Path | None = None
    scanner: str = ""
    field_strength: str = ""
    metadata_summaries: list[dict] = field(default_factory=list)
    series_detected: int = 0


class QCDashboardGenerator:
    """Build a self-contained QC HTML dashboard after conversion."""

    def __init__(self, output_folder: Path | str) -> None:
        self.output_folder = Path(output_folder)

    def write(
        self,
        context: QCDashboardContext,
        *,
        filename: str = "qc_report.html",
    ) -> Path:
        path = self.output_folder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            # Never overwrite silently — write timestamped sibling
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = self.output_folder / f"qc_report_{stamp}.html"
        path.write_text(self.render(context), encoding="utf-8")
        LOGGER.info("Wrote QC dashboard: %s", path)
        return path

    def render(self, context: QCDashboardContext) -> str:
        results = list(context.conversion_results)
        total = context.series_detected or len(results)
        converted = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)
        warnings = list(context.validation.warnings) if context.validation else []
        errors = list(context.validation.errors) if context.validation else []

        type_counts = Counter(
            (r.series.sequence_type or "unknown") for r in results
        )
        for meta in context.metadata_summaries:
            label = meta.get("fine_type") or meta.get("modality")
            if label:
                type_counts[str(label)] += 0  # ensure key exists without double-count

        modality_bars = _modality_bars(type_counts)
        rows = _conversion_rows(results, context.validation)
        preview_html = _optional_previews(results)
        warn_items = _warning_panel(warnings, errors, results, context.validation)

        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>NeuroPipeline QC Dashboard</title>
  <style>
    body {{ font-family: Segoe UI, Helvetica, Arial, sans-serif; margin: 28px; color: #1f2933; background: #f8fafc; }}
    h1 {{ color: #0b1f33; margin-bottom: 4px; }}
    h2 {{ color: #243b53; border-bottom: 1px solid #d9e2ec; padding-bottom: 6px; margin-top: 28px; }}
    .card {{ background: #fff; border: 1px solid #d9e2ec; border-radius: 10px; padding: 16px 18px; margin: 12px 0; }}
    .kpis {{ display: flex; flex-wrap: wrap; gap: 12px; }}
    .kpi {{ flex: 1 1 120px; background: #f0f4f8; border-radius: 8px; padding: 12px; text-align: center; }}
    .kpi .n {{ font-size: 1.6rem; font-weight: 700; color: #102a43; }}
    .bar {{ display: flex; align-items: center; gap: 8px; margin: 6px 0; }}
    .bar .label {{ width: 90px; font-size: 0.9rem; }}
    .bar .track {{ flex: 1; background: #e4e7eb; height: 14px; border-radius: 7px; overflow: hidden; }}
    .bar .fill {{ height: 100%; background: #2b6cb0; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 7px 9px; text-align: left; font-size: 0.92rem; }}
    th {{ background: #f0f4f8; }}
    .PASS {{ color: #0f7b3a; font-weight: 600; }}
    .WARNING {{ color: #b26a00; font-weight: 600; }}
    .FAIL, .ERROR {{ color: #b00020; font-weight: 600; }}
    .previews {{ display: flex; flex-wrap: wrap; gap: 16px; }}
    .previews figure {{ margin: 0; background: #fff; border: 1px solid #d9e2ec; padding: 8px; border-radius: 8px; }}
    .previews img {{ max-width: 280px; max-height: 280px; display: block; }}
    ul {{ line-height: 1.45; }}
  </style>
</head>
<body>
  <h1>QC Dashboard</h1>
  <p>NeuroPipeline {_esc(__version__)} · {_esc(stamp)}</p>

  <div class="card">
    <h2>1. Summary</h2>
    <div class="kpis">
      <div class="kpi"><div class="n">{total}</div>Total series</div>
      <div class="kpi"><div class="n">{converted}</div>Converted</div>
      <div class="kpi"><div class="n">{failed}</div>Failed</div>
      <div class="kpi"><div class="n">{len(warnings)}</div>Warnings</div>
    </div>
    <p><strong>Input:</strong> {_esc(context.input_folder or '—')}<br/>
       <strong>Output:</strong> {_esc(context.output_folder or '—')}</p>
  </div>

  <div class="card">
    <h2>2. Modalities</h2>
    {modality_bars}
  </div>

  <div class="card">
    <h2>3. Scanner</h2>
    <p><strong>Manufacturer / model:</strong> {_esc(context.scanner or 'Unknown')}<br/>
       <strong>Field strength:</strong> {_esc(context.field_strength or 'Unknown')}</p>
  </div>

  <div class="card">
    <h2>4. Conversion table</h2>
    <table>
      <thead>
        <tr>
          <th>Original DICOM</th><th>NIfTI</th><th>Type</th><th>Validation</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>5. Warning panel</h2>
    {warn_items}
  </div>

  <div class="card">
    <h2>6. Image previews</h2>
    {preview_html}
  </div>
</body>
</html>
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _modality_bars(counts: Counter) -> str:
    if not counts:
        return "<p>No modalities recorded.</p>"
    max_c = max(counts.values()) or 1
    parts = []
    for label, count in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        pct = int(100 * count / max_c)
        parts.append(
            f'<div class="bar"><span class="label">{_esc(label)}</span>'
            f'<div class="track"><div class="fill" style="width:{pct}%"></div></div>'
            f"<span>{count}</span></div>"
        )
    return "".join(parts)


def _conversion_rows(
    results: Sequence[ConversionResult],
    validation: ValidationSummary | None,
) -> str:
    nifti_status: dict[str, str] = {}
    if validation:
        for r in validation.nifti_results:
            nifti_status[r.filename] = r.status.value
        for r in validation.dwi_results:
            nifti_status[r.nifti_path.name] = r.status.value

    rows: list[str] = []
    for result in results:
        original = result.series.display_name
        seq = result.series.sequence_type or "unknown"
        niftis = [
            p
            for p in result.output_files
            if p.name.endswith(".nii") or p.name.endswith(".nii.gz")
        ]
        if not niftis:
            status = "FAIL" if not result.success else "—"
            rows.append(
                "<tr>"
                f"<td>{_esc(original)}</td><td>—</td>"
                f"<td>{_esc(seq)}</td>"
                f"<td class='{status}'>{status}</td></tr>"
            )
            continue
        for nii in niftis:
            status = nifti_status.get(nii.name) or ("PASS" if result.success else "FAIL")
            rows.append(
                "<tr>"
                f"<td>{_esc(original)}</td>"
                f"<td>{_esc(nii.name)}</td>"
                f"<td>{_esc(seq)}</td>"
                f"<td class='{_esc(status)}'>{_esc(status)}</td></tr>"
            )
    return "".join(rows) if rows else '<tr><td colspan="4">No conversions.</td></tr>'


def _warning_panel(
    warnings: list[str],
    errors: list[str],
    results: Sequence[ConversionResult],
    validation: ValidationSummary | None,
) -> str:
    items: list[str] = []
    items.extend(errors)
    items.extend(warnings)
    # Heuristic companions
    for result in results:
        niftis = [
            p
            for p in result.output_files
            if p.name.endswith(".nii.gz") or p.name.endswith(".nii")
        ]
        for nii in niftis:
            stem = nii.name[: -len(".nii.gz")] if nii.name.endswith(".nii.gz") else nii.stem
            parent = nii.parent
            if (result.series.sequence_type or "") == "dwi":
                if not (parent / f"{stem}.bvec").exists():
                    items.append(f"missing bvec: {nii.name}")
            if not (parent / f"{stem}.json").exists():
                items.append(f"missing json: {nii.name}")
    if validation:
        for nr in validation.nifti_results:
            for msg in getattr(nr, "messages", []) or []:
                low = str(msg).lower()
                if "voxel" in low or "corrupt" in low or "unusual" in low:
                    items.append(f"{nr.filename}: {msg}")
    # Dedupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    if not uniq:
        return "<p>No warnings.</p>"
    return "<ul>" + "".join(f"<li>{_esc(i)}</li>" for i in uniq) + "</ul>"


def _optional_previews(results: Sequence[ConversionResult]) -> str:
    """Render central-slice previews when nilearn (+nibabel) is available."""
    try:
        import nibabel as nib
        from nilearn import plotting
    except Exception:
        return (
            "<p>Image previews skipped (optional dependency "
            "<code>nilearn</code> not installed).</p>"
        )

    figures: list[str] = []
    picked = 0
    for result in results:
        if picked >= 4:
            break
        seq = (result.series.sequence_type or "").lower()
        if seq not in {"anat", "dwi"}:
            continue
        for nii in result.output_files:
            if not (nii.name.endswith(".nii") or nii.name.endswith(".nii.gz")):
                continue
            if not nii.exists():
                continue
            try:
                img = nib.load(str(nii))
                data = img.get_fdata()
                if data.ndim < 2:
                    continue
                # Prefer mid-slice orthographic PNG via nilearn
                buf = io.BytesIO()
                display = plotting.plot_anat(
                    img if seq == "anat" else img.slicer[..., 0] if data.ndim >= 4 else img,
                    display_mode="z",
                    cut_coords=1,
                    title=nii.name,
                )
                display.savefig(buf, dpi=80)
                display.close()
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                figures.append(
                    f"<figure><img src='data:image/png;base64,{b64}' alt='{_esc(nii.name)}'/>"
                    f"<figcaption>{_esc(seq.upper())}: {_esc(nii.name)}</figcaption></figure>"
                )
                picked += 1
                break
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("Preview failed for %s: %s", nii, exc)
                continue
    if not figures:
        return "<p>No previewable T1/DWI volumes found.</p>"
    return '<div class="previews">' + "".join(figures) + "</div>"
