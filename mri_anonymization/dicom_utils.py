"""Shared DICOM helper utilities."""

from __future__ import annotations

from pydicom.dataset import Dataset


def get_tag_string(dataset: Dataset, tag: tuple[int, int]) -> str:
    """Safely read a tag as string."""
    element = dataset.get(tag)
    if element is None or element.value is None:
        return ""
    return str(element.value).strip()


def iter_all_elements(
    dataset: Dataset,
    *,
    include_file_meta: bool = False,
) -> list:
    """Flatten dataset elements including nested sequences."""
    elements: list = []

    def _walk(dset: Dataset) -> None:
        for element in dset:
            elements.append(element)
            if element.VR == "SQ" and element.value:
                for item in element.value:
                    _walk(item)

    _walk(dataset)
    if include_file_meta and hasattr(dataset, "file_meta") and dataset.file_meta:
        for element in dataset.file_meta:
            elements.append(element)
    return elements


def collect_uid_values(dataset: Dataset) -> set[str]:
    """Collect all UID values from dataset and file meta."""
    uids: set[str] = set()
    for element in iter_all_elements(dataset, include_file_meta=True):
        if element.VR == "UI" and element.value:
            values = element.value if isinstance(element.value, (list, tuple)) else [element.value]
            for value in values:
                text = str(value).strip()
                if text:
                    uids.add(text)
    return uids


def collect_date_values(dataset: Dataset) -> dict[tuple[int, int], str]:
    """Collect configured date tag values before anonymization."""
    from mri_anonymization.constants import DATE_DICOM_TAGS, DATETIME_DICOM_TAGS

    dates: dict[tuple[int, int], str] = {}
    for tag in (*DATE_DICOM_TAGS, *DATETIME_DICOM_TAGS):
        value = get_tag_string(dataset, tag)
        if value:
            dates[tag] = value
    return dates
