"""HTML conversion report generator (simple BIDS-oriented summary)."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from neuro_pipeline import __version__
from neuro_pipeline.models import ConversionResult
from neuro_pipeline.validation.models import ValidationSummary


@dataclass(slots=True)
class ReportContext:
    """Inputs required to build ``conversion_report.html``."""

    input_folder: Path
    output_folder: Path
    conversion_results: Sequence[ConversionResult]
    validation: ValidationSummary
    series_detected: int = 0
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    software_version: str = __version__
    metadata_summary: object | None = None
    subject_id: str = ""
    session_id: str = ""
    bids_validation_status: str = ""


class ReportGenerator:
    """Write a concise self-contained HTML conversion report."""

    def __init__(self, output_folder: Path | str) -> None:
        self.output_folder = Path(output_folder)

    def write(self, context: ReportContext, filename: str = "conversion_report.html") -> Path:
        path = self.output_folder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(context), encoding="utf-8")
        return path

    def render(self, context: ReportContext) -> str:
        converted = sum(1 for r in context.conversion_results if r.success)
        failed = sum(1 for r in context.conversion_results if not r.success)
        detected = context.series_detected or len(context.conversion_results)
        stamp = context.generated_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        subject = context.subject_id or "—"
        session = context.session_id or "—"
        bids = context.bids_validation_status or "—"
        ok = failed == 0 and context.bids_validation_status in {"", "PASS", "WARNING"}
        headline = (
            "Conversion completed successfully"
            if ok
            else "Conversion finished with errors"
        )
        seq_rows = []
        for result in context.conversion_results:
            status = "OK" if result.success else "FAIL"
            seq_rows.append(
                "<tr>"
                f"<td>{_esc(result.series.display_name)}</td>"
                f"<td>{_esc(result.series.sequence_type)}</td>"
                f"<td class='{status}'>{status}</td>"
                "</tr>"
            )
        sub_label = subject
        if subject not in {"", "—"} and not str(subject).startswith("sub-"):
            sub_label = f"sub-{subject}"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>NeuroPipeline Conversion Report</title>
  <style>
    body {{ font-family: Segoe UI, Helvetica, Arial, sans-serif; margin: 32px; color: #1f2933; }}
    h1 {{ color: #102a43; }}
    h2 {{ color: #243b53; margin-top: 28px; border-bottom: 1px solid #d9e2ec; padding-bottom: 6px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px 10px; text-align: left; }}
    th {{ background: #f0f4f8; }}
    .OK, .PASS {{ color: #0f7b3a; font-weight: 600; }}
    .WARNING {{ color: #b26a00; font-weight: 600; }}
    .FAIL {{ color: #b00020; font-weight: 600; }}
    .meta {{ background: #f0f4f8; padding: 12px 16px; border-radius: 8px; }}
  </style>
</head>
<body>
  <h1>NeuroPipeline Conversion Report</h1>
  <p><strong>{_esc(headline)}</strong></p>
  <div class="meta">
    <p><strong>Software version:</strong> {_esc(context.software_version)}</p>
    <p><strong>Date:</strong> {_esc(stamp)}</p>
    <p><strong>Input:</strong> {_esc(context.input_folder)}</p>
    <p><strong>Output:</strong> {_esc(context.output_folder)}</p>
    <p><strong>Subject:</strong> {_esc(subject)}</p>
    <p><strong>Session:</strong> {_esc(session)}</p>
    <p><strong>BIDS validation:</strong> <span class="{_esc(bids)}">{_esc(bids)}</span></p>
  </div>
  <h2>Summary</h2>
  <ul>
    <li>Sequences detected: <strong>{detected}</strong></li>
    <li>Sequences converted: <strong>{converted}</strong></li>
    <li>Failed: <strong>{failed}</strong></li>
  </ul>
  <p>BIDS dataset created: <strong>{_esc(sub_label)}</strong></p>
  <h2>Sequences</h2>
  <table>
    <thead><tr><th>Series</th><th>Type</th><th>Status</th></tr></thead>
    <tbody>
      {''.join(seq_rows) if seq_rows else '<tr><td colspan="3">No series.</td></tr>'}
    </tbody>
  </table>
</body>
</html>
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)
