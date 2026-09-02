"""Silent post-conversion QC error detector."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from neuro_pipeline.qc.errors.models import QCIssue, QCReport, QCStatus
from neuro_pipeline.qc.errors.rules import load_qc_rules

LOGGER = logging.getLogger(__name__)


class ErrorDetector:
    """Detect missing companions, corrupt/empty NIfTI, dimension and duplicate issues."""

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self.rules = rules if rules is not None else load_qc_rules()

    def detect(self, output_dir: Path | str) -> QCReport:
        root = Path(output_dir)
        report = QCReport()
        if not root.is_dir():
            report.add(
                QCIssue(
                    code="missing_output",
                    status=QCStatus.FAIL,
                    message=f"Output directory missing: {root}",
                )
            )
            return report

        nifti_files = [
            p
            for p in root.rglob("*.nii*")
            if p.is_file() and "derivatives" not in p.parts and "_staging" not in p.parts
        ]
        self._check_duplicates(nifti_files, report)
        for nifti in nifti_files:
            self._check_one(nifti, report)
        return report

    def write_html_report(self, report: QCReport, output_dir: Path | str) -> Path:
        """Write ``qc_error_report.html`` summarizing silent error detection."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        rows = []
        for issue in report.issues:
            rows.append(
                "<tr>"
                f"<td>{issue.code}</td>"
                f"<td><b>{issue.status.value}</b></td>"
                f"<td>{issue.message}</td>"
                f"<td>{Path(issue.path).name if issue.path else '—'}</td>"
                "</tr>"
            )
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>QC error detection</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ddd;padding:8px;text-align:left}}
th{{background:#f4f4f4}}
</style></head><body>
<h1>Silent error detection</h1>
<p><b>Overall:</b> {report.status.value}</p>
<p>Warnings: {report.warnings} &nbsp; Failures: {report.failures}</p>
<table>
<thead><tr><th>Code</th><th>Status</th><th>Message</th><th>File</th></tr></thead>
<tbody>
{''.join(rows) if rows else '<tr><td colspan="4">No issues detected</td></tr>'}
</tbody></table>
</body></html>
"""
        path = out / "qc_error_report.html"
        path.write_text(html, encoding="utf-8")
        return path

    def _check_one(self, nifti: Path, report: QCReport) -> None:
        global_rules = self.rules.get("global") or {}
        datatype = self._infer_datatype(nifti)
        type_rules = self.rules.get(datatype) or {}

        # Empty files
        try:
            size = nifti.stat().st_size
        except OSError:
            size = -1
        if size == 0 and global_rules.get("fail_on_empty", True):
            report.add(
                QCIssue(
                    code="empty_file",
                    status=QCStatus.FAIL,
                    message="Empty NIfTI file",
                    path=str(nifti),
                )
            )
            return

        # Corrupt NIfTI
        img = None
        try:
            import nibabel as nib

            img = nib.load(str(nifti))
            _ = img.shape
        except Exception as exc:  # noqa: BLE001
            if global_rules.get("fail_on_corrupt", True):
                report.add(
                    QCIssue(
                        code="corrupt_nifti",
                        status=QCStatus.FAIL,
                        message=f"Cannot load NIfTI with nibabel: {exc}",
                        path=str(nifti),
                    )
                )
                return

        # Missing companions
        stem = self._stem(nifti)
        json_path = nifti.with_suffix("").with_suffix(".json") if nifti.suffix == ".gz" else nifti.with_suffix(".json")
        # Safer companion discovery
        json_candidates = list(nifti.parent.glob(stem + "*.json"))
        bvec = list(nifti.parent.glob(stem + "*.bvec"))
        bval = list(nifti.parent.glob(stem + "*.bval"))

        if type_rules.get("require_json", False) and not json_candidates:
            report.add(
                QCIssue(
                    code="missing_json",
                    status=QCStatus.WARNING,
                    message="NIfTI exists but JSON sidecar is missing",
                    path=str(nifti),
                )
            )
        if datatype == "dwi":
            if type_rules.get("require_bvec", True) and not bvec:
                report.add(
                    QCIssue(
                        code="missing_bvec",
                        status=QCStatus.FAIL,
                        message="DWI NIfTI missing .bvec",
                        path=str(nifti),
                    )
                )
            if type_rules.get("require_bval", True) and not bval:
                report.add(
                    QCIssue(
                        code="missing_bval",
                        status=QCStatus.FAIL,
                        message="DWI NIfTI missing .bval",
                        path=str(nifti),
                    )
                )
            if type_rules.get("require_4d", True) and img is not None and len(getattr(img, "shape", ())) < 4:
                # ADC maps are often 3D — warn only if name suggests multi-shell DWI
                name = nifti.name.lower()
                if "adc" not in name:
                    report.add(
                        QCIssue(
                            code="dimension_mismatch",
                            status=QCStatus.WARNING,
                            message="DWI expected 4D image but found 3D",
                            path=str(nifti),
                            details={"shape": list(img.shape)},
                        )
                    )
        if datatype == "func" and type_rules.get("require_4d", True) and img is not None:
            if len(getattr(img, "shape", ())) < 4:
                report.add(
                    QCIssue(
                        code="dimension_mismatch",
                        status=QCStatus.WARNING,
                        message="Functional BOLD expected 4D image but found 3D",
                        path=str(nifti),
                        details={"shape": list(img.shape)},
                    )
                )

    def _check_duplicates(self, files: list[Path], report: QCReport) -> None:
        if not (self.rules.get("global") or {}).get("warn_on_duplicate", True):
            return
        by_name: dict[str, list[Path]] = defaultdict(list)
        for path in files:
            by_name[path.name].append(path)
        for name, paths in by_name.items():
            if len(paths) > 1:
                report.add(
                    QCIssue(
                        code="duplicate_output",
                        status=QCStatus.WARNING,
                        message=f"Duplicate output filename: {name}",
                        path=str(paths[0]),
                        details={"paths": [str(p) for p in paths]},
                    )
                )

    @staticmethod
    def _stem(path: Path) -> str:
        name = path.name
        if name.endswith(".nii.gz"):
            return name[: -len(".nii.gz")]
        return path.stem

    @staticmethod
    def _infer_datatype(path: Path) -> str:
        parts = {p.lower() for p in path.parts}
        name = path.name.lower()
        for key in ("anat", "dwi", "func", "fmap"):
            if key in parts:
                return key
        if "bold" in name:
            return "func"
        if "dwi" in name or "diff" in name or "adc" in name:
            return "dwi"
        if "fmap" in name:
            return "fmap"
        return "anat"
