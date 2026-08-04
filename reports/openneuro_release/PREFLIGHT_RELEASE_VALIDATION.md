# Pre-flight release validation

**Generated (UTC):** 2026-07-23T21:35:50Z
**Overall status:** **PASS**

Read-only validation of the dry-run release plan before `python code/build_release.py --apply`.

Protected trees (never modified by this script): `bids/`, `derivatives/`, `raw_original/`.

## Check summary

| Check | Status | Notes |
|---|---|---|
| 1_anatomical_replacement_audit | **PASS** | planned=481 successful=481 missing_repl=0 duplicates=0 |
| 2_anatomical_integrity | **PASS** | compared=481 pass=481 fail=0 |
| 3_anatomical_json | **PASS** | checked=481 ok=481 missing=0 |
| 4_release_structure | **PASS** | mode=simulate fail=0 warn=0 |
| 5_bids_readiness | **PASS** | subjects=84 |

## Details

### 1_anatomical_replacement_audit

- **planned:** 481
- **successful:** 481
- **missing_replacements:** 0
- **missing_originals:** 0
- **duplicates:** 0
- **ambiguous:** 0
- **unmatched:** 0

### 2_anatomical_integrity

- **compared:** 481
- **pass:** 481
- **fail:** 0
- **skipped:** 0

### 3_anatomical_json

- **checked:** 481
- **ok:** 481
- **missing:** 0
- **invalid_name:** 0

### 4_release_structure

- **mode:** simulate
- **n_fail:** 0
- **n_warn:** 0

### 5_bids_readiness

- **n_subjects:** 84

## Decision

All pre-flight checks passed.

Safe to execute:

```bash
python code/build_release.py --apply
```

After the release is built, run:

```bash
bids-validator ~/scratch/release_dataset
```

