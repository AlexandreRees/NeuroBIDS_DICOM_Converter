"""HTML report for BIDS validation outcomes."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

from neuro_pipeline import __version__
from neuro_pipeline.bids.validator import BIDSValidationResult


class BidsValidationReportWriter:
    """Write ``bids_validation_report.html`` next to a BIDS dataset."""

    def __init__(self, output_folder: Path | str) -> None:
        self.output_folder = Path(output_folder)

    def write(
        self,
        result: BIDSValidationResult,
        *,
        filename: str = "bids_validation_report.html",
    ) -> Path:
        path = self.output_folder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(result), encoding="utf-8")
        return path

    def render(self, result: BIDSValidationResult) -> str:
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        status = result.status.value
        recs = _recommendations(result)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>BIDS Validation Report</title>
  <style>
    body {{ font-family: Segoe UI, Helvetica, Arial, sans-serif; margin: 32px; color: #1f2933; }}
    h1 {{ color: #102a43; }}
    h2 {{ color: #243b53; border-bottom: 1px solid #d9e2ec; padding-bottom: 6px; }}
    .PASS {{ color: #0f7b3a; font-weight: 700; }}
    .WARNING {{ color: #b26a00; font-weight: 700; }}
    .FAIL {{ color: #b00020; font-weight: 700; }}
    .meta {{ background: #f0f4f8; padding: 12px 16px; border-radius: 8px; }}
    ul {{ line-height: 1.5; }}
  </style>
</head>
<body>
  <h1>BIDS Validation Report</h1>
  <p>Status: <span class="{status}">{status}</span></p>
  <div class="meta">
    <p><strong>Dataset path:</strong> {_esc(result.dataset_path)}</p>
    <p><strong>Validation date:</strong> {_esc(stamp)}</p>
    <p><strong>Software version:</strong> NeuroPipeline {_esc(__version__)}</p>
    <p><strong>Validator backend:</strong> {_esc(result.validator_backend or "n/a")}</p>
    <p><strong>Summary:</strong> {_esc(result.summary)}</p>
  </div>
  <h2>Errors</h2>
  {_list(result.errors)}
  <h2>Warnings</h2>
  {_list(result.warnings)}
  <h2>Recommendations</h2>
  {_list(recs)}
</body>
</html>
"""


def _list(items: list[str]) -> str:
    if not items:
        return "<p>None.</p>"
    return "<ul>" + "".join(f"<li>{_esc(i)}</li>" for i in items) + "</ul>"


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _recommendations(result: BIDSValidationResult) -> list[str]:
    recs: list[str] = []
    if "bids-validator executable was not found" in " ".join(result.warnings):
        recs.append(
            "Install the official bids-validator (npm i -g bids-validator) "
            "or bundle it next to the application for full schema checks."
        )
    if result.errors:
        recs.append("Fix listed errors before public sharing or OpenNeuro upload.")
    if any("sidecar" in w.lower() for w in result.warnings):
        recs.append("Ensure dcm2niix JSON sidecars are exported with every NIfTI.")
    if any("participants" in w.lower() for w in result.warnings):
        recs.append("Complete participants.tsv sex/age fields when ethically appropriate.")
    if not recs and result.status.value == "PASS":
        recs.append("Dataset looks ready for internal use; review License before release.")
    return recs
