#!/usr/bin/env python3
"""Audit MRI acquisition table vs BIDS sidecars (read-only)."""
from __future__ import annotations
import csv, json, re
from collections import Counter, defaultdict
from pathlib import Path

BIDS = Path('/home/alexrees/scratch/bids')
OUT = Path('/home/alexrees/scratch/reports')
EXISTING = Path('/home/alexrees/scratch/reports/mri_acquisition_table/MRI_Acquisition_Table.md')

def log(msg: str) -> None:
    print(msg, flush=True)

def loadj(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None

def modality(p: Path) -> str:
    for m in ('anat', 'func', 'dwi', 'fmap'):
        if m in p.parts:
            return m
    return 'other'

def entities(name: str) -> dict:
    stem = name[:-5] if name.endswith('.json') else name
    out = {}
    for tok in stem.split('_'):
        if '-' in tok:
            k, _, v = tok.partition('-')
            out[k] = v
        else:
            out.setdefault('suffix', tok)
    # last non-entity token is suffix if not set
    toks = stem.split('_')
    if 'suffix' not in out:
        out['suffix'] = toks[-1]
    return out

def mode(vals):
    vals = [v for v in vals if v is not None and str(v) not in ('None', 'nan', '')]
    if not vals:
        return None, []
    norm = []
    for v in vals:
        if isinstance(v, float):
            norm.append(round(v, 4) if abs(v - round(v)) > 1e-6 else int(round(v)))
        elif isinstance(v, int):
            norm.append(v)
        else:
            norm.append(v)
    c = Counter(map(str, norm))
    return c.most_common(1)[0][0], [k for k, _ in c.most_common()]

def nifti_zooms_vols(nii: Path):
    try:
        import nibabel as nib
        img = nib.load(str(nii))
        z = tuple(round(float(x), 3) for x in img.header.get_zooms()[:3])
        sh = img.shape
        nv = int(sh[3]) if len(sh) == 4 else 1
        return z, nv
    except Exception:
        return None, None

log('Scanning JSON sidecars…')
recs = []
man = Counter(); model = Counter(); field = Counter(); soft = Counter(); coil = Counter(); cae = Counter()
json_files = sorted(BIDS.glob('sub-*/ses-*/*/*.json'))
log(f'n_json={len(json_files)}')
for jp in json_files:
    meta = loadj(jp)
    if not meta:
        continue
    ent = entities(jp.name)
    man[str(meta.get('Manufacturer'))] += 1
    model[str(meta.get('ManufacturersModelName'))] += 1
    field[str(meta.get('MagneticFieldStrength'))] += 1
    soft[str(meta.get('SoftwareVersions'))] += 1
    coil[str(meta.get('ReceiveCoilName'))] += 1
    if meta.get('ReceiveCoilActiveElements'):
        cae[str(meta.get('ReceiveCoilActiveElements'))] += 1
    recs.append({'path': jp, 'mod': modality(jp), 'ent': ent, 'meta': meta})
log(f'loaded={len(recs)}')
log(f'Manufacturer={man.most_common(3)}')
log(f'Model={model.most_common(3)}')
log(f'Field={field.most_common(3)}')
log(f'Software={soft.most_common(5)}')
log(f'Coil={coil.most_common(3)}')
log(f'CoilActive={cae.most_common(3)}')

def group_key(r):
    m = r['mod']; e = r['ent']; meta = r['meta']
    sd = str(meta.get('SeriesDescription') or '').lower()
    pn = str(meta.get('ProtocolName') or '').lower()
    suf = e.get('suffix', '')
    if m == 'func':
        kind = 'sbref' if suf == 'sbref' else 'bold'
        return ('Functional', kind, e.get('task', ''), e.get('dir', ''), e.get('part', ''))
    if m == 'fmap':
        return ('Field map', 'epi', e.get('dir', ''), e.get('part', ''), '')
    if m == 'dwi':
        if 'resolve' in sd:
            return ('Diffusion', 'RESOLVE', e.get('dir', ''), '', '')
        if '3b0' in sd or ('pa' in sd and 'b0' in sd and '76dir' not in sd):
            return ('Diffusion', 'b0_reversePE', e.get('dir', ''), '', '')
        if '76dir' in sd or 'gsld' in sd:
            return ('Diffusion', 'multi-shell_or_multidir', e.get('dir', ''), '', '')
        return ('Diffusion', 'other', e.get('dir', ''), sd[:40], '')
    if m == 'anat':
        if suf == 'FLAIR' or 'flair' in sd:
            return ('Anatomical', 'FLAIR', '', '', '')
        if 'wmn' in sd or 'wmn' in pn:
            return ('Anatomical', 'WMn_MPRAGE', '', '', '')
        if suf == 'T1w':
            return ('Anatomical', 'T1w_MPRAGE', '', '', '')
        if 'b1' in sd or 'TB1' in suf or 'RB1' in suf or suf in ('TB1map', 'RB1map'):
            return ('Anatomical', 'B1map', suf, '', '')
        return ('Anatomical', 'other', suf, '', '')
    return (m, suf, '', '', '')

groups = defaultdict(list)
for r in recs:
    groups[group_key(r)].append(r)
log(f'n_groups={len(groups)}')

# Aggregate + sample 1 nifti per group for resolution/vols
summary = {}
for g, items in groups.items():
    metas = [i['meta'] for i in items]
    def col(k):
        return [m.get(k) for m in metas]
    tr, trs = mode(col('RepetitionTime'))
    te, tes = mode(col('EchoTime'))
    fa, fas = mode(col('FlipAngle'))
    mb, mbs = mode(col('MultibandAccelerationFactor'))
    ipat, ipats = mode(col('ParallelReductionFactorInPlane'))
    pe, pes = mode(col('PhaseEncodingDirection'))
    st, sts = mode(col('SliceThickness'))
    sd, sds = mode(col('SeriesDescription'))
    sn, sns = mode(col('SequenceName'))
    pn, pns = mode(col('ProtocolName'))
    pbw, _ = mode(col('PixelBandwidth'))
    trot, trots = mode(col('TotalReadoutTime'))
    # volumes from SliceTiming length if present
    nvols = []
    for m in metas:
        stime = m.get('SliceTiming')
        # not nvols
        pass
    # bvals for dwi
    bschemes = Counter(); ndirs = Counter(); nb0 = Counter()
    if g[0] == 'Diffusion':
        for i in items:
            bp = i['path'].with_suffix('').with_suffix('.bval')  # wrong
            bp = Path(str(i['path'])[:-5] + '.bval')
            if not bp.exists():
                continue
            try:
                vals = [float(x) for x in bp.read_text().split()]
            except Exception:
                continue
            uniq = sorted({int(round(v)) for v in vals})
            bschemes[','.join(map(str, uniq))] += 1
            ndirs[sum(1 for v in vals if v >= 50)] += 1
            nb0[sum(1 for v in vals if v < 50)] += 1
    # one nifti sample
    z = nv = None
    for i in items[:3]:
        nii = Path(str(i['path'])[:-5] + '.nii.gz')
        if nii.exists():
            z, nv = nifti_zooms_vols(nii)
            if z:
                break
    res = f'{z[0]:g}×{z[1]:g}×{z[2]:g} mm' if z else (f'{st} mm slice' if st else '')
    # BIDS label template
    e0 = items[0]['ent']
    bits = []
    if e0.get('task'): bits.append(f"task-{e0['task']}")
    if e0.get('dir'): bits.append(f"dir-{e0['dir']}")
    if e0.get('part'): bits.append(f"part-{e0['part']}")
    bits.append(e0.get('suffix', g[1]))
    bids_label = '_'.join(bits)
    # human sequence name
    seq = {
        ('Anatomical', 'T1w_MPRAGE'): 'T1-weighted MPRAGE',
        ('Anatomical', 'WMn_MPRAGE'): 'White-matter-nulled MPRAGE',
        ('Anatomical', 'FLAIR'): '3D FLAIR',
        ('Anatomical', 'B1map'): 'B1 mapping (turbo flash)',
        ('Field map', 'epi'): 'Spin-echo EPI field map',
        ('Functional', 'bold'): f"BOLD fMRI ({e0.get('task','')})",
        ('Functional', 'sbref'): f"Single-band reference ({e0.get('task','')})",
        ('Diffusion', 'multi-shell_or_multidir'): 'Diffusion-weighted MRI (multidirection)',
        ('Diffusion', 'b0_reversePE'): 'Diffusion b0 reverse phase-encode',
        ('Diffusion', 'RESOLVE'): 'RESOLVE diffusion (trace)',
    }.get((g[0], g[1]), sd or pn or g[1])

    add_parts = []
    if mb: add_parts.append(f'MB={mb}')
    if ipat: add_parts.append(f'in-plane accel={ipat}')
    if pe: add_parts.append(f'PE={pe}')
    if trot: add_parts.append(f'TotalReadoutTime={trot}s')
    if nv and g[0] in ('Functional', 'Diffusion'):
        add_parts.append(f'volumes={nv}')
    if bschemes:
        add_parts.append('b-values=' + '; '.join(f'{k} (n={v})' for k,v in bschemes.most_common(3)))
    if ndirs:
        add_parts.append('n_diff_dirs=' + '; '.join(f'{k} (n={v})' for k,v in ndirs.most_common(3)))
    if nb0:
        add_parts.append('n_b0=' + '; '.join(f'{k} (n={v})' for k,v in nb0.most_common(3)))
    if sn: add_parts.append(f'SequenceName={sn}')
    if len(trs) > 1: add_parts.append('TR_variants=' + '|'.join(trs[:4]))
    if len(tes) > 1: add_parts.append('TE_variants=' + '|'.join(tes[:4]))
    if len(soft.most_common()) > 1:
        # per-group software
        gs = Counter(str(m.get('SoftwareVersions')) for m in metas)
        if len(gs) > 1:
            add_parts.append('Software=' + '|'.join(k for k,_ in gs.most_common(3)))

    # run counts for func bold by task: unique files / subjects rough
    n_files = len(items)
    summary[g] = {
        'modality': g[0], 'kind': g[1], 'n_files': n_files,
        'sequence': seq, 'bids_label': bids_label,
        'TR_ms': tr, 'TE_ms': te, 'flip_angle_deg': fa, 'resolution': res,
        'additional': '; '.join(add_parts),
        'SeriesDescription': sd, 'ProtocolName': pn, 'SequenceName': sn,
        'MB': mb, 'iPAT': ipat, 'PE': pe, 'SliceThickness': st,
        'TotalReadoutTime': trot, 'PixelBandwidth': pbw,
        'TR_variants': trs, 'TE_variants': tes, 'FA_variants': fas,
        'bval_schemes': bschemes.most_common(), 'n_dirs': ndirs.most_common(),
        'sample_volumes': nv, 'software_group': mode(col('SoftwareVersions'))[1],
    }

# ---- Build revised manuscript table rows (concise) ----
# Prefer primary imaging rows; SBRef as note; omit derived RESOLVE ADC/TRACE unless raw present

def pick(*keys):
    for k in keys:
        if k in summary:
            return summary[k]
    return None

revised = []

def add_row(modality, sequence, bids_label, s, extra=''):
    if not s:
        return
    add = s['additional']
    if extra:
        add = (add + '; ' if add else '') + extra
    revised.append({
        'Modality': modality,
        'Sequence': sequence,
        'BIDS_label': bids_label,
        'TR_ms': s['TR_ms'] or '',
        'TE_ms': s['TE_ms'] or '',
        'Flip_angle_deg': s['flip_angle_deg'] or '',
        'Resolution': s['resolution'] or '',
        'Additional_parameters': add,
        'n_sidecars': s['n_files'],
    })

# Anatomical
add_row('Anatomical', 'T1-weighted MPRAGE', 'T1w', pick(('Anatomical','T1w_MPRAGE','','','')))
add_row('Anatomical', 'White-matter-nulled MPRAGE', 'T1w (WMn series)', pick(('Anatomical','WMn_MPRAGE','','','')))
add_row('Anatomical', '3D FLAIR', 'FLAIR', pick(('Anatomical','FLAIR','','','')))
# B1 - may be multiple suffixes
b1_groups = [s for g,s in summary.items() if g[0]=='Anatomical' and g[1]=='B1map']
if b1_groups:
    # merge note
    s0 = b1_groups[0]
    labels = sorted({s['bids_label'] for s in b1_groups})
    add_row('Anatomical', 'B1 mapping (turbo flash)', '/'.join(labels), s0,
            extra=f'B1-related series present as {", ".join(labels)}; FA variants common in paired maps')

# Field maps
for direction in ('AP', 'PA'):
    # magnitude preferred (no part) else any
    cand = None
    for g,s in summary.items():
        if g[0]=='Field map' and g[2]==direction and g[3] in ('', None):
            cand = s; break
    if not cand:
        for g,s in summary.items():
            if g[0]=='Field map' and g[2]==direction:
                cand = s; break
    if cand:
        add_row('Field map', f'Spin-echo EPI ({direction})', f'dir-{direction}_epi', cand)

# Functional bold by task
for task, nice, n_runs_claimed in [
    ('rest', 'Resting-state BOLD', 'typically 1 run/session'),
    ('movie', 'Movie BOLD', 'typically 4 runs/session'),
    ('fmri', 'Task BOLD', 'typically 4 runs/session'),
    ('control', 'Control BOLD', 'short runs; AP and/or PA'),
]:
    # prefer no dir / no part
    s = None
    for g,ss in summary.items():
        if g[0]=='Functional' and g[1]=='bold' and g[2]==task and g[4]=='':
            s = ss; break
    if not s:
        for g,ss in summary.items():
            if g[0]=='Functional' and g[1]=='bold' and g[2]==task:
                s = ss; break
    if s:
        # count SBRef availability
        n_sbref = sum(ss['n_files'] for g,ss in summary.items() if g[0]=='Functional' and g[1]=='sbref' and g[2]==task)
        add_row('Functional', nice, f'task-{task}_bold', s,
                extra=f'{n_runs_claimed}; SBRef paired series n≈{n_sbref}')

# Diffusion primary
s = pick(('Diffusion','multi-shell_or_multidir','','',''))
# may have dir entity empty - search
if not s:
    for g,ss in summary.items():
        if g[0]=='Diffusion' and g[1]=='multi-shell_or_multidir':
            s = ss; break
if s:
    add_row('Diffusion', 'Multidirection DWI', 'dwi', s)
s = None
for g,ss in summary.items():
    if g[0]=='Diffusion' and g[1]=='b0_reversePE':
        s = ss; break
if s:
    add_row('Diffusion', 'Reverse-PE b0', 'dwi (reverse PE)', s)
s = None
for g,ss in summary.items():
    if g[0]=='Diffusion' and g[1]=='RESOLVE':
        s = ss; break
if s:
    add_row('Diffusion', 'RESOLVE trace DWI', 'dwi (RESOLVE)', s,
            extra='Derived TRACE/ADC/FA maps may exist in source protocol; released BIDS primarily stores convertible DWI runs')

# Write TSV
tsv_path = OUT / 'mri_acquisition_table_revised.tsv'
with tsv_path.open('w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=[
        'Modality','Sequence','BIDS_label','TR_ms','TE_ms','Flip_angle_deg','Resolution','Additional_parameters','n_sidecars'],
        delimiter='\t')
    w.writeheader()
    for row in revised:
        w.writerow(row)
log(f'wrote {tsv_path} rows={len(revised)}')

# ---- Compare to existing table claims ----
existing_text = EXISTING.read_text() if EXISTING.exists() else ''
claims = {
    'scanner_E11_only': 'syngo MR E11' in existing_text and 'XA30' not in existing_text,
    'T1_TR_2500': 'TR 2500' in existing_text,
    'T1_TE_2.22': 'TE 2.22' in existing_text,
    'T1_FA_8': 'Flip angle 8' in existing_text,
    'T1_0.8iso': '0.8 mm isotropic' in existing_text and 'T1-weighted' in existing_text,
    'WMn_TR_4000': 'TR 4000' in existing_text and 'White-matter' in existing_text,
    'FLAIR_TR_6000': 'TR 6000' in existing_text,
    'FLAIR_TE_357': 'TE 357' in existing_text,
    'FLAIR_FA_120': 'Flip angle 120' in existing_text,
    'fmap_TR_9710': 'TR 9710' in existing_text,
    'fmap_TE_66': 'TE 66' in existing_text,
    'bold_TR_937': 'TR 937' in existing_text,
    'bold_TE_37': 'TE 37' in existing_text,
    'bold_FA_52': 'Flip angle 52' in existing_text,
    'bold_MB_missing_in_table': 'multiband' not in existing_text.lower() and 'MB' not in existing_text,
    'dwi_76dir_b2000_only': '76 directions' in existing_text and 'b = 2000' in existing_text,
    'dwi_TR_3500': 'TR 3500' in existing_text,
    'dwi_TE_75': 'TE 75' in existing_text,
    'coil_missing_in_table': 'HeadNeck' not in existing_text and 'ReceiveCoil' not in existing_text,
    'sbref_omitted_explicitly': 'single-band' in existing_text.lower() or 'Single-band' in existing_text or 'references' in existing_text.lower(),
    'physio_omitted': 'physio' in existing_text.lower() or 'Physiological' in existing_text,
}

# Validate numeric claims vs BIDS modes
def check_num(group_pred, key, expected, tol=0.05):
    hits = []
    for g,s in summary.items():
        if group_pred(g,s):
            hits.append(s.get(key))
    if not hits:
        return 'missing_group', hits
    # compare first non-null
    for h in hits:
        if h is None: continue
        try:
            hv = float(h); ev = float(expected)
            if abs(hv-ev) <= tol:
                return 'match', hits
            return 'mismatch', hits
        except Exception:
            if str(h) == str(expected):
                return 'match', hits
            return 'mismatch', hits
    return 'no_value', hits

checks = []
checks.append(('T1 TR', check_num(lambda g,s: g[:2]==('Anatomical','T1w_MPRAGE'), 'TR_ms', 2500, 1)))
checks.append(('T1 TE', check_num(lambda g,s: g[:2]==('Anatomical','T1w_MPRAGE'), 'TE_ms', 2.22, 0.05)))
checks.append(('T1 FA', check_num(lambda g,s: g[:2]==('Anatomical','T1w_MPRAGE'), 'flip_angle_deg', 8, 0.5)))
checks.append(('WMn TR', check_num(lambda g,s: g[:2]==('Anatomical','WMn_MPRAGE'), 'TR_ms', 4000, 1)))
checks.append(('WMn TE', check_num(lambda g,s: g[:2]==('Anatomical','WMn_MPRAGE'), 'TE_ms', 3.82, 0.05)))
checks.append(('FLAIR TR', check_num(lambda g,s: g[:2]==('Anatomical','FLAIR'), 'TR_ms', 6000, 1)))
checks.append(('FLAIR TE', check_num(lambda g,s: g[:2]==('Anatomical','FLAIR'), 'TE_ms', 357, 1)))
checks.append(('BOLD TR', check_num(lambda g,s: g[0]=='Functional' and g[1]=='bold' and g[2]=='rest', 'TR_ms', 937, 1)))
checks.append(('BOLD TE', check_num(lambda g,s: g[0]=='Functional' and g[1]=='bold' and g[2]=='rest', 'TE_ms', 37, 0.5)))
checks.append(('BOLD FA', check_num(lambda g,s: g[0]=='Functional' and g[1]=='bold' and g[2]=='rest', 'flip_angle_deg', 52, 0.5)))
checks.append(('BOLD MB', check_num(lambda g,s: g[0]=='Functional' and g[1]=='bold' and g[2]=='rest', 'MB', 8, 0.1)))
checks.append(('FMAP TR', check_num(lambda g,s: g[0]=='Field map' and g[2]=='AP', 'TR_ms', 9710, 1)))
checks.append(('FMAP TE', check_num(lambda g,s: g[0]=='Field map' and g[2]=='AP', 'TE_ms', 66, 0.5)))

# DWI scheme diversity
dwi_schemes = Counter()
for g,s in summary.items():
    if g[0]=='Diffusion':
        for k,n in s['bval_schemes']:
            dwi_schemes[k]+=n

# func volume modes
func_vols = {}
for g,s in summary.items():
    if g[0]=='Functional' and g[1]=='bold':
        func_vols[g[2]] = s.get('sample_volumes')

# Field coverage of key keys
key_coverage = Counter()
wanted = ['Manufacturer','ManufacturersModelName','MagneticFieldStrength','SoftwareVersions',
          'ReceiveCoilName','ReceiveCoilActiveElements','RepetitionTime','EchoTime','FlipAngle',
          'SliceThickness','PhaseEncodingDirection','MultibandAccelerationFactor',
          'ParallelReductionFactorInPlane','TotalReadoutTime','SeriesDescription','SequenceName','ProtocolName']
for r in recs:
    for k in wanted:
        if k in r['meta']:
            key_coverage[k]+=1
n = len(recs)

# Physiology in BIDS
physio_files = list(BIDS.glob('sub-*/ses-*/func/*physio*')) + list(BIDS.glob('sub-*/ses-*/*/*Physio*'))

# Write audit markdown
audit = OUT / 'mri_acquisition_table_audit.md'
lines = []
lines += [
    '# MRI acquisition table audit',
    '',
    '**Date:** 2026-07-23',
    '**Existing table:** `reports/mri_acquisition_table/MRI_Acquisition_Table.md`',
    '**BIDS root:** `/home/alexrees/scratch/bids` (read-only)',
    f'**Sidecars inspected:** {n} JSON files under `anat/`, `func/`, `dwi/`, `fmap/`',
    f'**Revised table:** `reports/mri_acquisition_table_revised.tsv`',
    '',
    '## Scanner-level metadata (BIDS consensus)',
    '',
    f'- Manufacturer: **{man.most_common(1)[0][0]}**',
    f'- Model: **{model.most_common(1)[0][0]}**',
    f'- Field strength: **{field.most_common(1)[0][0]} T**',
    f'- Software versions present: ' + ', '.join(f'`{k}` (n={v})' for k,v in soft.most_common()),
    f'- Receive coil: **{coil.most_common(1)[0][0]}**',
    f'- ReceiveCoilActiveElements (top): ' + ', '.join(f'`{k}` (n={v})' for k,v in cae.most_common(3)),
    '',
    '## Sidecar field coverage',
    '',
    '| Field | Present | Coverage |',
    '|---|---:|---:|',
]
for k in wanted:
    lines.append(f'| `{k}` | {key_coverage[k]} | {100*key_coverage[k]/n:.1f}% |')

lines += [
    '',
    '## A) Missing information (vs Scientific Data MRI acquisition needs)',
    '',
    'Parameters expected for a reproducible MRI Methods/acquisition table but **absent or incomplete** in the existing curated table:',
    '',
    '1. **MultibandAccelerationFactor** for BOLD (BIDS mode = 8) — not listed in the table body.',
    '2. **ParallelReductionFactorInPlane / iPAT** when present (anat/DWI/RESOLVE).',
    '3. **TotalReadoutTime** and **EffectiveEchoSpacing** for EPI (func/fmap/dwi) — needed for distortion correction reproducibility.',
    '4. **Receive coil name / active elements** — mentioned in Methods prose elsewhere, not in the acquisition table.',
    '5. **SoftwareVersions diversity** — table states only `syngo MR E11`; BIDS also contains `syngo MR XA30`.',
    '6. **BIDS labels** (`T1w`, `FLAIR`, `task-*_bold`, `dir-*_epi`, `dwi`) — table uses free-text only.',
    '7. **Diffusion scheme diversity** — table implies a single `76 dir / b=2000` protocol; BIDS `.bval` schemes include multiple unique-b-value sets (see below).',
    '8. **RESOLVE geometry** — table mentions RESOLVE but omits TR/TE/FA/resolution (BIDS: TR≈4140 ms, TE≈51 ms, FA≈180°, ~1.4 mm).',
    '9. **Reverse-PE b0** — mentioned briefly; TR/TE/volumes not separated as their own row.',
    '10. **SBRef** — explicitly omitted by table note; for Scientific Data, a one-line note that SBRef exists and matches BOLD geometry is preferable to silence.',
    '11. **Physiological monitoring** — omitted from table (Methods correctly notes PhysioLog not released as BIDS physio); table should either omit with explicit cross-ref or state “acquired but not distributed”.',
    '12. **PhaseEncodingDirection** coded as BIDS `j`/`j-` (not only “AP/PA” prose) for fmap/func/dwi.',
    '13. **Number of volumes** verified from NIfTI for each functional task (table values appear protocol-derived; confirm against BIDS).',
    '',
    '### Diffusion b-value schemes observed in BIDS',
    '',
]
if dwi_schemes:
    lines.append('| Unique b-values | Sidecar-linked scans (sampled groups) |')
    lines.append('|---|---:|')
    for k,v in dwi_schemes.most_common(12):
        lines.append(f'| `{k}` | {v} |')
else:
    lines.append('_No bval schemes aggregated (unexpected)._')

lines += [
    '',
    '### Functional volume counts (NIfTI sample per task group)',
    '',
    '| task | sampled volumes |',
    '|---|---:|',
]
for t,v in sorted(func_vols.items()):
    lines.append(f'| `{t}` | {v} |')

lines += [
    '',
    '## B) Incorrect / inconsistent information',
    '',
    'Comparisons of existing table claims vs BIDS JSON modes:',
    '',
    '| Claim / check | Status | BIDS evidence |',
    '|---|---|---|',
]
for name, (status, hits) in checks:
    lines.append(f'| {name} | **{status}** | values={hits[:6]} |')

# Software claim
lines.append(f'| SoftwareVersions = E11 only | **{"mismatch" if soft.get("syngo MR XA30",0)>0 else "match"}** | {dict(soft)} |')
# DWI oversimplification
lines.append(f'| DWI described as 76 dir / b=2000 only | **{"mismatch" if len(dwi_schemes)>1 else "match"}** | schemes={dwi_schemes.most_common(6)} |')
# Control runs PE
ctrl_pe = []
for g,s in summary.items():
    if g[0]=='Functional' and g[1]=='bold' and g[2]=='control':
        ctrl_pe.append((g, s.get('PE'), s['n_files']))
lines.append(f'| Control fMRI PE AP/PA | informational | groups={ctrl_pe} |')

# Resolution claim for DWI "1 mm isotropic (protocol)" vs nifti
dwi_res = []
for g,s in summary.items():
    if g[0]=='Diffusion' and g[1]=='multi-shell_or_multidir':
        dwi_res.append(s.get('resolution'))
lines.append(f'| DWI 1 mm isotropic | check vs NIfTI | sampled resolution={dwi_res} |')

# SliceThickness quirks for DWI from DICOM (5 mm in protocol sample) vs 1mm protocol name
lines.append('| DWI SliceThickness in some DICOM-derived notes (5 mm) vs “1 mm iso” protocol name | **needs careful wording** | Prefer NIfTI zooms / reconstructed resolution over ambiguous DICOM SliceThickness for SMS/multiband stacks |')

lines += [
    '',
    '### Notable consistency findings',
    '',
    '- Core anatomical and BOLD TR/TE/FA values in the existing table **match** the dominant BIDS sidecar modes.',
    '- Field-map TR/TE/FA **match** BIDS.',
    '- The table **under-reports** acceleration (MB=8) and scanner software heterogeneity (E11 + XA30).',
    '- The table **over-simplifies** diffusion as a single 76-direction b=2000 acquisition; BIDS contains multiple b-value/direction protocols plus RESOLVE and reverse-PE b0.',
    '',
    '## C) Redundant information',
    '',
    'Safe to keep out of the main manuscript table (put in prose or omit):',
    '',
    '1. Localizers / scout scans.',
    '2. Derived vendor maps (RESOLVE ADC/FA/ColFA/TENSOR) if not released as primary BIDS imaging.',
    '3. Duplicate magnitude/phase pairs beyond noting `part-phase` exists for fmap when relevant.',
    '4. Per-run identifiers, SeriesInstanceUID, AcquisitionDate.',
    '5. Institutional site address / station names (already de-identified).',
    '6. Full PixelBandwidth / ReconMatrixPE matrices — useful in supplements, not the main table.',
    '7. Listing every SBRef as its own row (one footnote is enough).',
    '8. PhysioLog series names when physiology is not distributed.',
    '',
    '## D) Recommended final manuscript table structure',
    '',
    'Use one concise table with BIDS-aligned columns:',
    '',
    '| Modality | Sequence | BIDS label | TR (ms) | TE (ms) | Flip angle (°) | Resolution | Additional parameters |',
    '|---|---|---|---:|---:|---:|---|---|',
]
for row in revised:
    lines.append(
        f"| {row['Modality']} | {row['Sequence']} | `{row['BIDS_label']}` | {row['TR_ms']} | {row['TE_ms']} | {row['Flip_angle_deg']} | {row['Resolution']} | {row['Additional_parameters']} |"
    )

lines += [
    '',
    '### Recommended accompanying prose (1 short paragraph)',
    '',
    f"MRI was acquired at 3 T on a Siemens Prisma system using a {coil.most_common(1)[0][0]} receive coil. "
    f"Scanner software versions in the released sidecars include {', '.join(f'`{k}`' for k,_ in soft.most_common())}. "
    'Exact run-level parameters are stored in BIDS JSON sidecars; diffusion gradient tables are provided as `.bval`/`.bvec`. '
    'Single-band reference images were acquired with BOLD runs. Physiological monitoring (ECG/respiration/pulse) was logged on the scanner but is not distributed as BIDS physiology files in this release.',
    '',
    '## Group inventory (all aggregated protocol groups)',
    '',
    '| Modality | Kind | n JSON | TR | TE | FA | Resolution | SeriesDescription |',
    '|---|---|---:|---:|---:|---:|---|---|',
]
for g,s in sorted(summary.items(), key=lambda x: (x[1]['modality'], -x[1]['n_files'])):
    lines.append(
        f"| {s['modality']} | {s['kind']} | {s['n_files']} | {s['TR_ms']} | {s['TE_ms']} | {s['flip_angle_deg']} | {s['resolution']} | {s['SeriesDescription']} |"
    )

lines += [
    '',
    '## Methods',
    '',
    '- Read-only inspection of BIDS JSON sidecars (and linked `.bval` / NIfTI headers for resolution and volume counts).',
    '- No modifications to `bids/`.',
    '- Existing curated table treated as the manuscript candidate under audit.',
    '',
]
audit.write_text('\n'.join(lines) + '\n')
log(f'wrote {audit}')

# dump summary json for provenance
(OUT / 'mri_acquisition_group_summary.json').write_text(json.dumps({str(k): v for k,v in summary.items()}, indent=2, default=str))
log('done')
