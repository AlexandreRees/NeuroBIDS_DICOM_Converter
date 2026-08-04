# Benchmark: permanent `deid_dicom/` vs streaming temporary de-identification

**Context.** On this Scratch project the Lustre inode quota is **1,000,000**. Before redesign, inode use was already at **100%** with:

| Tree | Approximate inode count |
|---|---:|
| `raw_original/` | ~912,000 |
| `deid_dicom/` (partial Control mirror) | ~86,600 |
| code / metadata / reports | ~1,400 |
| **Total** | **1,000,000 (quota full)** |

Removing the derived `deid_dicom/` mirror freed ~85,000 inodes and restored write capacity. A full permanent mirror of all cohorts would approach **~1.8M inodes** (raw + deid), which is **infeasible** under a 1M inode quota even when disk bytes remain available (~17 TB free).

## Comparison

| Metric | Old: permanent `deid_dicom/` | New: streaming temp workspace |
|---|---|---|
| Permanent de-identified DICOM files | ≈ number of source DICOM files (~900k at full scale) | **0** |
| Peak extra inodes during processing | ~900k (full mirror) | **≈ files in one acquisition** (typically tens–thousands) |
| Peak extra disk during processing | Full mirror size | One acquisition (then deleted) |
| `raw_original/` modified? | No | No |
| Anonymization policy | PS3.15-oriented custom policy | **Identical** (`process_dicom_file`) |
| BIDS mapping / naming | Unchanged | **Identical** |
| Provenance | `deidentify_report.csv`, manifest, date shifts | Same + `processing_manifest.csv` |
| Resume after interrupt | Partial `--subject` / `--force` | Per-acquisition checkpoint (`resume=true`) |
| Failure handling | Failed rows in report; tree remains | Temp dir **retained** (`keep_failed_cases=true`) |
| Processing time | De-id entire tree, then convert | De-id+convert per series (similar work; less I/O wait for full mirror) |

## Estimated full-cohort permanent mirror cost

Assuming ~912k DICOM files in `raw_original/`:

- Permanent mirror inodes ≈ **912k** additional
- Combined with raw ≈ **1.82M** inodes → **exceeds** 1M quota by ~82%
- Streaming peak ≈ max series length (often &lt; 1k files) → **well within** quota

## Processing time

Wall-clock time is dominated by DICOM read/write and dcm2niix. Streaming performs the **same scientific work** per series but avoids:

1. Writing a second full archive before any conversion starts
2. A second full-tree privacy walk over `deid_dicom/`

Exact timings depend on cluster load; measure with:

```bash
/usr/bin/time -v python -m neuro_pipeline.convert_to_bids \
  --data-root ~/scratch --code-root ~/scratch/neuro_pipeline --seed 42 --subject SUBC001
```

## Recommendation

Use **streaming** (default) on inode-constrained HPC. Reserve `--permanent-deid` only for sites with ample inodes and a requirement for a durable de-identified DICOM tree.
