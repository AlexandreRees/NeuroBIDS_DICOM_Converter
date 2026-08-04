# Event metadata availability

Validated task-fMRI event files are provided for 456 acquisitions.
Files were generated only when a unique correspondence between
experimental logs and BOLD acquisitions could be established.
Acquisitions lacking an unambiguous mapping were intentionally
released without event files.

Of 507 non-phase `task-fmri` BOLD runs, 456 (89.9%) include a validated
`*_events.tsv`. The remaining 51 runs were withheld from event release
because of duplicate ProtocolName matches (n = 32), missing grating
Results (n = 8), duplicate or missing `scan_info` trigger files
(n = 5 and n = 4), or MATLAB versus ProtocolName numbering mismatch
(n = 2). No timing was manually inferred and no synthetic events were
generated.

See `FUNCTIONAL_EVENT_METADATA_VALIDATION.md` for full validation criteria
and `Figure_Functional_Event_Metadata_Status.png` for a summary figure.
