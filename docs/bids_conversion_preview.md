# BIDS Conversion Preview

The Convert page includes an interactive **BIDS Preview** between Input analysis and
Subject/Session. It lets you inspect and edit the planned BIDS layout **before** any
DICOM conversion.

## Safety

The preview system **never** modifies DICOM input:

- no rename / move / delete of DICOM files
- no metadata written into DICOM folders
- all edits live in an in-memory `BIDSConversionPlan` or an optional `conversion_plan.json`
  saved **outside** the input folder

## Pipeline

```
DICOM (read-only)
  → DicomParser / SequenceClassifier
  → BIDSConversionPlan
  → user edits (GUI)
  → ConversionManager (consumes validated plan)
  → dcm2niix + BIDSExporter
  → BIDS output
```

Classification and naming reuse the existing helpers (`BIDSEntityResolver`,
`build_bids_target`, `unique_stem`). There is no second classifier.

## GUI actions

| Button | Effect |
|--------|--------|
| Refresh Preview | Recalculate planned filenames from the table |
| Reset Changes | Restore the automatic plan |
| Validate Plan | Check duplicates, labels, required entities |
| Save / Load Plan | JSON user choices only |
| Continue to Conversion | Validate, then focus Convert |
| Convert | If a plan exists, it must validate; converter follows the plan |

Convert without using the preview remains supported (backward compatible): when no plan is attached, naming follows the previous exporter path.

## Planned item fields

`source_series_uid`, series number/description, subject, session, datatype, suffix,
task, run, acquisition, direction, intended filename, include flag, confidence, and
classification source.

## Tests

See `tests/test_conversion_plan.py` for DICOM immutability, edit/reset behaviour,
exporter-driven export names, and rejection of invalid plans.
