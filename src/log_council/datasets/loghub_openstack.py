from __future__ import annotations

import re
from pathlib import Path

from ..models import LogEvent, ParsedLog, ParseIssue, ParseStats
from ..parser import parse_timestamp


OPENSTACK_LOG = re.compile(
    r"^(?P<log_file>\S+)\s+"
    r"(?P<date>\d{4}-\d{2}-\d{2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+"
    r"(?P<process_id>\d+)\s+"
    r"(?P<level>TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)\s+"
    r"(?P<component>\S+)\s+"
    r"\[(?P<context>[^\]]*)\]\s*"
    r"(?P<message>.*)$",
    re.IGNORECASE,
)
REQUEST_ID = re.compile(r"\b(req-[0-9a-f-]+)\b", re.IGNORECASE)


def _service_name(log_file: str) -> str:
    return log_file.split(".log", 1)[0]


def parse_openstack_text(text: str) -> ParsedLog:
    """Parse the raw Loghub OpenStack layout into LogCouncil events."""
    events: list[LogEvent] = []
    issues: list[ParseIssue] = []
    structured_count = 0
    fallback_count = 0
    invalid_timestamp_count = 0
    input_lines = 0

    for line_number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        input_lines += 1
        event_id = f"OS-{input_lines:06d}"
        line = raw.rstrip("\r\n")
        match = OPENSTACK_LOG.match(line)
        if match is None:
            fallback_count += 1
            events.append(LogEvent(
                id=event_id,
                timestamp=None,
                level="INFO",
                service="unknown",
                message=line.strip(),
                attributes={"dataset": "loghub-openstack", "line_number": line_number},
                raw=line,
            ))
            issues.append(ParseIssue(
                line_number=line_number,
                code="unrecognized_openstack_format",
                detail="Line was preserved as an unstructured INFO event.",
                raw=line,
            ))
            continue

        values = match.groupdict()
        timestamp = parse_timestamp(f"{values['date']} {values['time']}")
        if timestamp is None:
            invalid_timestamp_count += 1
            issues.append(ParseIssue(
                line_number=line_number,
                code="invalid_timestamp",
                detail="Could not parse the OpenStack timestamp.",
                raw=line,
            ))
        request = REQUEST_ID.search(values["context"])
        events.append(LogEvent(
            id=event_id,
            timestamp=timestamp,
            level=values["level"].upper(),
            service=_service_name(values["log_file"]),
            message=values["message"],
            trace_id=request.group(1) if request else None,
            attributes={
                "dataset": "loghub-openstack",
                "line_number": line_number,
                "log_file": values["log_file"],
                "process_id": int(values["process_id"]),
                "component": values["component"],
                "context": values["context"],
            },
            raw=line,
        ))
        structured_count += 1

    return ParsedLog(
        events=tuple(events),
        issues=tuple(issues),
        stats=ParseStats(
            input_lines=input_lines,
            event_count=len(events),
            structured_count=structured_count,
            fallback_count=fallback_count,
            invalid_timestamp_count=invalid_timestamp_count,
            duplicate_id_count=0,
        ),
    )


def parse_openstack_file(path: str | Path) -> ParsedLog:
    return parse_openstack_text(Path(path).read_text(encoding="utf-8-sig"))
