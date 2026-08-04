# Confirmation: InstitutionalDepartmentName scrub

**Checked (UTC):** 2026-07-22

| Tree | JSON scanned | `InstitutionalDepartmentName` present |
| --- | ---: | ---: |
| `derivatives/defacing/` | 726 | **0** |
| `bids/` (prior cleaning audit) | 7958 | **0** |

No other sensitive keys matching PatientName/PatientID/PatientBirth/DeviceSerial/StationName/OperatorsName/Institutional* were found in defacing JSON.

No further scrub write was required — the field is already absent from derivative sidecars.
