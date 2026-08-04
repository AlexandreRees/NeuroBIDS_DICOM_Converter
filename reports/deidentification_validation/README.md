# De-identification validation package

Read-only pre-publication privacy validation for the Scientific Data BIDS release.

## Quick start

```bash
# Dry-run
python code/audit_dicom_deidentification.py --dry-run --dicom-dir /project/def-amirs/raw_original
python code/audit_bids_sidecar_privacy.py --dry-run --bids-dir /home/alexrees/scratch/bids
python code/audit_defacing_release.py --dry-run \
  --bids-dir /home/alexrees/scratch/bids \
  --defaced-dir /home/alexrees/scratch/derivatives/defacing

# Full
python code/audit_dicom_deidentification.py --dicom-dir /project/def-amirs/raw_original
python code/audit_bids_sidecar_privacy.py --bids-dir /home/alexrees/scratch/bids
python code/audit_defacing_release.py \
  --bids-dir /home/alexrees/scratch/bids \
  --defaced-dir /home/alexrees/scratch/derivatives/defacing
```

## Deliverables

See `FINAL_PRIVACY_READINESS_REPORT.md` for statuses and `Scientific_Data_Technical_Validation_Deidentification.md` for manuscript text.
