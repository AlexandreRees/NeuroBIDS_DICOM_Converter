# Repository Data Safety Policy

This repository contains software source code only.

Never commit:

- DICOM files
- NIfTI files
- participant identifiers
- patient names
- dates of birth
- medical record numbers
- research datasets
- clinical metadata
- study-specific mapping tables
- McGill internal paths
- Compute Canada / Narval paths
- SSH keys
- API tokens
- passwords
- credentials
- private configuration files
- generated logs containing local paths or identifiers

Research data must remain outside this repository.

Examples and tests must use synthetic or explicitly redistributable data.

Before any public release:

1. Run the repository audit.
2. Review `git diff`.
3. Review `git status`.
4. Review the complete Git history.
5. Verify that no study-specific data are included.
6. Verify that no credentials are included.
7. Verify that no local filesystem paths are included.
8. Verify that all example data are synthetic or redistributable.
