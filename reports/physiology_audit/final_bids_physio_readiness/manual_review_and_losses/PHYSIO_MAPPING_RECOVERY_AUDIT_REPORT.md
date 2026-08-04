# Physio mapping recovery — audit package

**Generated:** `2026-07-29T18:14:47.678448+00:00`

This package documents (1) acceptance of HIGH-confidence ambiguous mappings with PULS/RESP,
(2) the remaining **21 LOW** cases for manual audit (including **sub-043 twins**), and
(3) **likely definitive losses** that should be disclosed in the data descriptor.

## A. HIGH recovery executed (this session)

| Item | Value |
| --- | ---: |
| HIGH + PULS/RESP candidates | 15 |
| Spot-check PASS | 15 |
| Converted OK | **15** |
| Sidecar files written (tsv+json × channels) | **90** |
| bids/ `*_physio.tsv.gz` total now | **3620** |
| release_dataset/ `*_physio.tsv.gz` total now | **3620** |

**Criteria for acceptance:** `confidence=HIGH`, PULS/RESP present, `start_time_available=yes`,
unique recommended BOLD stem, BIDS `ProtocolName` match, `|ΔSeriesNumber|≤2`, no pre-existing
physio on target stem, CSA SampleTime + ticks present.

**Subjects recovered:** sub-015, 016, 021, 035, 038, 040, 060, 082

Provenance:
- `high_mapping_recovery/high_spotcheck.tsv`
- `high_mapping_recovery/high_conversion_results.tsv`
- `high_mapping_recovery/high_recovery_summary.json`
- Converter: `code/convert_high_mapping_recovery.py`

**Not converted from HIGH:** 9 EXT-only + 3 empty-channel HIGH rows (no PULS/RESP value).

## B. Manual review required — 21 LOW

File: [`MANUAL_REVIEW_LOW_21.tsv`](MANUAL_REVIEW_LOW_21.tsv)

Fill columns `auditor_decision`, `auditor_chosen_bold_stem`, `auditor_notes`.

| Subject | n LOW | Channels | Typical issue |
| --- | ---: | --- | --- |
| `sub-043` | 11 | {'PULS;RESP;EXT': 9, 'RESP;EXT': 2} | {'SUB043_TWIN_PROTOCOL_REDO': 11} |
| `sub-012` | 2 | {'EXT': 2} | {'MANUAL_CHOOSE': 2} |
| `sub-023` | 2 | {'PULS;RESP;EXT': 2} | {'MANUAL_CHOOSE': 2} |
| `sub-025` | 2 | {'PULS;RESP;EXT': 2} | {'MANUAL_CHOOSE': 2} |
| `sub-046` | 2 | {'PULS;RESP;EXT': 2} | {'MANUAL_CHOOSE': 2} |
| `sub-083` | 2 | {'PULS;RESP;EXT': 2} | {'MANUAL_CHOOSE': 2} |

### How to audit a LOW row

1. Open `all_candidates` (column `all_candidates` or `SUB043_all_candidates.tsv`).
2. Compare PhysioLog `SeriesNumber` / `SeriesTime` vs each BOLD candidate.
3. Prefer BOLD with SeriesNumber immediately after PhysioLog when unique.
4. If two BOLDs share the **same SeriesNumber** (classic twin/redo), use acquisition notes,
   export order, or leave unmapped (fail-closed).
5. Only then authorize conversion via an explicit `physio_uid → bold_stem` override table.

### sub-043 twins (CRITICAL)

File: [`MANUAL_REVIEW_SUB043_TWINS.tsv`](MANUAL_REVIEW_SUB043_TWINS.tsv)  
Candidate expansion: [`SUB043_all_candidates.tsv`](SUB043_all_candidates.tsv)

- **11** ambiguous PhysioLogs for `sub-043`
- Dominant failure mode: **`tie_equivalent_candidates`** — multiple BOLD runs share the same
  Siemens `ProtocolName` **and often the same SeriesNumber**, so SeriesNumber distance cannot
  break the tie.
- Do **not** auto-convert. Requires human decision or permanent exclusion with documentation.

## C. Remaining exclusions after HIGH recovery

File: [`REMAINING_EXCLUSIONS_AFTER_HIGH_RECOVERY.tsv`](REMAINING_EXCLUSIONS_AFTER_HIGH_RECOVERY.tsv)

| exclusion_class | N |
| --- | ---: |
| `EXT_ONLY_NO_STARTTIME` | 206 |
| `NO_SAMPLETIME_AND_NO_STARTTIME` | 38 |
| `MAPPING_AMBIGUOUS` | 33 |
| `NO_STARTTIME_WITH_PHYSIO_CHANNELS` | 13 |

| recoverability | N |
| --- | ---: |
| `UNLIKELY_EXT_ONLY` | 206 |
| `LIKELY_DEFINITIVE_LOSS` | 38 |
| `POSSIBLE_AFTER_MANUAL_REVIEW` | 21 |
| `RECOVERABLE_WITH_POLICY_CHANGE` | 13 |
| `LOW_VALUE_EXT_ONLY_HIGH` | 12 |

## D. Likely definitive losses (document in data descriptor)

### D1. Subjects with **no** BIDS physio at all

File: [`SUBJECTS_WITHOUT_BIDS_PHYSIO.tsv`](SUBJECTS_WITHOUT_BIDS_PHYSIO.tsv)

| Subject | Cause | Recoverability |
| --- | --- | --- |
| `sub-010` | PhysioLog present but EXT-only (no PULS/RESP); StartTime missing | `DEFINITIVE_FOR_CARD_RESP` |
| `sub-013` | PhysioLog present but EXT-only (no PULS/RESP); StartTime missing | `DEFINITIVE_FOR_CARD_RESP` |
| `sub-014` | PhysioLog present but EXT-only (no PULS/RESP); StartTime missing | `DEFINITIVE_FOR_CARD_RESP` |
| `sub-056` | No PhysioLog DICOM and no peripheral PMU files in inventory | `DEFINITIVE_ABSENT_AT_SOURCE` |
| `sub-061` | No PhysioLog DICOM; session-wide peripheral PMU (.puls/.resp/.ecg/.ext) only | `POLICY_BLOCKED_PERIPHERAL_PMU` |
| `sub-062` | No PhysioLog DICOM; session-wide peripheral PMU (.puls/.resp/.ecg/.ext) only | `POLICY_BLOCKED_PERIPHERAL_PMU` |
| `sub-063` | No PhysioLog DICOM; session-wide peripheral PMU (.puls/.resp/.ecg/.ext) only | `POLICY_BLOCKED_PERIPHERAL_PMU` |

### D2. CSA SampleTime absent (`NO_SAMPLETIME_AND_NO_STARTTIME`) — **38** UIDs

File: [`DEFINITIVE_LOSS_NO_SAMPLETIME.tsv`](DEFINITIVE_LOSS_NO_SAMPLETIME.tsv)

Subjects: **sub-007, sub-008, sub-009, sub-042** (ses-01).

Without Siemens `SampleTime`, SamplingFrequency cannot be derived under the project rule
`Hz = 1000 / SampleTime_ms`. Publishing would require inventing a rate → **not authorized**.

### D3. EXT-only PhysioLogs (`EXT_ONLY_NO_STARTTIME`) — still **206** after recovery

No cardiac/respiratory content. Safe for descriptor language:

> PhysioLog series containing only the EXT (TTL) channel without recoverable StartTime were
> not converted to BIDS physiology sidecars.

### D4. Potentially recoverable but **not** converted here

| Class | N | Path |
| --- | ---: | --- |
| `MAPPING_AMBIGUOUS` remaining (mostly LOW) | 33 | Manual review (section B) |
| `NO_STARTTIME_WITH_PHYSIO_CHANNELS` | 13 | Policy change: allow StartTimeConfidence=LOW |
| Peripheral PMU only (sub-061/062/063) | 3 subjects | Separate PMU pipeline + ethics |

## E. Suggested data-descriptor wording (draft)

**Recovered ambiguous mappings.** Fifteen PhysioLog series previously excluded because multiple
BOLD runs shared a Siemens ProtocolName were remapped using SeriesNumber adjacency
(confidence HIGH, PULS/RESP present, CSA StartTime available) and converted to BIDS
`*_physio` sidecars after automated spot-checks.

**Unresolved ambiguous mappings.** Twenty-one PhysioLog series remain unmapped pending manual
review (including eleven series for sub-043 where candidate BOLD runs were tied). These were
not converted under the fail-closed policy.

**Absent or non-convertible physiology.** Seven subjects lack BIDS physiology: three had
EXT-only PhysioLogs; one had no PhysioLog or peripheral files inventoriable; three had only
session-wide peripheral PMU exports excluded by policy. An additional 38 PhysioLog
series lacked CSA SampleTime and were not converted.

## F. File index

| File | Purpose |
| --- | --- |
| `MANUAL_REVIEW_LOW_21.tsv` | Auditor worksheet for all LOW cases |
| `MANUAL_REVIEW_SUB043_TWINS.tsv` | sub-043 subset |
| `SUB043_all_candidates.tsv` | All scored BOLD candidates for sub-043 |
| `REMAINING_EXCLUSIONS_AFTER_HIGH_RECOVERY.tsv` | Full remaining exclusion ledger |
| `SUBJECTS_WITHOUT_BIDS_PHYSIO.tsv` | Subject-level gaps |
| `DEFINITIVE_LOSS_NO_SAMPLETIME.tsv` | SampleTime-absent losses |
| `../high_mapping_recovery/` | HIGH conversion provenance |
