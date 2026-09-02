# DICOM Inventory

The Convert page includes **Generate Inventory**, which builds a metadata workbook
from the same discovery path used before conversion. No NIfTI or BIDS files are written.

## Workflow

1. Select an **Input Folder** (scan runs automatically).
2. Optionally set **Subject** / **Session** (same rules as Convert).
3. Optionally set an **Output Folder** (inventory files are written there; if empty, files go to `<input>/inventory`).
4. Click **Generate Inventory**.
5. Open `dicom_inventory.xlsx` (CSV copies are written alongside).

## Architecture

`InventoryManager` is the only orchestration entry point used by the GUI (`InventoryWorker`):

| Step | Reused component |
|------|------------------|
| Dataset discovery | `DicomParser.scan` → `list[DicomSeries]` |
| Per-series metadata | `DicomMetadataExtractor.extract_from_file` (sample file only, `stop_before_pixels`) |
| Extra tags not yet on the metadata model | `inventory.extra_tags.read_optional_tags` |
| Acquisition type | Classifier fields already on `DicomSeries` (`fine_sequence_type`, `sequence_type`, …) |
| Planned BIDS names / run | `build_bids_target` + `unique_stem` |
| Protocol completeness | `inventory.protocol_completeness` mapping classified series → expected acquisition keys |

There is **no** second DICOM parser and no duplicated classification rules.

## Outputs

### `dicom_inventory.xlsx`

1. **DICOM Series Inventory** — one row per series (metadata + planned BIDS columns).
2. **Protocol Completeness** — one row per subject/session with ✓/✗ for expected acquisitions and `Complete Protocol` TRUE/FALSE.

Formatting (openpyxl): green bold headers, auto-filter, frozen header row, auto column widths, alternate row shading, workbook metadata including timestamp and pipeline version.

### CSV

- `dicom_inventory.csv` — series sheet
- `dicom_inventory_protocol_completeness.csv` — protocol sheet

## Performance

Inventory scales with the existing scanner: headers only, one sample file enrichment per discovered series, and reuse of an already-scanned `self.series` list from the Convert page when available.

## Keeping pace with the parser

Series inventory columns pull from `DicomSeries` and `DicomMetadataExtractor` objects. When new fields are added to `DicomSeriesMetadata`, map them in `InventoryManager._META_COLUMN_ATTR` (and add the column name to `SERIES_INVENTORY_COLUMNS` if it should appear in Excel). Optional tags not yet modelled go through `OPTIONAL_TAGS` / `_OPTIONAL_COLUMN_TAG`.
