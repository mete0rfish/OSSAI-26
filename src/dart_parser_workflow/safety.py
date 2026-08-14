"""생성된 파서에 대한 보수적인 정적 안전 검사."""

from __future__ import annotations

import ast
from dataclasses import dataclass

ALLOWED_IMPORTS = {
    "bs4",
    "datetime",
    "decimal",
    "html",
    "re",
    "typing",
    "unicodedata",
}

BANNED_CALLS = {
    "__import__",
    "breakpoint",
    "compile",
    "delattr",
    "dir",
    "eval",
    "exec",
    "getattr",
    "globals",
    "help",
    "input",
    "locals",
    "open",
    "setattr",
    "vars",
}

BANNED_NAMES = {
    "__builtins__",
    "ctypes",
    "importlib",
    "multiprocessing",
    "os",
    "pathlib",
    "shutil",
    "signal",
    "socket",
    "subprocess",
    "sys",
}


@dataclass(slots=True)
class SafetyViolation(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def _validate_module_statement(node: ast.stmt) -> None:
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)):
        return
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        if isinstance(node.value.value, str):
            return
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        value = node.value
        if value is None:
            return
        try:
            ast.literal_eval(value)
        except ValueError, TypeError:
            raise SafetyViolation("모듈 수준에는 리터럴 상수만 할당할 수 있습니다") from None
        return
    raise SafetyViolation(
        f"모듈 import 시 실행될 수 있는 문장은 허용하지 않습니다: {type(node).__name__}"
    )


def validate_parser_source(source: str, max_source_bytes: int) -> None:
    if len(source.encode("utf-8")) > max_source_bytes:
        raise SafetyViolation("생성 코드가 source 크기 제한을 초과했습니다")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SafetyViolation(f"Python 구문 오류: {exc.msg} (line {exc.lineno})") from exc

    for statement in tree.body:
        _validate_module_statement(statement)

    extracts = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "extract"
    ]
    if len(extracts) != 1:
        raise SafetyViolation("정확히 하나의 extract 함수를 정의해야 합니다")
    extract = extracts[0]
    if extract.decorator_list:
        raise SafetyViolation("extract 함수 decorator는 허용하지 않습니다")
    arguments = extract.args
    if (
        len(arguments.posonlyargs) + len(arguments.args) != 1
        or arguments.vararg is not None
        or arguments.kwarg is not None
        or arguments.kwonlyargs
    ):
        raise SafetyViolation("extract 함수는 html 위치 인자 하나만 받아야 합니다")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root not in ALLOWED_IMPORTS:
                    raise SafetyViolation(f"허용되지 않은 import입니다: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise SafetyViolation("상대 import는 허용하지 않습니다")
            root = (node.module or "").split(".", 1)[0]
            if root not in ALLOWED_IMPORTS:
                raise SafetyViolation(f"허용되지 않은 import입니다: {node.module}")
            if any(alias.name == "*" for alias in node.names):
                raise SafetyViolation("별표 import는 허용하지 않습니다")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in BANNED_CALLS:
                raise SafetyViolation(f"허용되지 않은 함수 호출입니다: {node.func.id}")
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            raise SafetyViolation(f"허용되지 않은 이름입니다: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise SafetyViolation(f"dunder attribute 접근은 허용하지 않습니다: {node.attr}")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            raise SafetyViolation("global/nonlocal 문은 허용하지 않습니다")
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom)):
            raise SafetyViolation("비동기 함수와 generator는 허용하지 않습니다")
