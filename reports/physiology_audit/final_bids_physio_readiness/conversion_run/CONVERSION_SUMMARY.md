# PhysioLog → BIDS conversion summary

**Generated:** `2026-07-27T21:32:10.368355+00:00`
**READY jobs attempted:** 1307 (decision table; **1258** unique PhysioLog UIDs after dedupe of duplicate rows)
**OK:** 1307 job-rows / **1256** unique BOLD stems with ≥1 physio sidecar
**On-disk products:** **3575** `*_physio.tsv.gz` + **3575** `*_physio.json` in both `bids/` and `release_dataset/`
**By recording:** pulse 1112 · respiratory 1243 · trigger 1208 · ecg 12
**FAIL:** 0
**PHI_FAIL:** 0
**Dry run:** False
**Also release_dataset:** True
**Converter:** `code/convert_physiolog_to_bids.py`

## PHI policy

- JSON allowlist only: Columns, ConversionSoftware, ConversionSoftwareVersion, Manufacturer, SampleTime_ms, SamplingFrequency, SiemensChannel, StartTime, StartTimeConfidence, StartTimeMethod
- Forbidden keys never written (Patient*, Institution*, DeviceSerial*, dates, UIDs, paths).
- Source PhysioLog DICOMs remain outside the public BIDS tree.

- Post-write PHI findings: **0** (PHI_RISK=0)

## Outputs

- `/home/alexrees/scratch/reports/physiology_audit/final_bids_physio_readiness/conversion_run/conversion_results.tsv`
- `/home/alexrees/scratch/reports/physiology_audit/final_bids_physio_readiness/conversion_run/physio_json_phi_audit.tsv`
