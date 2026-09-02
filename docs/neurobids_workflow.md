# NeuroBIDS workflow

NeuroBIDS is a scientific neuroimaging dataset curation interface:

> **From raw neuroimaging data to a research-ready dataset.**

```text
DISCOVER → MAP → AUDIT → PROTECT → RELEASE
```

Conversion, queue, settings, and logs remain available as tools. They are not the product’s conceptual center.

## Stages

| Stage | What you do |
|-------|-------------|
| **Discover** | Select a DICOM folder. Review subject, session, acquisition, file, and modality counts from the existing scan / `DatasetContext`. |
| **Map** | Curate the BIDS conversion plan. Subjects · BIDS Preview · acquisition inspector. |
| **Audit** | Review issues already known to NeuroBIDS (`plan.validate()`, `DatasetContext.metadata_issues`). No invented health score. |
| **Protect** | Original DICOM is read-only. PatientName is never exported to Copilot. |
| **Release** | Same deterministic checks, stated honestly. Optional text report. Not a publication certificate. |

Jump between stages at any time. The workflow is a guide, not a locked wizard.

## Role of Copilot

**NeuroBIDS Copilot** is a dataset-aware research assistant. It is a natural-language interface over the same typed tools as before.

It is not a second conversion engine, not a chatbot glued to Convert, and not a filesystem agent.

```text
                NEUROBIDS
                    │
        ┌───────────┴───────────┐
        │                       │
   Deterministic Core       Copilot
        │                       │
   BIDS / DICOM / QC      Natural language
   validation / export       reasoning
        │                       │
        └───────────┬───────────┘
                    │
                ChangeSet
                    │
             Human approval
                    │
                  Apply
```

The Copilot reasons. The deterministic core is the source of truth.

## Safety model

```text
LLM → typed tools → deterministic NeuroBIDS logic → ChangeSet → explicit Apply
```

- The LLM never accesses the filesystem, DICOM pixels, the shell, Python execution, dcm2niix, or `ConversionManager`.
- Mutations only update the in-memory `BIDSConversionPlan`.
- **Original DICOM files are never modified.**
- Apply stays disabled unless the ChangeSet is valid, the plan fingerprint matches, and conversion is not running.
- NeuroBIDS is fully usable with no LLM provider.

## Contextual Copilot

Select a subject, session, or acquisition on Map. The Copilot session receives that selection as metadata (no pixels, no paths of interest for PHI).

“Why was this classified as func?” is then interpreted against the selected acquisition.

Open or hide Copilot with the header button or **Ctrl+J**. The BIDS Preview remains the primary workspace. **Ctrl+K** opens a command palette that routes to the same Copilot `ask()` path or to a stage (Audit, Release, Map).

## Reviewing proposed changes

When Copilot proposes a mutation it shows a before/after diff, impact counts, and the guarantees above. **Reject** discards the ChangeSet. **Apply Changes** is the only way a proposal becomes the live plan.

Manual BIDS Preview edits remain compatible with Copilot. If you edit the plan after a proposal, the ChangeSet is stale and Apply stays disabled.

## Configure Copilot

Optional environment variables (Settings explains them; they are not stored in YAML):

```text
NEUROBIDS_LLM_PROVIDER   openai | azure | local | none
NEUROBIDS_LLM_MODEL
NEUROBIDS_LLM_API_KEY
NEUROBIDS_LLM_BASE_URL
```

If no provider is configured:

> Copilot is currently unavailable. The rest of NeuroBIDS remains fully functional.

## Conversion

DICOM → NIfTI still runs from **Conversion** (and Queue). Map’s **Continue to Conversion** jumps there. The converter still consumes the same `BIDSConversionPlan`.
