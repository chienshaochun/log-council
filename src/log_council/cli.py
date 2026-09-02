from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .orchestrator import CouncilOrchestrator
from .parser import parse_log_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="log-council", description="Run a multi-agent log investigation.")
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze", help="Analyze a .log or .jsonl file")
    analyze.add_argument("path", type=Path)
    analyze.add_argument("--output", "-o", type=Path, help="Write the full JSON report")
    analyze.add_argument("--no-events", action="store_true", help="Exclude raw events from JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "analyze":
        return 2
    try:
        events = parse_log_file(args.path)
        report = CouncilOrchestrator().analyze(events)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}")
        return 1
    payload = json.dumps(report.to_dict(include_events=not args.no_events), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
