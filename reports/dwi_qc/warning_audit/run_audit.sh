#!/bin/bash
set -euo pipefail
module purge 2>/dev/null || true
module load StdEnv/2023 python/3.11.5 scipy-stack/2025a
export PATH="/cvmfs/soft.computecanada.ca/easybuild/software/2023/x86-64-v3/Compiler/gcc12/mrtrix/3.0.8/bin:$PATH"
export PATH="/cvmfs/soft.computecanada.ca/easybuild/software/2023/x86-64-v3/Core/fsl/6.0.7.20/share/fsl/bin:$PATH"
export FSLDIR=/cvmfs/soft.computecanada.ca/easybuild/software/2023/x86-64-v3/Core/fsl/6.0.7.20
export FSLOUTPUTTYPE=NIFTI_GZ
# Prefer module python
export PATH="$(dirname $(which python3)):$PATH"
cd /home/alexrees/scratch
python3 -c 'import matplotlib,nibabel,numpy; print("imports_ok")'
which bet dwi2mask
python3 -u code/audit_dwi_qc_warnings.py \
  --qc-dir /home/alexrees/scratch/reports/dwi_qc \
  --workers 2
