# MRI acquisition parameters

MRI acquisition parameters. Siemens Prisma, 3 T (syngo MR E11 / XA30; HeadNeck_64). Parameters from BIDS JSON sidecars. Localizers, SBRef, physiological logs and derived diffusion maps omitted. Reverse-PE b0 not present in released BIDS DWI; EPI distortion correction uses spin-echo field maps.

| Category | Sequence | BIDS label | Acquisition parameters |
|---|---|---|---|
| Anatomical | T1-weighted MPRAGE | `T1w` | TR 2500 ms; TE 2.2 ms; Flip angle 8°; 0.8×0.8×0.8 mm; in-plane accel. 2 |
| Anatomical | White-matter-nulled MPRAGE | `T1w (WMn)` | TR 4000 ms; TE 3.8 ms; Flip angle 7°; 1×1×1 mm; in-plane accel. 2 |
| Anatomical | 3D FLAIR | `FLAIR` | TR 6000 ms; TE 357 ms; Flip angle 120°; 0.8×0.8×0.8 mm; in-plane accel. 2 |
| Field map | Spin-echo EPI (AP/PA) | `dir-AP/PA_epi` | TR 9710 ms; TE 66 ms; Flip angle 90°; 2 mm isotropic; PE AP/PA; TotalReadoutTime 0.0597 s |
| Functional | Resting-state fMRI (1 run) | `task-rest_bold` | TR 937 ms; TE 37 ms; Flip angle 52°; 2×2×2 mm; MB 8; 320 volumes; PE AP |
| Functional | Movie fMRI (4 runs) | `task-movie_bold` | TR 937 ms; TE 37 ms; Flip angle 52°; 2×2×2 mm; MB 8; 210 volumes; PE AP |
| Functional | Task fMRI (4 runs) | `task-fmri_bold` | TR 937 ms; TE 37 ms; Flip angle 52°; 2×2×2 mm; MB 8; 226 volumes; PE AP |
| Functional | Control fMRI (3 runs) | `task-control_bold` | TR 937 ms; TE 37 ms; Flip angle 52°; 2×2×2 mm; MB 8; 20 volumes; PE AP/PA |
| Diffusion | Multidirection DWI | `dwi` | TR 3500 ms; TE 75 ms; Flip angle 90°; 1 mm isotropic (protocol); MB 2; in-plane accel. 3; b = 0/1000/2000 s/mm²; ~365 directions; 20 b0; PE AP |
| Diffusion | RESOLVE trace DWI | `dwi (RESOLVE)` | TR 4140 ms; TE 51 ms; Flip angle 180°; ≈1.4 mm; in-plane accel. 3; b = 0/1000 s/mm²; 11 directions; 4 b0; PE AP |
| Calibration | B1 map (turbo flash) | `TB1TFL` | TR 4000 ms; TE 1.8 ms; Flip angle 8°; 3.438×3.438×10 mm |
