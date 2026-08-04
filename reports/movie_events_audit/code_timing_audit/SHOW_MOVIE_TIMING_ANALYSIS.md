# Show_movie.m timing analysis

**Generated:** `2026-07-28T14:38:24.668263+00:00`  
**Unique SHA256 (truncated) versions:** 3  
**Copies observed:** 156

## Scanner trigger

**FOUND**

Evidence (representative `83ade79574081031`):

```
L79: psychtoolbox_forp_id=0; | L92: keysOfInterest(KbName('t'))=1; | L93: % only look for t as trigger | L94: KbQueueCreate(psychtoolbox_forp_id, keysOfInterest); | L95: KbQueueStart; | L99: KbQueueWait
```

Notes: Scripts wait for FORP-mapped key `t` via `KbQueueWait`. This is **runtime** trigger handling, not a saved timestamp array.

## Screen Flip timestamps

**NOT FOUND**

`Screen('Flip')` called without capturing return value as `vbl`: **YES**

Evidence:

```
L74: % Flip info to the real window | L75: Screen('Flip', win); | L138: Screen('Flip', win);
```

## Frame timestamps

**NOT FOUND**

Frame loop present: **FOUND**

Evidence:

```
L88: Screen('PlayMovie', movie, 1); | L100: while 1 | L107: Screen('PlayMovie', movie, 0); | L118: tex = Screen('GetMovieImage', win, movie); | L146: Screen('PlayMovie', movie, 0);

```

## Saved timing

**NOT FOUND**

Evidence:

```
L93: % only look for t as trigger
```

## Summary table

| Question | Result |
|---|---|
| A) Scanner trigger *reception* in code | FOUND |
| B) Flip timestamps *captured* | NOT FOUND |
| C) Timing *saved* to disk | NOT FOUND |
| D) Frame playback loop | FOUND |
| E) Per-frame timestamps logged | NOT FOUND |
