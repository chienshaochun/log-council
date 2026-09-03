from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import LogEvent
from .contracts import DatasetError


LOG_COLUMNS = {"timestamp", "container_name", "message"}
CASE_COLUMNS = {
    "case",
    "dataset",
    "system_name",
    "root_cause_service",
    "fault",
    "fault_description",
    "repetition",
    "inject_time",
    "time_start",
    "time_end",
    "n_logs",
    "has_logs",
}


@dataclass(frozen=True)
class RCAEvalAnalysisInput:
    """The benchmark information that an analysis workflow is allowed to see."""

    events: tuple[LogEvent, ...]
    incident_anchor: datetime


@dataclass(frozen=True)
class RCAEvalGroundTruth:
    """Evaluation-only labels. Never add these fields to LogEvent attributes."""

    case_id: str
    root_cause_service: str
    fault: str
    fault_description: str
    repetition: int


@dataclass(frozen=True)
class RCAEvalCase:
    dataset: str
    system: str
    time_start: datetime
    time_end: datetime
    analysis: RCAEvalAnalysisInput
    ground_truth: RCAEvalGroundTruth


def _parquet_module() -> Any:
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:  # pragma: no cover - depends on installation extras
        raise DatasetError(
            "RCAEval parquet support requires: pip install -e '.[datasets]'"
        ) from exc
    return parquet


def _read_table(path: str | Path, required: set[str], role: str) -> Any:
    artifact = Path(path)
    if not artifact.is_file():
        raise DatasetError(f"RCAEval {role} file is missing: {artifact}")
    parquet = _parquet_module()
    try:
        table = parquet.read_table(artifact)
    except Exception as exc:
        raise DatasetError(f"Could not read RCAEval {role} parquet: {exc}") from exc
    missing = required.difference(table.column_names)
    if missing:
        raise DatasetError(
            f"RCAEval {role} schema is missing columns: {', '.join(sorted(missing))}"
        )
    return table


def _unix_datetime(value: Any, field: str) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (OSError, OverflowError, TypeError, ValueError) as exc:
        raise DatasetError(f"Invalid RCAEval {field}: {value!r}") from exc


def _load_inject_time(path: str | Path) -> int:
    artifact = Path(path)
    try:
        return int(artifact.read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as exc:
        raise DatasetError(f"Invalid RCAEval injection-time file {artifact}: {exc}") from exc


def load_rcaeval_case(
    logs_path: str | Path,
    cases_path: str | Path,
    inject_time_path: str | Path,
    case_id: str,
) -> RCAEvalCase:
    """Load one RCAEval case while keeping evaluation labels out of agent input."""
    logs_table = _read_table(logs_path, LOG_COLUMNS, "logs")
    cases_table = _read_table(cases_path, CASE_COLUMNS, "case index")

    matching = [row for row in cases_table.to_pylist() if row["case"] == case_id]
    if len(matching) != 1:
        raise DatasetError(
            f"Expected exactly one RCAEval case named {case_id!r}, found {len(matching)}"
        )
    metadata = matching[0]
    if not metadata["has_logs"]:
        raise DatasetError(f"RCAEval case {case_id!r} is marked as having no logs")

    inject_time = _load_inject_time(inject_time_path)
    if inject_time != int(metadata["inject_time"]):
        raise DatasetError(
            "RCAEval injection time does not match the ground-truth index: "
            f"{inject_time} != {metadata['inject_time']}"
        )
    if logs_table.num_rows != int(metadata["n_logs"]):
        raise DatasetError(
            "RCAEval log count does not match the ground-truth index: "
            f"{logs_table.num_rows} != {metadata['n_logs']}"
        )

    events: list[LogEvent] = []
    for row_number, row in enumerate(logs_table.to_pylist(), start=1):
        try:
            timestamp_value = int(row["timestamp"])
        except (TypeError, ValueError) as exc:
            raise DatasetError(
                f"Invalid timestamp at RCAEval row {row_number}: {row['timestamp']!r}"
            ) from exc
        service = row["container_name"]
        message = row["message"]
        if not isinstance(service, str) or not service:
            raise DatasetError(f"Invalid container_name at RCAEval row {row_number}")
        if not isinstance(message, str):
            raise DatasetError(f"Invalid message at RCAEval row {row_number}")
        offset = timestamp_value - inject_time
        events.append(LogEvent(
            id=f"RCA-{row_number:06d}",
            timestamp=_unix_datetime(timestamp_value, f"timestamp at row {row_number}"),
            level="UNKNOWN",
            service=service,
            message=message,
            attributes={
                "dataset": "rcaeval-re3ob",
                "row_number": row_number,
                "unix_timestamp": timestamp_value,
                "seconds_from_injection": offset,
                "phase": "pre-injection" if offset < 0 else "post-injection",
            },
            raw=message,
        ))

    return RCAEvalCase(
        dataset=str(metadata["dataset"]),
        system=str(metadata["system_name"]),
        time_start=_unix_datetime(metadata["time_start"], "time_start"),
        time_end=_unix_datetime(metadata["time_end"], "time_end"),
        analysis=RCAEvalAnalysisInput(
            events=tuple(events),
            incident_anchor=_unix_datetime(inject_time, "inject_time"),
        ),
        ground_truth=RCAEvalGroundTruth(
            case_id=case_id,
            root_cause_service=str(metadata["root_cause_service"]),
            fault=str(metadata["fault"]),
            fault_description=str(metadata["fault_description"]),
            repetition=int(metadata["repetition"]),
        ),
    )
