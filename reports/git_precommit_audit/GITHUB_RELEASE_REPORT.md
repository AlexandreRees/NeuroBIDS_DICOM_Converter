# GitHub release report

Generated (UTC): 2026-08-04T13:59:29Z

## Commit

- commit hash: `fd11df1db82bac15e4b3f0d5ece7258ed4f4e453`
- date (UTC): 2026-08-04T13:59:29Z
- branch: `main`
- message: `Initial Scientific Data repository: code, metadata, audits and documentation`
- files in commit (git ls-files): **1489**

## Remote

- intended remote: `https://github.com/AlexandreRees/neuro_pipeline.git`
- remote configured in `.git/config`: **NO** (filesystem refused writes to `.git/config`: `Device or resource busy`)
- push status: **NOT COMPLETED** — GitHub HTTPS authentication unavailable in this environment (`could not read Username for 'https://github.com'`; no `gh`, no `GITHUB_TOKEN`, no SSH key resolved for GitHub)

## Confirmations (committed tree)

- "No imaging data were committed." — verified at staging: 0 NIfTI, 0 DICOM, 0 raw imaging trees
- "No PHI-containing raw data were committed." — `bids/`, `sourcedata/`, `raw_original/`, `derivatives/`, `release_dataset/`, `reports/shards/`, large deidentify dumps excluded

## Manual push instructions

On a machine/login with GitHub credentials (PAT or `gh auth login`):

```bash
cd /lustre07/scratch/alexrees
# If .git/config becomes writable:
git remote add origin https://github.com/AlexandreRees/neuro_pipeline.git || \
  git remote set-url origin https://github.com/AlexandreRees/neuro_pipeline.git
git push -u origin main

# Or push without saving remote:
git push -u https://github.com/AlexandreRees/neuro_pipeline.git main
```

## Related artefacts

- `reports/git_precommit_audit/GIT_PRECOMMIT_AUDIT.md`
- `reports/git_precommit_audit/STAGING_FINAL_REPORT.md`
- `README.md`, `CITATION.cff`, `.gitignore`
