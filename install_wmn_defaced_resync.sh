#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Install WMn defaced resync into nifti/
# Safe mode: no overwrite without backup
# ============================================================

PROJECT="$HOME/projects/def-amirs/Shmuel_Mendola"

SOURCE="$PROJECT/WMN_MPRAGE_NIfTI/nifti_defaced_resync_20260731"
TARGET="$PROJECT/WMN_MPRAGE_NIfTI/nifti"

LOG="$SOURCE/INSTALL_FINAL_LOG_$(date +%Y%m%d_%H%M%S).txt"

echo "=== WMn defaced resync installation ===" | tee "$LOG"
echo "Source: $SOURCE" | tee -a "$LOG"
echo "Target: $TARGET" | tee -a "$LOG"


# ------------------------------------------------------------
# Check source
# ------------------------------------------------------------

if [ ! -d "$SOURCE" ]; then
    echo "ERROR: Source folder missing" | tee -a "$LOG"
    exit 1
fi


# ------------------------------------------------------------
# Check target permissions
# ------------------------------------------------------------

echo "" | tee -a "$LOG"
echo "Checking target permissions..." | tee -a "$LOG"

if [ -w "$TARGET" ]; then
    echo "WRITE ACCESS: OK" | tee -a "$LOG"
else
    echo "WRITE ACCESS: FAILED" | tee -a "$LOG"
    echo "" | tee -a "$LOG"

    echo "Current permissions:" | tee -a "$LOG"
    ls -ld "$TARGET" | tee -a "$LOG"

    echo "" | tee -a "$LOG"
    echo "You need one of the following:" | tee -a "$LOG"
    echo "1) Ask owner finch to run this script" | tee -a "$LOG"
    echo "2) Ask finch to grant group write permission:" | tee -a "$LOG"
    echo ""
    echo "chmod -R g+w $TARGET"
    echo ""

    exit 2
fi


# ------------------------------------------------------------
# Create backup directory
# ------------------------------------------------------------

BACKUP="$TARGET/backup_before_wmn_resync_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP"


# ------------------------------------------------------------
# Copy files safely
# ------------------------------------------------------------

echo "" | tee -a "$LOG"
echo "Copying WMn files..." | tee -a "$LOG"

COUNT=0

for SRC in "$SOURCE"/*_ses1_WMn.nii.gz "$SOURCE"/*_ses1_WMn.json \
            "$SOURCE"/*_ses2_WMn.nii.gz "$SOURCE"/*_ses2_WMn.json
do

    if [ ! -f "$SRC" ]; then
        continue
    fi

    FILE=$(basename "$SRC")
    DEST="$TARGET/$FILE"

    if [ -f "$DEST" ]; then
        echo "Existing file detected: $FILE" | tee -a "$LOG"

        cp "$DEST" "$BACKUP/"
        echo "Backup created" | tee -a "$LOG"
    fi

    cp -v "$SRC" "$DEST" | tee -a "$LOG"

    COUNT=$((COUNT+1))

done


# ------------------------------------------------------------
# Validation
# ------------------------------------------------------------

echo "" | tee -a "$LOG"
echo "Validation..." | tee -a "$LOG"

NII=$(find "$TARGET" -maxdepth 1 -name "*_WMn.nii.gz" | wc -l)
JSON=$(find "$TARGET" -maxdepth 1 -name "*_WMn.json" | wc -l)


echo "WMn NIfTI count: $NII" | tee -a "$LOG"
echo "WMn JSON count: $JSON" | tee -a "$LOG"


# ------------------------------------------------------------
# Check missing SUBC025
# ------------------------------------------------------------

echo "" | tee -a "$LOG"
echo "Checking expected missing subject..." | tee -a "$LOG"

if ls "$TARGET"/*SUBC025*WMn* >/dev/null 2>&1; then
    echo "SUBC025 found" | tee -a "$LOG"
else
    echo "WARNING: SUBC025 still missing" | tee -a "$LOG"
fi


echo "" | tee -a "$LOG"
echo "===================================="
echo "INSTALLATION COMPLETE"
echo "Files copied: $COUNT"
echo "Log: $LOG"
echo "===================================="
