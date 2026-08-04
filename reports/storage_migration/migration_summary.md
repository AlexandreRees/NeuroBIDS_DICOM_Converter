# Storage migration summary — raw_original → /project

**Status: NEEDS REVIEW**

Date: 2026-07-19  
Host: Narval  
User: alexrees  
Project: def-amirs

---

## Verdict

Full migration of `~/scratch/raw_original` to `/project/def-amirs/raw_original` is **blocked by the project inode quota**.

| Resource | Before (approx) | After cleanup | Notes |
| --- | --- | --- | --- |
| `/scratch` files | **1000K / 1000K** | **914K / 1000K** | ~86K inodes freed |
| `/scratch` space | ~2344 GB | ~2260 GB | tmp/caches removed |
| `/project` files | 310K / 500K | 310K / 500K | ~190K free |
| `raw_original` files | **900 375** | **900 375** (source intact) | needs ~990K free on project with headroom |

**Required:** request a `/project/def-amirs` **file (inode) quota increase** to **≥ 1.5M** (preferably 2M), then re-run:

```bash
bash ~/scratch/neuro_pipeline/scripts/migrate_raw_original_to_project.sh
# after validation OK:
bash ~/scratch/neuro_pipeline/scripts/migrate_raw_original_to_project.sh --cutover
```

---

## What was done

### 1. Audit
- `storage_before.txt` — quotas, file counts, pipeline paths, capacity check

### 2. Safe inode cleanup (no DICOM / BIDS / derivatives / metadata)
- `__pycache__` under `neuro_pipeline`
- `~/scratch/tmp_processing/*` (~69 794 files)
- misplaced `~/scratch/defacing_env`
- `~/scratch/.pydeps*` caches
- See `cleanup_report.txt`

### 3. Migration attempt
- Destination created: `/project/def-amirs/raw_original`
- An initial rsync briefly started due to a parser bug (`310K/ 500K` spacing), then **killed**
- Source **not** renamed/deleted; **no symlink cutover**
- Partial destination: **72 files** (safe to resume later with rsync)
- Guard fixed; subsequent runs exit with `VALIDATION: BLOCKED` (exit 2)
- Logs: `raw_original_rsync.log`, `raw_original_validation.txt`

### 4. Pipeline path adaptation (non-breaking)
- `config/paths.yaml` — canonical `raw_root` / `scratch_root` / `project_root`
- `neuro_pipeline_config.json` — absolute `data_root` on scratch
- `neuro_pipeline/utils/paths.py` — loads `paths.yaml`; honors `RAW_ROOT` / `NEURO_PIPELINE_RAW_ORIGINAL`
- Empty project `raw_root` is **not** forced until cohorts exist there
- Live data still read from `~/scratch/raw_original`

### 5. Path check
```
PATH CHECK PASSED
```
(`path_check.txt`)

### 6. Defacing environment (home, not scratch)
```bash
~/defacing_env
# pip install --no-index pydeface nilearn  → DEFACING ENV OK
```

---

## New paths (target layout)

| Role | Path |
| --- | --- |
| Raw DICOM (target) | `/project/def-amirs/raw_original` |
| Raw DICOM (current) | `/home/alexrees/scratch/raw_original` |
| Scratch / data root | `/home/alexrees/scratch` |
| Project root | `/project/def-amirs` |
| Code | `/home/alexrees/scratch/neuro_pipeline` |
| Defacing venv | `/home/alexrees/defacing_env` |

After successful cutover, compatibility symlink will be:

`~/scratch/raw_original` → `/project/def-amirs/raw_original`

---

## Files modified / created

### Created
- `neuro_pipeline/config/paths.yaml`
- `neuro_pipeline/scripts/migrate_raw_original_to_project.sh`
- `neuro_pipeline/scripts/check_paths.sh`
- `~/scratch/reports/storage_migration/*`
- `~/defacing_env/` (venv)

### Modified
- `neuro_pipeline/neuro_pipeline/utils/paths.py` (paths.yaml + `RAW_ROOT`)
- `neuro_pipeline/neuro_pipeline_config.json` (`data_root` absolute)
- `neuro_pipeline/run_defacing_sub022.slurm` (venv → `~/defacing_env`)
- `neuro_pipeline/docs/defacing.md` (venv location / `--no-index`)

### Not modified
- DICOM contents under `raw_original`
- `bids/`, `derivatives/`, `metadata/`
- BIDS filenames

---

## Quota before / after

| | Scratch files | Scratch space | Project files |
| --- | --- | --- | --- |
| Before | 1000K/1000K | ~2344 GB | 310K/500K |
| After | 914K/1000K | ~2260 GB | 310K/500K |

---

## Next actions (PI / user)

1. **Request inode quota increase** for `def-amirs` on `/project` (≥ 1.5M files).  
2. Re-run migration script (rsync `--checksum` will resume).  
3. Confirm `raw_original_validation.txt` shows `status: OK`.  
4. Run `--cutover` (rename → `raw_original_backup`, create symlink).  
5. Re-run `bash scripts/check_paths.sh`.  
6. Only then delete `~/scratch/raw_original_backup` after an explicit second verification.
