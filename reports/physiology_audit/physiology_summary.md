# Physiology audit summary

Generated: `2026-07-21T17:44:43.034133+00:00`

Read-only audit of Siemens physiological logs. **No files under `raw_original/` were modified, copied, or converted.** Missing values are reported as `NA` and are never inferred.

## Inputs

- Raw root: `/lustre07/scratch/alexrees/raw_original`
- Existing metadata: `/lustre07/scratch/alexrees/metadata`
- BIDS root: `/lustre07/scratch/alexrees/bids`

## File counts

- Total physiology files: **448**
- ECG (`.ecg`): **74**
- RESP (`.resp`): **75**
- PULS (`.puls`): **75**
- PMU (`.pmu`): **74**
- EXT (`.ext`): **75**
- EXT1 (`.ext1`): **0**
- EXT2 (`.ext2`): **75**

## Parse status

- `binary_pmu`: **74**
- `parsed_text`: **374**

## Metadata presence

- Sampling frequency found: **0**
- Sampling frequency missing (`NA`): **448**
- Start time found: **358**
- Start time missing (`NA`): **90**

## BIDS run association

- `confirmed`: **0**
- `possible`: **0**
- `ambiguous`: **378**
- `unmatched`: **70**

## Conversion candidates

- Files with sampling frequency present **and** `confirmed` BIDS run: **0**
- Listed in `physiology_conversion_candidates.tsv`. This audit does **not** convert them; a validated converter must do that separately.

## Notes

- Siemens ASCII PMU logs (`.ecg/.puls/.resp/.ext/.ext2`) rarely store an explicit sampling frequency; when absent it is reported as `NA` rather than assumed from model defaults.
- A single physiological recording typically spans an entire session (many fMRI runs). Sessions with more than one func run are therefore reported as `ambiguous`: run-level assignment requires a real converter using trigger/timing alignment, not a guess.
- `start_timestamp` is the literal `LogStartMDHTime` tick value from the footer (see also the MPCU columns in the metadata report).

## Outputs

- `reports/physiology_audit/physiology_inventory.tsv`
- `reports/physiology_audit/physiology_metadata_report.tsv`
- `reports/physiology_audit/physiology_conversion_candidates.tsv`
- `reports/physiology_audit/physiology_summary.md`
