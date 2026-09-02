"""Subject reconstruction from recursive DICOM records (read-only)."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path

from neuro_pipeline.discovery.models import (
    DetectionMethod,
    DicomFileRecord,
    DiscoveryMode,
    SubjectRecord,
)

LOGGER = logging.getLogger(__name__)

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
_SUBJECT_NAME_RE = re.compile(
    r"^(sub|subject|patient|participant|subj|pat)[-_]?\w*",
    re.IGNORECASE,
)
_SESSION_NAME_RE = re.compile(
    r"^(ses|session|visit|timepoint|tp|v)[-_]?\w*$",
    re.IGNORECASE,
)
# NIfTI / derived export folders must not become the discovered subject root.
_NIFTI_EXPORT_RE = re.compile(
    r"(^|[_\-.])(nii|nifti|niftis|bids)([_\-.]|$)",
    re.IGNORECASE,
)
# Siemens / scanner study containers under session folders.
_STUDY_CONTAINER_RE = re.compile(
    r"(protocol|_data$|_raw$|(^|[_\-.])(dst|std)([_\-.]|$))",
    re.IGNORECASE,
)
_PENALTY_NAMES = {
    "dicom",
    "dicoms",
    "mr",
    "mri",
    "raw",
    "data",
    "images",
    "image",
    "scans",
    "scan",
    "nifti",
    "bids",
    "derivatives",
    "sourcedata",
    "temp",
    "tmp",
    "series",
    "sequences",
    "protocol",
    "protocols",
    "archive",
    "archives",
    "export",
    "exports",
    "incoming",
    "unsorted",
    "unknown",
}


class SubjectDetector:
    """Group DICOM records into BIDS subjects without modifying DICOM files.

    Folder strategy (automatic / folder_recursive):
      Build a tree partition that works at mixed depths — do not stop at the
      first level of folders under the input root. Prefer subject-like names
      over containers (data/DICOM/raw) and over series/session folders.
    """

    def detect_subjects(
        self,
        dicom_records: list[DicomFileRecord],
        input_root: Path | str,
        *,
        mode: DiscoveryMode | str = DiscoveryMode.AUTOMATIC,
    ) -> tuple[list[SubjectRecord], dict[str, str], str, str]:
        """Return ``(subjects, file_to_bids_subject, method, reason)``."""
        root = Path(input_root)
        mode_e = mode if isinstance(mode, DiscoveryMode) else DiscoveryMode(str(mode))
        if not dicom_records:
            return [], {}, DetectionMethod.SINGLE.value, "No DICOM files detected"

        if mode_e == DiscoveryMode.PATIENT_ID:
            return self._group_by_patient_id(dicom_records, root)

        if mode_e == DiscoveryMode.FOLDER_RECURSIVE:
            return self._partition_by_folder(
                dicom_records,
                root,
                method=DetectionMethod.DEEP_FOLDER.value,
                reason="Deep recursive folder inference",
            )

        # AUTOMATIC — PatientID only when genuinely discriminative and folders
        # do not reveal a multi-subject tree the IDs would collapse.
        if self._patient_ids_discriminative(dicom_records, root):
            return self._group_by_patient_id(dicom_records, root)

        return self._partition_by_folder(
            dicom_records,
            root,
            method=DetectionMethod.FOLDER_BASED.value,
            reason="Folder tree partition (mixed-depth)",
        )

    def _patient_ids_discriminative(
        self, records: list[DicomFileRecord], root: Path
    ) -> bool:
        pids = [(r.patient_id or "").strip() for r in records]
        if any(not p for p in pids):
            return False
        unique = set(pids)
        if len(unique) < 2:
            # Single PatientID: only keep PatientID mode when tree is not multi-subject
            return len(self._candidate_subject_folders(records, root)) < 2
        # Multiple IDs: still prefer folders when the tree clearly has ≥2
        # subject-like partitions and IDs look collided / not 1:1 with folders.
        folders = self._candidate_subject_folders(records, root)
        if len(folders) >= 2:
            # If each PatientID maps cleanly to one folder, PatientID is fine.
            by_pid_folders: dict[str, set[Path]] = defaultdict(set)
            for rec in records:
                pid = (rec.patient_id or "").strip()
                chosen = self._best_subject_folder_for_file(rec, root, folders)
                if chosen is not None:
                    by_pid_folders[pid].add(chosen)
            if any(len(v) > 1 for v in by_pid_folders.values()):
                # Same PatientID spans multiple subject folders → use folders
                return False
        return True

    def _group_by_patient_id(
        self,
        records: list[DicomFileRecord],
        root: Path,
    ) -> tuple[list[SubjectRecord], dict[str, str], str, str]:
        by_pid: dict[str, list[DicomFileRecord]] = defaultdict(list)
        for rec in records:
            pid = (rec.patient_id or "").strip() or "unknown"
            by_pid[pid].append(rec)

        subjects: list[SubjectRecord] = []
        mapping: dict[str, str] = {}
        used_labels: set[str] = set()
        refine_groups: dict[Path, list[DicomFileRecord]] = defaultdict(list)

        for pid, items in sorted(by_pid.items(), key=lambda kv: kv[0]):
            label = _unique_label(_sanitize(pid), used_labels)
            used_labels.add(label)
            series_uids = sorted({r.series_instance_uid for r in items if r.series_instance_uid})
            study_uids = sorted({r.study_instance_uid for r in items if r.study_instance_uid})
            folder = ""
            folder_path = ""
            tops = _top_level_folders(items, root)
            if len(tops) == 1:
                folder = next(iter(tops))
                folder_path = str((root / folder).resolve())
            else:
                # Prefer the shared subject folder if all files share one
                folders = self._candidate_subject_folders(items, root)
                if len(folders) == 1:
                    only = next(iter(folders))
                    folder = only.name
                    folder_path = str(only)
            subjects.append(
                SubjectRecord(
                    bids_subject=label,
                    source_folder=folder,
                    source_folder_path=folder_path,
                    dicom_patient_id="" if pid == "unknown" else pid,
                    detection_method=DetectionMethod.PATIENT_ID.value,
                    reason="Unique PatientID grouping",
                    dicom_files=len(items),
                    series_uids=series_uids,
                    study_uids=study_uids,
                    score=100.0,
                )
            )
            for rec in items:
                mapping[str(rec.filepath)] = label
            if folder_path:
                refine_groups[Path(folder_path)].extend(items)

        if refine_groups:
            self._refine_source_paths(subjects, refine_groups, _stable_path(root))

        method = DetectionMethod.PATIENT_ID.value
        reason = "Unique PatientID values"
        if len(subjects) == 1:
            method = DetectionMethod.SINGLE.value
            reason = "Single subject (PatientID)"
            subjects[0].detection_method = method
            subjects[0].reason = reason
        return subjects, mapping, method, reason

    def _partition_by_folder(
        self,
        records: list[DicomFileRecord],
        root: Path,
        *,
        method: str,
        reason: str,
    ) -> tuple[list[SubjectRecord], dict[str, str], str, str]:
        """Partition DICOM files into subject folders at mixed depths."""
        root_r = root.resolve()
        selected = self._candidate_subject_folders(records, root_r)
        if not selected:
            # Entire root is one subject
            return self._subjects_from_groups(
                {root_r: list(records)},
                root_r,
                method=DetectionMethod.SINGLE.value,
                reason="Single subject dataset",
            )

        groups: dict[Path, list[DicomFileRecord]] = defaultdict(list)
        for rec in records:
            folder = self._best_subject_folder_for_file(rec, root_r, selected)
            if folder is None:
                folder = root_r
            groups[folder].append(rec)

        subjects, mapping, out_method, out_reason = self._subjects_from_groups(
            groups, root_r, method=method, reason=reason
        )
        # Prefer *_DATA / *PROTOCOL* study roots for conversion input paths.
        self._refine_source_paths(subjects, groups, root_r)
        return subjects, mapping, out_method, out_reason

    def _candidate_subject_folders(
        self, records: list[DicomFileRecord], root: Path
    ) -> set[Path]:
        """Select a non-nested set of subject folders covering all DICOM files.

        Works when some subjects sit directly under root and others are nested
        under extra container folders.
        """
        root_r = Path(root).resolve()
        # folder → files whose parent chain includes that folder
        files_under: dict[Path, list[DicomFileRecord]] = defaultdict(list)
        ancestors_per_file: list[list[Path]] = []

        for rec in records:
            chain = self._ancestor_folders(rec, root_r)
            ancestors_per_file.append(chain)
            for folder in chain:
                files_under[folder].append(rec)

        if not files_under:
            return set()

        scored: list[tuple[float, Path]] = []
        for folder, items in files_under.items():
            if folder == root_r:
                continue
            scored.append((self._score_folder(folder, root_r, items), folder))
        scored.sort(key=lambda t: (-t[0], str(t[1])))

        selected: list[Path] = []
        covered_files: set[str] = set()

        def _is_nested(a: Path, b: Path) -> bool:
            try:
                a.relative_to(b)
                return a != b
            except ValueError:
                return False

        for score, folder in scored:
            if score < 0.5:
                # Weak container / series names — skip as primary picks
                # unless nothing else covers those files later
                continue
            if any(folder == s or _is_nested(folder, s) or _is_nested(s, folder) for s in selected):
                continue
            selected.append(folder)
            for rec in files_under[folder]:
                covered_files.add(str(rec.filepath))

        # Cover remaining files with the best remaining ancestor (may be weak)
        for rec, chain in zip(records, ancestors_per_file):
            key = str(rec.filepath)
            if key in covered_files:
                continue
            best: Path | None = None
            best_score = -10**9
            for folder in chain:
                if folder == root_r:
                    continue
                if any(_is_nested(folder, s) or folder == s for s in selected):
                    # already under a selected subject
                    best = None
                    best_score = 10**9
                    break
                if any(_is_nested(s, folder) for s in selected):
                    continue
                sc = self._score_folder(folder, root_r, files_under[folder])
                if sc > best_score:
                    best_score = sc
                    best = folder
            if best is not None and best_score < 10**9:
                selected.append(best)
                for r in files_under[best]:
                    covered_files.add(str(r.filepath))

        # Drop parent containers if all their DICOM sit under stronger children
        selected = self._drop_redundant_parents(selected, files_under, root_r)
        return set(selected)

    def _drop_redundant_parents(
        self,
        selected: list[Path],
        files_under: dict[Path, list[DicomFileRecord]],
        root: Path,
    ) -> list[Path]:
        """If a selected folder only wraps better subject children, drop it."""
        selected_set = set(selected)
        to_drop: set[Path] = set()
        for folder in selected:
            children = [
                s
                for s in selected
                if s != folder and _is_relative_to(s, folder)
            ]
            if not children:
                continue
            parent_files = {str(r.filepath) for r in files_under.get(folder, [])}
            child_files: set[str] = set()
            for child in children:
                child_files.update(str(r.filepath) for r in files_under.get(child, []))
            # Parent adds no exclusive DICOM → redundant container
            if parent_files and parent_files <= child_files:
                to_drop.add(folder)
                continue
            # Parent looks like a penalty / study container and children score higher
            try:
                name = folder.resolve().relative_to(root.resolve()).parts[-1]
            except ValueError:
                name = folder.name
            parent_score = self._score_folder_name(
                name, depth=max(0, len(folder.parts) - len(root.parts) - 1), under_root=False
            )
            if name.lower() in _PENALTY_NAMES or parent_score < 2:
                if parent_files <= child_files or len(child_files) >= len(parent_files) * 0.9:
                    to_drop.add(folder)
        return [s for s in selected if s not in to_drop]

    def _best_subject_folder_for_file(
        self,
        rec: DicomFileRecord,
        root: Path,
        selected: set[Path],
    ) -> Path | None:
        if not selected:
            return None
        chain = self._ancestor_folders(rec, root)
        # Prefer deepest selected ancestor (most specific subject folder)
        for folder in reversed(chain):
            if folder in selected:
                return folder
        return None

    def _refine_source_paths(
        self,
        subjects: list[SubjectRecord],
        groups: dict[Path, list[DicomFileRecord]],
        root: Path,
    ) -> None:
        """Point ``source_folder_path`` at a study/protocol container when unique.

        Session folders like ``SUBT01_Session02_*`` often wrap::

            …_DATA / SiemensUID / DR_*_PROTOCOL_* / series…

        Prefer that PROTOCOL (or *_DATA) leaf so conversion scans the real
        DICOM study, not a sibling ``*_NII`` export tree.
        """
        by_path = {
            _stable_path(Path(s.source_folder_path)): s
            for s in subjects
            if s.source_folder_path
        }
        for folder, items in groups.items():
            subject = by_path.get(_stable_path(folder))
            if subject is None:
                continue
            refined = self._best_study_root(folder, items, root)
            if refined is None or _stable_path(refined) == _stable_path(folder):
                continue
            subject.source_folder_path = str(refined)
            subject.source_folder = self._display_name(refined, root)

    def _best_study_root(
        self,
        subject_folder: Path,
        items: list[DicomFileRecord],
        root: Path,
    ) -> Path | None:
        """Deepest common study-like folder under ``subject_folder`` covering all files."""
        if not items:
            return subject_folder

        chains: list[list[Path]] = []
        for rec in items:
            chain = self._ancestor_folders(rec, root)
            # Keep only ancestors under/equal subject folder
            under = [f for f in chain if f == subject_folder or _is_relative_to(f, subject_folder)]
            if under:
                chains.append(under)
        if not chains:
            return subject_folder

        common = set(chains[0])
        for chain in chains[1:]:
            common &= set(chain)
        if not common:
            return subject_folder

        # Prefer PROTOCOL / *_DATA names; never pick NIfTI exports.
        study_like = [
            f
            for f in common
            if _STUDY_CONTAINER_RE.search(f.name or "")
            and not _is_nifti_export_name(f.name)
        ]
        if study_like:
            return max(study_like, key=lambda p: len(p.parts))

        # Otherwise deepest common non-nifti ancestor under the subject
        usable = [f for f in common if not _is_nifti_export_name(f.name)]
        if usable:
            return max(usable, key=lambda p: len(p.parts))
        return subject_folder

    def _ancestor_folders(self, rec: DicomFileRecord, root: Path) -> list[Path]:
        """Ancestors from root child down to file parent (root excluded)."""
        root_r = _stable_path(root)
        file_path = _stable_path(rec.filepath)
        try:
            rel = file_path.relative_to(root_r)
        except ValueError:
            parent = _stable_path(rec.parent_folder)
            return [parent] if parent != root_r else []
        parts = rel.parts[:-1]
        out: list[Path] = []
        for i in range(len(parts)):
            out.append(root_r.joinpath(*parts[: i + 1]))
        return out

    def _subjects_from_groups(
        self,
        groups: dict[Path, list[DicomFileRecord]],
        root: Path,
        *,
        method: str,
        reason: str,
    ) -> tuple[list[SubjectRecord], dict[str, str], str, str]:
        subjects: list[SubjectRecord] = []
        mapping: dict[str, str] = {}
        used_labels: set[str] = set()
        root_r = root.resolve()

        for folder_path, items in sorted(groups.items(), key=lambda kv: str(kv[0])):
            display = self._display_name(folder_path, root_r)
            label = _unique_label(_sanitize(display), used_labels)
            used_labels.add(label)
            pids = sorted(
                {(r.patient_id or "").strip() for r in items if (r.patient_id or "").strip()}
            )
            dicom_pid = pids[0] if len(pids) == 1 else ""
            if len(pids) > 1:
                dicom_pid = ",".join(pids[:3]) + ("…" if len(pids) > 3 else "")

            series_uids = sorted({r.series_instance_uid for r in items if r.series_instance_uid})
            study_uids = sorted({r.study_instance_uid for r in items if r.study_instance_uid})
            score = self._score_folder(folder_path, root_r, items)

            subjects.append(
                SubjectRecord(
                    bids_subject=label,
                    source_folder=display,
                    source_folder_path=str(folder_path),
                    dicom_patient_id=dicom_pid,
                    detection_method=method,
                    reason=reason,
                    dicom_files=len(items),
                    series_uids=series_uids,
                    study_uids=study_uids,
                    score=score,
                )
            )
            for rec in items:
                mapping[str(rec.filepath)] = label

        out_method = method
        out_reason = reason
        if len(subjects) == 1:
            subjects[0].detection_method = DetectionMethod.SINGLE.value
            subjects[0].reason = "Single subject dataset"
            out_method = DetectionMethod.SINGLE.value
            out_reason = subjects[0].reason
        elif method == DetectionMethod.FOLDER_BASED.value and any(
            s.source_folder_path and Path(s.source_folder_path).parent != root_r
            for s in subjects
        ):
            # Mixed depths present
            out_reason = "Folder tree partition (mixed-depth)"

        return subjects, mapping, out_method, out_reason

    def _display_name(self, folder_path: Path, root: Path) -> str:
        try:
            rel = folder_path.resolve().relative_to(root.resolve())
            if not rel.parts:
                return root.name
            # Prefer deepest non-penalty / non-session name
            for part in reversed(rel.parts):
                lower = part.lower()
                if lower in _PENALTY_NAMES or _SESSION_NAME_RE.match(part):
                    continue
                return part
            return rel.parts[0]
        except ValueError:
            return folder_path.name

    def _score_folder(self, folder: Path, root: Path, items: list[DicomFileRecord]) -> float:
        try:
            rel = folder.resolve().relative_to(root.resolve())
            depth = max(0, len(rel.parts) - 1)
            under_root = len(rel.parts) == 1
            name = rel.parts[-1] if rel.parts else folder.name
        except ValueError:
            depth = 0
            under_root = False
            name = folder.name

        score = self._score_folder_name(name, depth=depth, under_root=under_root)
        series_uids = {r.series_instance_uid for r in items if r.series_instance_uid}
        study_uids = {r.study_instance_uid for r in items if r.study_instance_uid}
        if len(series_uids) > 1:
            score += 3
        if study_uids:
            score += 2
        # Many files under a subject-like folder is a positive signal
        score += min(len(items), 20) * 0.05
        return float(score)

    @staticmethod
    def _score_folder_name(name: str, *, depth: int, under_root: bool) -> float:
        score = 0.0
        lower = (name or "").lower()
        if _is_nifti_export_name(name):
            # Never prefer already-converted NIfTI export trees as subject roots
            score -= 12
        if _SUBJECT_NAME_RE.match(name or ""):
            score += 8
        if _SESSION_NAME_RE.match(name or ""):
            score -= 4
        if under_root:
            score += 2
        if lower in _PENALTY_NAMES:
            score -= 6
        if _STUDY_CONTAINER_RE.search(name or ""):
            # Siemens PROTOCOL / *_DATA study folders are good conversion roots
            score += 4
        if lower not in _PENALTY_NAMES and not _SESSION_NAME_RE.match(name or "") and len(name) >= 2:
            score += 1.5
        # Mild preference for shallower subject folders, but do not crush deep subjects
        score -= depth * 0.05
        return score


def _is_nifti_export_name(name: str) -> bool:
    lower = (name or "").lower()
    if lower in {"nifti", "niftis", "nii", "bids"}:
        return True
    if lower.endswith("_nii") or lower.endswith("_nifti") or lower.endswith("-nii"):
        return True
    return bool(_NIFTI_EXPORT_RE.search(name or ""))


def _stable_path(path: Path | str) -> Path:
    """Resolve when possible; fall back to absolute without failing long paths."""
    p = Path(path)
    try:
        return p.resolve()
    except OSError:
        try:
            return p.absolute()
        except OSError:
            return p


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return path.resolve() != parent.resolve()
    except ValueError:
        return False


def _top_level_folders(records: list[DicomFileRecord], root: Path) -> set[str]:
    root_r = Path(root).resolve()
    out: set[str] = set()
    for rec in records:
        try:
            rel = rec.filepath.resolve().relative_to(root_r)
        except ValueError:
            continue
        if rel.parts:
            name = rel.parts[0]
            if name.lower() not in _PENALTY_NAMES:
                out.add(name)
    return out


def _sanitize(value: str) -> str:
    cleaned = _NON_ALNUM.sub("", str(value or "").strip())
    return cleaned or "unknown"


def _unique_label(base: str, used: set[str]) -> str:
    label = base or "unknown"
    if label not in used:
        return label
    n = 2
    while f"{base}{n}" in used:
        n += 1
    return f"{base}{n}"
