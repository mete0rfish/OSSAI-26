from pathlib import Path

import pytest

from dart_parser_workflow.config import ExecutionSettings
from dart_parser_workflow.execution import ParserExecutionError, execute_parser


def _write_parser(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "parser.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_parser_runs_in_subprocess(tmp_path: Path) -> None:
    path = _write_parser(tmp_path, "def extract(html: str) -> str:\n    return html.strip()\n")
    assert execute_parser(path, " value ", ExecutionSettings()) == "value"


def test_non_string_result_is_rejected(tmp_path: Path) -> None:
    path = _write_parser(tmp_path, "def extract(html: str) -> str:\n    return 123\n")
    with pytest.raises(ParserExecutionError, match="str이어야"):
        execute_parser(path, "value", ExecutionSettings())


def test_timeout_is_enforced(tmp_path: Path) -> None:
    path = _write_parser(
        tmp_path,
        "def extract(html: str) -> str:\n    while True:\n        pass\n",
    )
    settings = ExecutionSettings(timeout_seconds=0.2)
    with pytest.raises(ParserExecutionError, match="시간이 제한"):
        execute_parser(path, "value", settings)


def test_return_size_is_limited(tmp_path: Path) -> None:
    path = _write_parser(tmp_path, "def extract(html: str) -> str:\n    return 'x' * 100\n")
    settings = ExecutionSettings(max_output_bytes=10)
    with pytest.raises(ParserExecutionError, match="반환값이 제한"):
        execute_parser(path, "value", settings)
