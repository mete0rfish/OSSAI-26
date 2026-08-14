"""별도 Python 프로세스 안에서 검사를 통과한 파서를 호출한다."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path


class OutputLimitExceeded(RuntimeError):
    pass


class LimitedWriter(io.TextIOBase):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.size = 0

    def write(self, value: str) -> int:
        self.size += len(value.encode("utf-8"))
        if self.size > self.limit:
            raise OutputLimitExceeded("파서의 로그 출력이 제한을 초과했습니다")
        return len(value)


def _load_parser(path: Path):
    spec = importlib.util.spec_from_file_location("generated_parser", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("생성 파서 모듈을 불러올 수 없습니다")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    parser_path = Path(sys.argv[1])
    output_limit = int(sys.argv[2])
    sys.dont_write_bytecode = True
    html = sys.stdin.read()
    sink = LimitedWriter(output_limit)
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            module = _load_parser(parser_path)
            value = module.extract(html)
        if not isinstance(value, str):
            raise TypeError(f"extract 반환값은 str이어야 합니다: {type(value).__name__}")
        if len(value.encode("utf-8")) > output_limit:
            raise OutputLimitExceeded("extract 반환값이 제한을 초과했습니다")
        payload = {"ok": True, "value": value}
    except BaseException as exc:  # 생성 코드는 SystemExit도 결과로 보존한다.
        payload = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:2000]}"}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
