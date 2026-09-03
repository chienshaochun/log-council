from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import LogEvent, ParsedLog, ParseIssue, ParseStats


TEXT_LOG = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ][^ ]+)\s+"
    r"(?P<level>TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)\s+"
    r"(?:\[(?P<service>[^\]]+)\]\s+)?(?P<message>.*)$",
    re.IGNORECASE,
)
TRACE_PATTERN = re.compile(r"(?:trace[_-]?id|trace)=['\"]?([\w.-]+)", re.IGNORECASE)


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def _json_event(data: dict[str, Any], raw: str, index: int) -> LogEvent:
    known = {
        "id", "event_id", "ts", "timestamp", "time", "level", "severity",
        "service", "app", "component", "logger", "message", "msg", "trace_id", "trace",
    }
    event_id = str(data.get("id") or data.get("event_id") or f"EVT-{index:03d}")
    level = str(data.get("level") or data.get("severity") or "INFO").upper()
    service = str(
        data.get("service") or data.get("app") or data.get("component")
        or data.get("logger") or "unknown"
    )
    message = str(data.get("message") or data.get("msg") or raw)
    trace_id = data.get("trace_id") or data.get("trace")
    return LogEvent(
        id=event_id,
        timestamp=parse_timestamp(data.get("ts") or data.get("timestamp") or data.get("time")),
        level=level,
        service=service,
        message=message,
        trace_id=str(trace_id) if trace_id is not None else None,
        attributes={key: value for key, value in data.items() if key not in known},
        raw=raw,
    )


def _text_event(line: str, index: int) -> LogEvent:
    match = TEXT_LOG.match(line)
    if not match:
        return LogEvent(
            id=f"EVT-{index:03d}", timestamp=None, level="INFO", service="unknown",
            message=line, raw=line,
        )
    values = match.groupdict()
    trace_match = TRACE_PATTERN.search(values["message"])
    return LogEvent(
        id=f"EVT-{index:03d}",
        timestamp=parse_timestamp(values["ts"]),
        level=values["level"].upper(),
        service=values.get("service") or "unknown",
        message=values["message"],
        trace_id=trace_match.group(1) if trace_match else None,
        raw=line,
    )


def parse_log_text(text: str) -> list[LogEvent]:
    """Parse JSONL or common timestamp/level/service text logs.

    Unrecognized non-empty lines are intentionally kept as INFO events so an
    investigation never silently drops evidence.
    """
    return list(parse_log_document(text).events)


def parse_log_document(text: str) -> ParsedLog:
    """Parse a log and return events plus an auditable data-quality summary."""
    events: list[LogEvent] = []
    issues: list[ParseIssue] = []
    seen_ids: Counter[str] = Counter()
    structured_count = 0
    fallback_count = 0
    invalid_timestamp_count = 0
    duplicate_id_count = 0
    input_lines = 0

    for line_number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        input_lines += 1
        event_index = len(events) + 1
        line = raw.strip()
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            data = None

        if isinstance(data, dict):
            event = _json_event(data, line, event_index)
            structured_count += 1
            timestamp_value = data.get("ts") or data.get("timestamp") or data.get("time")
            if timestamp_value and event.timestamp is None:
                invalid_timestamp_count += 1
                issues.append(ParseIssue(
                    line_number, "invalid_timestamp",
                    f"無法解析時間戳記：{timestamp_value}", line,
                ))
        else:
            event = _text_event(line, event_index)
            if TEXT_LOG.match(line):
                structured_count += 1
                if event.timestamp is None:
                    invalid_timestamp_count += 1
                    issues.append(ParseIssue(
                        line_number, "invalid_timestamp", "無法解析文字 log 的時間戳記", line,
                    ))
            else:
                fallback_count += 1
                code = "unsupported_json_type" if data is not None else "unrecognized_format"
                issues.append(ParseIssue(
                    line_number, code,
                    "此行已保留為非結構化 INFO 事件。", line,
                ))

        seen_ids[event.id] += 1
        if seen_ids[event.id] > 1:
            duplicate_id_count += 1
            original_id = event.id
            event = replace(event, id=f"{original_id}#{seen_ids[original_id]}")
            issues.append(ParseIssue(
                line_number, "duplicate_event_id",
                f"重複的事件 ID「{original_id}」已重新命名為「{event.id}」。", line,
            ))
        events.append(event)

    stats = ParseStats(
        input_lines=input_lines,
        event_count=len(events),
        structured_count=structured_count,
        fallback_count=fallback_count,
        invalid_timestamp_count=invalid_timestamp_count,
        duplicate_id_count=duplicate_id_count,
    )
    return ParsedLog(tuple(events), tuple(issues), stats)


def parse_log_file(path: str | Path) -> list[LogEvent]:
    return parse_log_text(Path(path).read_text(encoding="utf-8-sig"))
