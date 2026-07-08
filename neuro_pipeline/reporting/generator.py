"""HTML and JSON report generation for pipeline QC and validation."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _esc(text: object) -> str:
    return html.escape(str(text))


def write_json_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_html_report(
    path: Path,
    *,
    title: str,
    summary: dict[str, Any],
    sections: list[tuple[str, list[dict[str, Any]]]],
) -> None:
    """Write a simple self-contained HTML report."""
    generated = datetime.now(timezone.utc).isoformat()
    rows: list[str] = [
        "<!DOCTYPE html>",
        "<html lang='en'><head><meta charset='utf-8'>",
        f"<title>{_esc(title)}</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:2rem;max-width:1100px}",
        "table{border-collapse:collapse;width:100%;margin:1rem 0}",
        "th,td{border:1px solid #ccc;padding:.4rem .6rem;text-align:left}",
        "th{background:#f5f5f5}.pass{color:#0a0}.fail{color:#a00}.warn{color:#a60}",
        "h1,h2{margin-top:1.5rem}",
        "</style></head><body>",
        f"<h1>{_esc(title)}</h1>",
        f"<p><strong>Generated:</strong> {_esc(generated)}</p>",
        "<h2>Summary</h2><table><tbody>",
    ]
    for key, value in summary.items():
        rows.append(f"<tr><th>{_esc(key)}</th><td>{_esc(value)}</td></tr>")
    rows.append("</tbody></table>")

    for section_title, items in sections:
        rows.append(f"<h2>{_esc(section_title)}</h2>")
        if not items:
            rows.append("<p>No items.</p>")
            continue
        headers = list(items[0].keys())
        rows.append("<table><thead><tr>")
        for header in headers:
            rows.append(f"<th>{_esc(header)}</th>")
        rows.append("</tr></thead><tbody>")
        for item in items:
            rows.append("<tr>")
            for header in headers:
                value = item.get(header, "")
                css = ""
                if header in {"status", "passed", "severity"}:
                    text = str(value).lower()
                    if text in {"fail", "failed", "false", "error"}:
                        css = " class='fail'"
                    elif text in {"warn", "warning"}:
                        css = " class='warn'"
                    elif text in {"pass", "passed", "true", "success"}:
                        css = " class='pass'"
                rows.append(f"<td{css}>{_esc(value)}</td>")
            rows.append("</tr>")
        rows.append("</tbody></table>")

    rows.append("</body></html>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows), encoding="utf-8")
