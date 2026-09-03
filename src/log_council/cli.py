from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import __version__
from .reporting import build_safe_report, serialize_report


SUPPORTED_SUFFIXES = {".jsonl", ".log", ".txt"}
MAX_INPUT_BYTES = 50 * 1024 * 1024


class CLIError(ValueError):
    """A user-actionable command-line error."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="log-council",
        description="Analyze logs locally with an evidence-bound Agent council.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="analyze a UTF-8 log file or stdin")
    analyze.add_argument("input", help=".log, .txt, or .jsonl path; use - for stdin")
    analyze.add_argument(
        "-o",
        "--output",
        type=Path,
        help="write a redacted deterministic JSON report",
    )
    analyze.add_argument(
        "--json",
        action="store_true",
        help="print JSON instead of the human-readable summary",
    )
    analyze.add_argument(
        "--omit-events",
        "--no-events",
        action="store_true",
        help="exclude redacted source events from JSON to reduce report size",
    )
    analyze.add_argument(
        "--force",
        action="store_true",
        help="replace an existing --output file",
    )
    return parser


def _read_input(source: str, stdin: TextIO) -> str:
    if source == "-":
        text = stdin.read(MAX_INPUT_BYTES + 1)
        if len(text) > MAX_INPUT_BYTES:
            raise CLIError(f"stdin exceeds the {MAX_INPUT_BYTES}-character safety limit")
        return text
    path = Path(source)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise CLIError(f"Unsupported input extension {path.suffix!r}; expected {supported}")
    if not path.is_file():
        raise CLIError(f"Input log does not exist or is not a file: {path}")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise CLIError(f"Input log exceeds the {MAX_INPUT_BYTES}-byte safety limit: {path}")
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CLIError(f"Input log is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise CLIError(f"Could not read input log {path}: {exc}") from exc


def _write_atomic(path: Path, content: str, force: bool) -> None:
    if path.suffix.lower() != ".json":
        raise CLIError(f"JSON output path must use a .json extension: {path}")
    if path.exists() and not force:
        raise CLIError(f"Output already exists; use --force to replace it: {path}")
    if not path.parent.is_dir():
        raise CLIError(f"Output directory does not exist: {path.parent}")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
        ) as temporary:
            temporary.write(content)
            temporary_name = temporary.name
        os.replace(temporary_name, path)
        temporary_name = None
    except OSError as exc:
        raise CLIError(f"Could not write JSON report {path}: {exc}") from exc
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _print_summary(payload: dict[str, Any], stdout: TextIO) -> None:
    summary = payload["summary"]
    parse = payload["parse"]
    stats = parse["stats"]
    hypotheses = payload["hypotheses"]
    actions = payload["recommended_actions"]
    print(f"Run: {summary['consensus']} Agent consensus ({summary['consensus_label']})", file=stdout)
    print(
        f"Input: {stats['event_count']} events, {stats['coverage']:.1%} structured, "
        f"{stats['fallback_count']} fallback",
        file=stdout,
    )
    print(f"Leading hypothesis: {hypotheses[0]['title']}", file=stdout)
    print(f"Confidence: {summary['confidence']:.1%}", file=stdout)
    print(f"Assessment: {summary['root_cause']}", file=stdout)
    print(f"Caveat: {summary['caveat']}", file=stdout)
    print(f"Correlation links: {len(payload['correlations'])}", file=stdout)
    print("Recommended next actions:", file=stdout)
    for index, action in enumerate(actions, start=1):
        print(f"  {index}. {action}", file=stdout)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.force and args.output is None:
            raise CLIError("--force requires --output")
        if (
            args.input != "-"
            and args.output is not None
            and Path(args.input).resolve() == args.output.resolve()
        ):
            raise CLIError("Output path must not be the input log path")
        text = _read_input(args.input, sys.stdin)
        payload = build_safe_report(text, include_events=not args.omit_events)
        json_text = serialize_report(payload)
        if args.output:
            _write_atomic(args.output, json_text, args.force)
        if args.json:
            sys.stdout.write(json_text)
        else:
            _print_summary(payload, sys.stdout)
            if args.output:
                print(f"JSON report: {args.output}", file=sys.stdout)
        return 0
    except BrokenPipeError:
        return 0
    except (CLIError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
