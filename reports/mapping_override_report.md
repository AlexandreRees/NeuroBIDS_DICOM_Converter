# Mapping override report — SUBC044

- Generated: 2026-07-16
- Scope: reinstate `SUBC044` via documented `manual_mapping_overrides.csv`
- Constraint: validation rules unchanged; overrides apply only to explicitly listed folders

## Why SUBC044 was rejected

`generate_mapping` groups inventory by subject folder. For:

`/lustre07/scratch/alexrees/raw_original/Control/SUBC44_Session02_2025FEB19`

inventory contained **two** distinct `patient_id_raw` values:

| patient_id_raw | n_series |
|---|---:|
| `24.07.25-16:45:52-DST-1.3.12.2.1107.5.2.43.166092` | 69 |
| `SUBC044_SESSION02_2025FEB19` | 75 |

Without an approved override, `classify_participant_candidate_with_overrides` rejected the folder:

```text
Skipping invalid participant candidate: .../SUBC44_Session02_2025FEB19,
reason=conflicting patient_id_raw values (2 distinct IDs)
```

Consequences before override:

- **0** `session_mapping.csv` rows for `canonical_subject_id=SUBC044`
- No participant assignment for SUBC044
- Aggregated `mapping.csv` retained only the auxiliary-only ses-01 folder as `NO_DICOM_FOUND` with empty `participant_id`
- Mapping audit reported the remaining ERROR on that orphan row

Sibling non-overridden case (still rejected, as intended):

```text
Skipping invalid participant candidate: .../SUBC57_Session01_2025AUG11,
reason=conflicting patient_id_raw values (2 distinct IDs)
```

## How the override resolved it

### Existing mechanism (reused; not reinvented)

The pipeline already supported:

- `metadata/manual_mapping_overrides.csv`
- `load_mapping_overrides()` / `find_mapping_override()`
- consultation inside `classify_participant_candidate_with_overrides` **before** conflict rejection
- the same bypass in `validate_intra_subject_patient_ids`

Only the missing CSV row + a clearer load log were added.

### Override row inserted

```csv
path,canonical_subject,canonical_session,status,reason,confidence
/lustre07/scratch/alexrees/raw_original/Control/SUBC44_Session02_2025FEB19,SUBC044,ses-02,approved_override,"PatientID conflict interpreted as scanner/anonymization variation. Folder name and DICOM metadata consistently identify the same participant.",high
```

### Runtime evidence

```text
Loaded 1 mapping override(s) from .../manual_mapping_overrides.csv
Using manual mapping overrides: ... (1 approved_override row(s))
Approved mapping override applied: .../SUBC44_Session02_2025FEB19 (...)
Approved mapping override permits patient_id_raw conflict: .../SUBC44_Session02_2025FEB19 (...)
```

Validation was **not** disabled: SUBC057 conflict still skipped.

## Files changed

| File | Change |
|---|---|
| `metadata/manual_mapping_overrides.csv` | **Created** with approved SUBC044 override |
| `neuro_pipeline/neuro_pipeline/generate_mapping.py` | Log when mapping overrides are loaded (behavior already consulted overrides) |
| `neuro_pipeline/tests/test_generate_mapping.py` | Added tests: precedence, non-overridden rejection, reproducibility |
| `metadata/session_mapping.csv` | Regenerated (9966 rows; +144 SUBC044 series) |
| `metadata/mapping.csv` | Regenerated (140 rows; SUBC044 ses-02 present) |
| `metadata/participant_mapping.csv` | Regenerated (83 participants; SUBC044 → `sub-043`) |
| `metadata/mapping_narval_fixed.csv` | Re-repaired after regenerate (0 missing participant_ids) |
| `metadata/mapping_fix_report.*` | Updated by repair |
| `reports/mapping_audit/` | Re-audit of regenerated `mapping.csv` |
| `reports/mapping_audit_session/` | Audit of regenerated `session_mapping.csv` |
| `reports/mapping_audit_fixed/` | Audit of repaired aggregated mapping |
| `reports/mapping_override_report.md` | This report |

Previous mapping artifacts archived under `metadata/archive/` with timestamp `2026-07-16T01-51-58Z`.

## Outcome for SUBC044

| Artifact | Result |
|---|---|
| `participant_mapping.csv` | `SUBC044` → `sub-043`, `override_applied=true`, `override_source=manual_mapping_overrides.csv` |
| `session_mapping.csv` | **144** series rows, `session_label=ses-02` |
| `mapping.csv` | ses-02 `AUTO_CONFIRMED`; aux ses-01 still `NO_DICOM_FOUND` |
| `mapping_narval_fixed.csv` | both sessions linked to `sub-043` (`ses-01` + `ses-02`) |

## Validation confirmation

### Series-level (`session_mapping.csv`) — convert input

- Status: **WARNING** (0 errors)
- Findings:
  - WARNING [sequence_consistency]: unmapped/unknown series descriptions
  - WARNING [missing_acquisitions]: mandatory acquisition family gaps (dataset-wide pattern)
- Forbidden `/mnt/d` hits: **0**
- Missing participant IDs: **0**
- Invalid session labels: **none**

### Aggregated (`mapping.csv`) after regenerate (before repair)

- Status: **ERROR**
- Cause: pre-existing auxiliary-only rows with raw session labels / empty participant_ids (not SUBC044 MRI exclusion)
- SUBC044 MRI session itself was present and valid

### Aggregated repaired (`mapping_narval_fixed.csv`)

- Status: **WARNING** (0 errors)
- Recommendation from audit: **Safe to launch neuro_convert after reviewing warnings**

## Tests executed

```bash
cd ~/scratch/neuro_pipeline
python -m pytest tests/test_generate_mapping.py -q
# 23 passed
```

Including:

- `test_approved_mapping_override_reinstates_subc044_patient_id_conflict`
- `test_mapping_override_precedence_over_patient_id_conflict`
- `test_non_overridden_patient_id_conflict_remains_rejected`
- `test_mapping_override_loader_is_reproducible`

## Regeneration command

```bash
cd ~/scratch/neuro_pipeline && python -m neuro_pipeline.generate_mapping \
  --data-root /home/alexrees/scratch \
  --code-root /home/alexrees/scratch/neuro_pipeline \
  --inventory /home/alexrees/scratch/metadata/inventory_narval.csv
```

## Audit commands

```bash
cd ~/scratch/neuro_pipeline
python scripts/audit_mapping.py \
  --mapping ~/scratch/metadata/session_mapping.csv \
  --output-dir ~/scratch/reports/mapping_audit_session

python scripts/audit_mapping.py \
  --mapping ~/scratch/metadata/mapping_narval_fixed.csv \
  --output-dir ~/scratch/reports/mapping_audit_fixed
```

## Final recommendation

**Ready for neuro_convert**

Rationale:

1. Convert consumes series-level `session_mapping.csv`, which now includes SUBC044 and audits with **0 ERROR**.
2. Participant validation remains strict; only the explicitly approved SUBC044 folder is reinstated.
3. SUBC057 conflict remains rejected (proves overrides are scoped).
4. Remaining warnings are acquisition-coverage / unknown-sequence notices, not subject-identity failures.

Optional follow-up (not blocking convert): add a second approved override for `SUBC57_Session01_2025AUG11` after the same human review standard used for SUBC044.
