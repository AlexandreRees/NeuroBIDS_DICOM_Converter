# Publication recommendations for a Scientific Data dataset

Generated: `2026-07-21T15:28:20.504207+00:00`

## Release recommendation

**Do not publish the associated-file tree as-is.** Build and validate a separate release candidate containing only scientifically justified, de-identified, rights-cleared files.

## Quantitative basis

- Audited files: **5756**
- Potential PHI: **2911**
- Require de-identification: **2911**
- Direct-release candidates: **2832**
- Require manual review: **242**
- Audiovisual/copyright-flagged: **104**

## Recommended Scientific Data package

1. Deposit BIDS imaging plus validated `events.tsv`, physiology, and eye-tracking derivatives.
2. Include de-identified source timing files only when needed to reproduce conversion.
3. Publish converter code, data dictionaries, channel units, sampling rates, synchronization methods, and run-mapping provenance.
4. Document exclusions and counts in the Data Records and Technical Validation sections.
5. Provide stimuli only under a compatible license; otherwise publish stimulus identifiers, citations, checksums, and acquisition instructions.
6. State that direct identifiers, dates, institution/operator fields, scanner UIDs, and local subject IDs were removed or consistently shifted.
7. Obtain institutional privacy/ethics review of the final release candidate; automated scanning is not sufficient approval.

## Required gates before release

- Zero unresolved direct identifiers in release files and filenames.
- Manual adjudication of all `Cannot determine` findings.
- BIDS Validator pass plus modality-specific checks for events, physiology, and eye tracking.
- Copyright/license evidence for every redistributed stimulus.
- Reproducible source-to-release manifest with checksums stored outside the public raw source tree.
