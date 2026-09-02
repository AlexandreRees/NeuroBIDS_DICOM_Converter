# Conversion Queue Manager

Optional page for large multi-subject conversions. It sits **above** the existing
`BatchManager` / `ConversionManager` and does not alter DICOM parsing, dcm2niix, or
BIDS export internals.

## Location

Main navigation → **Queue**

## Capabilities

- Add / remove / reorder jobs
- Start / Pause / Resume queue
- Cancel selected jobs
- Retry failed jobs
- Progress: subject, step, series message, percent
- Persist queue to `conversion_queue.json`
- Log status changes to `conversion_queue.log`

State files live in the per-user application state directory (see `user_state_dir()`).

## Job statuses

`QUEUED` · `ANALYZING` · `CONVERTING` · `VALIDATING` · `COMPLETED` · `FAILED` · `CANCELLED` · `PAUSED`

On application restart, in-progress jobs are recovered as `QUEUED`.

## Execution model

Jobs run **sequentially**. Each job calls `BatchManager.convert_folder(...)` with the
job’s subject/session and folders. Pause prevents starting the next job; resume
continues from remaining `QUEUED` items.
