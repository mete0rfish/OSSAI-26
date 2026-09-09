"""생성 코드의 문법과 진입점만 검사한다. 코드를 실행하거나 안전성을 보증하지 않는다."""

import ast

from .parser_schemas import ParserCodeCheck


def check_parser_code(source: str | None) -> ParserCodeCheck:
    if source is None:
        return ParserCodeCheck(status="not_applicable")
    try:
        tree = ast.parse(source)
        # AST parsing alone accepts some invalid modules (e.g. top-level return).
        compile(tree, "<generated-parser>", "exec", dont_inherit=True)
    except (SyntaxError, ValueError, RecursionError, OverflowError) as exc:
        # Never log exception text: syntax errors can contain generated source or HTML.
        return ParserCodeCheck(
            status="invalid", syntax_valid=False, issues=[type(exc).__name__]
        )
    functions = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "extract"
    ]
    valid = False
    if len(functions) == 1 and isinstance(functions[0], ast.FunctionDef):
        function = functions[0]
        args = function.args
        positional = [*args.posonlyargs, *args.args]
        valid = (
            len(positional) == 1
            and positional[0].arg == "html"
            and not args.defaults
            and not args.vararg
            and not args.kwarg
            and not args.kwonlyargs
            and not function.decorator_list
            and not any(
                isinstance(node, (ast.Yield, ast.YieldFrom)) for node in ast.walk(function)
            )
        )
    return ParserCodeCheck(
        status="valid" if valid else "invalid",
        syntax_valid=True,
        entrypoint_valid=valid,
        issues=[] if valid else ["동기 함수 extract(html) 하나가 필요합니다"],
    )
