# Level-1 associated-data conversion code

This directory records the strict conversion logic used for the public release.

- `convert_events.py` requires actual scanner `triggerTimes`, a recorded
  paradigm, matching run identities, and matching stimulus orders. It never
  uses a default TR or synthesized timing.
- `convert_physio.py` refuses conversion unless sampling frequency and
  BIDS-relative start time are explicit. Vendor constants are never guessed.
- `deidentify_release.py` scans generated scientific derivatives. Source files
  are never edited or copied.

Ambiguous inputs are represented only by non-identifying references in
`review_required/manual_review.tsv`.
