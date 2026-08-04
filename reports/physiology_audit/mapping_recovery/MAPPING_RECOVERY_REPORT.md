# PhysioLog → BOLD mapping recovery audit

Generated: `2026-07-27T21:10:14.875301+00:00`

**READ-ONLY.** No modifications to `raw_original/`, `bids/`, `derivatives/`, or `release_dataset/`.
No `*_physio.tsv.gz` created. Existing confirmed mappings were not overwritten.
Mode: `dry_run=True`.

## Inputs

- `/home/alexrees/scratch/reports/physiology_audit/final_bids_physio_readiness/EXCLUDED_324_physio_reasons.tsv` — `MAPPING_AMBIGUOUS` exclusion class
- `/home/alexrees/scratch/reports/physiology_audit/physiolog_dicom_deep.tsv` — PhysioLog SeriesNumber / SeriesTime / ProtocolName
- `/home/alexrees/scratch/reports/physiology_audit/physiolog_inventory.tsv` — subject / session join via filepath
- `/home/alexrees/scratch/reports/physiology_audit/physio_conversion_status.tsv` — prior conversion status (skip non-ambiguous mappings)
- BIDS root `/home/alexrees/scratch/bids` — magnitude `*_bold.json` sidecars (ProtocolName, SeriesNumber, run)

## Method (summary)

1. Restrict BOLD candidates to same subject, session, and Siemens `ProtocolName`.
2. Score by SeriesNumber distance, optional SeriesTime distance, and prefer BOLD immediately after PhysioLog when SeriesNumber-coherent.
3. Assign confidence HIGH / MEDIUM / LOW; ties → manual review.
4. Never choose on ProtocolName alone.

## Results

| Metric | Count |
| --- | ---: |
| PhysioLog UIDs analysed | 48 |
| No BOLD candidate | 0 |
| HIGH confidence | 27 |
| MEDIUM confidence | 0 |
| LOW confidence | 21 |
| Manual review rows | 21 |
| Candidate pairs written | 99 |
| Demoted for BOLD collision | 10 |

### Subjects with multiple ambiguous PhysioLogs

- `sub-043`: 11 ambiguous PhysioLog UIDs
- `sub-008`: 3 ambiguous PhysioLog UIDs
- `sub-002`: 2 ambiguous PhysioLog UIDs
- `sub-010`: 2 ambiguous PhysioLog UIDs
- `sub-011`: 2 ambiguous PhysioLog UIDs
- `sub-012`: 2 ambiguous PhysioLog UIDs
- `sub-015`: 2 ambiguous PhysioLog UIDs
- `sub-016`: 2 ambiguous PhysioLog UIDs
- `sub-021`: 2 ambiguous PhysioLog UIDs
- `sub-023`: 2 ambiguous PhysioLog UIDs
- `sub-025`: 2 ambiguous PhysioLog UIDs
- `sub-034`: 2 ambiguous PhysioLog UIDs
- `sub-035`: 2 ambiguous PhysioLog UIDs
- `sub-038`: 2 ambiguous PhysioLog UIDs
- `sub-040`: 2 ambiguous PhysioLog UIDs
- `sub-046`: 2 ambiguous PhysioLog UIDs
- `sub-060`: 2 ambiguous PhysioLog UIDs
- `sub-082`: 2 ambiguous PhysioLog UIDs
- `sub-083`: 2 ambiguous PhysioLog UIDs

## Outputs

- `all_physio_bold_candidates.tsv` — all scored PhysioLog↔BOLD pairs
- `physio_bold_mapping_recommendations.tsv` — best candidate per PhysioLog
- `manual_review_required.tsv` — LOW / ties / no candidate
- `physio_uid_series_index.tsv` — UID → SeriesNumber/SeriesTime cache used

## Recommendations for BIDS conversion

1. **Auto-accept HIGH** recommendations into a gated converter mapping table (`physio_uid → bold_stem`) after spot-checking a few sessions (e.g. `sub-015`).
2. **Review MEDIUM** (SeriesNumber proximity without temporal confirmation in BIDS JSON). Most BIDS sidecars lack `SeriesTime`/`AcquisitionTime`; SeriesNumber adjacency is the primary recoverable signal.
3. **Do not convert LOW** until manual resolution (ties, missing SeriesNumber, or identical BOLD SeriesNumbers across redos — especially `sub-043`).
4. Keep fail-closed policy for any UID not listed as HIGH/MEDIUM with a unique recommended stem.
5. This audit does **not** authorize writing `*_physio.tsv.gz`; conversion remains a separate gated step.

## Notes

- 59 exclusion rows collapsed to 48 unique `physio_series_uid` values.
- Phase BOLD (`part-phase`) excluded from candidates.
- Temporal scores are usually `NA` because BIDS JSON sidecars in this dataset typically omit SeriesTime/AcquisitionTime.
