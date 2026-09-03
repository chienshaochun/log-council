from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .orchestrator import CouncilOrchestrator
from .parser import parse_log_document
from .redaction import redact_value


def build_safe_report(text: str, include_events: bool = True) -> dict[str, Any]:
    """Analyze log text and return a redacted, replay-stable report payload."""
    parsed = parse_log_document(text)
    if not parsed.events:
        raise ValueError("Input contains no non-empty log events")
    report = CouncilOrchestrator().analyze(list(parsed.events))
    payload = report.to_dict(
        include_events=include_events,
        include_runtime_metadata=False,
    )
    payload["parse"] = {
        "stats": {
            **asdict(parsed.stats),
            "coverage": round(parsed.stats.coverage, 6),
        },
        "issues": [asdict(issue) for issue in parsed.issues],
    }
    return redact_value(payload)


def serialize_report(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
