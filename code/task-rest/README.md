# task-rest — resting-state protocol

## Overview

Eyes-open resting-state fMRI with **continuous central fixation** on a black background. In BIDS this paradigm is labelled **`task-rest`**.

## Scanner trigger

`main.m` waits for FORP / keyboard triggers coded as key **`t`**, then counts triggers until **`trs = 320`** volumes have elapsed.

## Why there are no `events.tsv` files

There is no discrete trial or block structure beyond continuous fixation. The script does not write timing Results. Missing `events.tsv` for `task-rest` is **expected** and should not be treated as a conversion error. Dataset-level description: [`../../task-rest.json`](../../task-rest.json).

## Canonical script

A single exemplar is published (modal SHA-256 across sessions):

`cbf1d5c8c657920e1b5bdef74da7008f11407abce4608a7e4120e7796f210ea8`

Minor whitespace / edit variants exist in the archive but are scientifically equivalent for this fixation protocol.

See [`task-rest_protocol.md`](task-rest_protocol.md) and [`../../docs/Protocols/Rest.md`](../../docs/Protocols/Rest.md).
