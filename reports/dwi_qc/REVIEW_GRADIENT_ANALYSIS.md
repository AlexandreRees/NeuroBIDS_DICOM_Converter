# dwigradcheck REVIEW investigation

Generated: 2026-07-23 15:18:48 UTC

## Scope

- REVIEW scans analysed: **111**
- No bvec files were modified.

## Suggestion class counts

- `axis_flip_and_swap`: **70**
- `axis_swap`: **25**
- `axis_flip`: **16**

## Top-ranked (flip, permutation, basis) configurations

- **8**: flip=`2`, perm=`(0, 1, 2)`, basis=`scanner`
- **6**: flip=`none`, perm=`(1, 0, 2)`, basis=`image`
- **6**: flip=`2`, perm=`(1, 0, 2)`, basis=`scanner`
- **5**: flip=`1`, perm=`(1, 0, 2)`, basis=`scanner`
- **5**: flip=`1`, perm=`(1, 0, 2)`, basis=`image`
- **4**: flip=`none`, perm=`(1, 2, 0)`, basis=`scanner`
- **4**: flip=`none`, perm=`(1, 0, 2)`, basis=`scanner`
- **4**: flip=`0`, perm=`(0, 2, 1)`, basis=`scanner`
- **4**: flip=`0`, perm=`(2, 0, 1)`, basis=`scanner`
- **4**: flip=`1`, perm=`(1, 2, 0)`, basis=`scanner`
- **4**: flip=`2`, perm=`(1, 0, 2)`, basis=`image`
- **3**: flip=`none`, perm=`(1, 2, 0)`, basis=`image`
- **3**: flip=`0`, perm=`(0, 2, 1)`, basis=`image`
- **3**: flip=`0`, perm=`(1, 0, 2)`, basis=`image`
- **3**: flip=`none`, perm=`(2, 0, 1)`, basis=`scanner`

## Acquisition enrichment

### By run entity

- `run-02`: **102**
- `run-01`: **3**
- `run-05`: **3**
- `run-04`: **2**
- `run-03`: **1**

### By b-value scheme

- `0,1000,2000`: **108**
- `0,1000`: **3**

## Single-orientation hypothesis

- Most common top suggestion accounts for **8/111** (7.2%) scans.
- Shared single orientation explaining ≥80% of REVIEW: **NO**.

REVIEW cases do **not** share one common corrective transform. However, they are strongly enriched in `run-02` multiphase / high-direction shells. This is best reported as a **protocol-/acquisition-type observation** about `dwigradcheck` ranking instability (or acquisition-dependent gradient geometry), not as 111 independent random failures.

## Software/reporting note (PASS classifier)

In `run_dwi_qc.interpret_dwigradcheck`, axis flip value `0` is treated as equivalent to `none`. In MRtrix, `0` means flip axis 0.
- PASS rows that are actually non-identity under this rule: **3**

- `sub-002` `ses-01` `run-02`: flip=`0` perm=`(0, 1, 2)` basis=`image`
- `sub-015` `ses-01` `run-02`: flip=`0` perm=`(0, 1, 2)` basis=`scanner`
- `sub-049` `ses-01` `run-02`: flip=`0` perm=`(0, 1, 2)` basis=`scanner`

Full table: `review_gradient_analysis.tsv`
