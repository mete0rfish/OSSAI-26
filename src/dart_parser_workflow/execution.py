"""생성된 파서를 제한된 subprocess에서 실행한다."""

from __future__ import annotations

import json
import math
import os
import platform
import resource
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import ExecutionSettings


@dataclass(slots=True)
class ParserExecutionError(Exception):
    kind: str
    message: str

    def __str__(self) -> str:
        return self.message


def _resource_limits(settings: ExecutionSettings):
    def set_when_supported(resource_kind: int, soft: int, hard: int) -> None:
        try:
            resource.setrlimit(resource_kind, (soft, hard))
        except OSError, ValueError:
            # 일부 macOS/sandbox 조합은 특정 limit을 지원하지 않는다. 부모의 wall timeout과
            # 출력 제한은 항상 적용되며, 지원되는 resource limit만 추가 방어선으로 사용한다.
            pass

    def apply() -> None:
        cpu_seconds = max(1, math.ceil(settings.timeout_seconds))
        set_when_supported(resource.RLIMIT_CPU, cpu_seconds, cpu_seconds + 1)
        memory_bytes = settings.memory_mb * 1024 * 1024
        memory_limit = resource.RLIMIT_DATA if platform.system() == "Darwin" else resource.RLIMIT_AS
        set_when_supported(memory_limit, memory_bytes, memory_bytes)
        set_when_supported(resource.RLIMIT_FSIZE, 0, 0)
        set_when_supported(resource.RLIMIT_NOFILE, 32, 32)

    return apply


def execute_parser(parser_path: Path, html: str, settings: ExecutionSettings) -> str:
    runner = Path(__file__).with_name("sandbox_runner.py").resolve()
    environment = {
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PATH": os.environ.get("PATH", ""),
    }
    try:
        with tempfile.TemporaryDirectory(prefix="dart-parser-") as sandbox_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(runner),
                    str(parser_path.resolve()),
                    str(settings.max_output_bytes),
                ],
                input=html,
                text=True,
                capture_output=True,
                cwd=sandbox_dir,
                env=environment,
                timeout=settings.timeout_seconds,
                check=False,
                preexec_fn=_resource_limits(settings),
            )
    except subprocess.TimeoutExpired as exc:
        raise ParserExecutionError("timeout", "파서 실행 시간이 제한을 초과했습니다") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise ParserExecutionError("sandbox_error", f"subprocess 시작 실패: {exc}") from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip()[:2000]
        raise ParserExecutionError(
            "process_error",
            f"파서 subprocess가 종료 코드 {completed.returncode}로 실패했습니다: {detail}",
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ParserExecutionError(
            "protocol_error", "파서 subprocess 응답이 JSON이 아닙니다"
        ) from exc
    if not payload.get("ok"):
        raise ParserExecutionError("runtime_error", str(payload.get("error", "알 수 없는 오류")))
    value = payload.get("value")
    if not isinstance(value, str):
        raise ParserExecutionError(
            "protocol_error", "파서 subprocess가 문자열을 반환하지 않았습니다"
        )
    return value
