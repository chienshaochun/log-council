from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DatasetError(ValueError):
    """Raised when dataset provenance or a downloaded artifact is invalid."""


@dataclass(frozen=True)
class DatasetFile:
    name: str
    role: str
    url: str
    sha256: str | None
    expected_lines: int | None
    max_bytes: int


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    name: str
    version: str
    source_repository: str
    source_revision: str
    environment: str
    license_notice: str
    citation: tuple[str, ...]
    files: tuple[DatasetFile, ...]


def load_manifest(path: str | Path) -> DatasetManifest:
    manifest_path = Path(path)
    try:
        data: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = tuple(DatasetFile(**item) for item in data.pop("files"))
        citation = tuple(data.pop("citation"))
        return DatasetManifest(**data, citation=citation, files=files)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise DatasetError(f"Invalid dataset manifest {manifest_path}: {exc}") from exc


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_dataset_file(path: str | Path, spec: DatasetFile) -> None:
    artifact = Path(path)
    if not artifact.is_file():
        raise DatasetError(f"Dataset file is missing: {artifact}")
    size = artifact.stat().st_size
    if size > spec.max_bytes:
        raise DatasetError(f"Dataset file exceeds {spec.max_bytes} bytes: {artifact}")
    if spec.sha256:
        actual = sha256_file(artifact)
        if actual != spec.sha256:
            raise DatasetError(
                f"SHA-256 mismatch for {artifact.name}: expected {spec.sha256}, got {actual}"
            )
    if spec.expected_lines is not None:
        with artifact.open("r", encoding="utf-8-sig", errors="replace") as handle:
            actual_lines = sum(1 for _ in handle)
        if actual_lines != spec.expected_lines:
            raise DatasetError(
                f"Line-count mismatch for {artifact.name}: "
                f"expected {spec.expected_lines}, got {actual_lines}"
            )
