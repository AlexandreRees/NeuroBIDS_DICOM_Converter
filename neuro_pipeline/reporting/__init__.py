"""Publication-ready reporting (Methods, QC summaries, OpenNeuro)."""

from neuro_pipeline.reporting.generator import write_html_report, write_json_report
from neuro_pipeline.reporting.methods_generator import generate_methods_md
from neuro_pipeline.reporting.pipeline_qc_summary import generate_pipeline_qc_summary_html

__all__ = [
    "generate_methods_md",
    "generate_pipeline_qc_summary_html",
    "write_html_report",
    "write_json_report",
]
