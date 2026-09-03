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
        description="使用受證據約束的多 Agent 團隊分析 log。",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="分析 UTF-8 log 檔案或標準輸入")
    analyze.add_argument("input", help=".log、.txt 或 .jsonl 路徑；使用 - 代表標準輸入")
    analyze.add_argument(
        "-o",
        "--output",
        type=Path,
        help="寫入已遮蔽敏感資訊且可重現的 JSON 報告",
    )
    analyze.add_argument(
        "--json",
        action="store_true",
        help="輸出 JSON，而非方便閱讀的摘要",
    )
    analyze.add_argument(
        "--omit-events",
        "--no-events",
        action="store_true",
        help="從 JSON 排除已遮蔽的來源事件，以縮小報告大小",
    )
    analyze.add_argument(
        "--force",
        action="store_true",
        help="取代既有的 --output 檔案",
    )
    return parser


def _read_input(source: str, stdin: TextIO) -> str:
    if source == "-":
        text = stdin.read(MAX_INPUT_BYTES + 1)
        if len(text) > MAX_INPUT_BYTES:
            raise CLIError(f"標準輸入超過 {MAX_INPUT_BYTES} 字元的安全上限")
        return text
    path = Path(source)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise CLIError(f"不支援的輸入副檔名 {path.suffix!r}；應為 {supported}")
    if not path.is_file():
        raise CLIError(f"輸入 log 不存在或不是檔案：{path}")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise CLIError(f"輸入 log 超過 {MAX_INPUT_BYTES} bytes 的安全上限：{path}")
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CLIError(f"輸入 log 不是有效的 UTF-8：{path}") from exc
    except OSError as exc:
        raise CLIError(f"無法讀取輸入 log {path}：{exc}") from exc


def _write_atomic(path: Path, content: str, force: bool) -> None:
    if path.suffix.lower() != ".json":
        raise CLIError(f"JSON 輸出路徑必須使用 .json 副檔名：{path}")
    if path.exists() and not force:
        raise CLIError(f"輸出檔案已存在；使用 --force 才能取代：{path}")
    if not path.parent.is_dir():
        raise CLIError(f"輸出目錄不存在：{path.parent}")
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
        raise CLIError(f"無法寫入 JSON 報告 {path}：{exc}") from exc
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _print_summary(payload: dict[str, Any], stdout: TextIO) -> None:
    summary = payload["summary"]
    parse = payload["parse"]
    stats = parse["stats"]
    hypotheses = payload["hypotheses"]
    actions = payload["recommended_actions"]
    consensus_labels = {
        "high confidence": "高信心",
        "moderate confidence": "中等信心",
        "no reliable consensus": "尚無可靠共識",
    }
    label = consensus_labels.get(summary["consensus_label"], summary["consensus_label"])
    print(f"分析：{summary['consensus']} 個 Agent 達成共識（{label}）", file=stdout)
    print(
        f"輸入：{stats['event_count']} 筆事件，{stats['coverage']:.1%} 為結構化資料，"
        f"{stats['fallback_count']} 筆以非結構化事件保留",
        file=stdout,
    )
    print(f"主要假設：{hypotheses[0]['title']}", file=stdout)
    print(f"信心：{summary['confidence']:.1%}", file=stdout)
    print(f"評估：{summary['root_cause']}", file=stdout)
    print(f"提醒：{summary['caveat']}", file=stdout)
    print(f"事件關聯數：{len(payload['correlations'])}", file=stdout)
    print("建議的下一步：", file=stdout)
    for index, action in enumerate(actions, start=1):
        print(f"  {index}. {action}", file=stdout)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.force and args.output is None:
            raise CLIError("--force 必須搭配 --output")
        if (
            args.input != "-"
            and args.output is not None
            and Path(args.input).resolve() == args.output.resolve()
        ):
            raise CLIError("輸出路徑不可與輸入 log 路徑相同")
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
                print(f"JSON 報告：{args.output}", file=sys.stdout)
        return 0
    except BrokenPipeError:
        return 0
    except (CLIError, OSError, ValueError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
