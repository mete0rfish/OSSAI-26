#!/usr/bin/env python3
"""driver/Program.cs 를 Python으로 이식한 독립 실행형 CLI.

  python driver.python/main.py --url <DART_URL> --out <저장경로.html>
      [--main-only] [--section <지정자>] [--list-sections] [--sleep <ms>]

기본 동작: 메인 HTML -> iframe 추출 -> 상세(전체) HTML fetch + 클렌징 -> 파일 저장.
--main-only:     메인 HTML(원본)을 그대로 저장.
--section:       전체 본문 대신 지정한 목차 섹션만 fetch + 클렌징 -> 저장.
--list-sections: 목차만 출력하고 종료(--out 불필요).
"""

import argparse
import os
import sys

import dart_page_loader
import http_client_helper
import toc_helper
import variables


def main(argv: list[str]) -> int:
    # Windows 콘솔(cp949)에서 한글 목차가 깨지지 않도록
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--url")
    parser.add_argument("--out")
    parser.add_argument("--main-only", action="store_true")
    parser.add_argument("--section")
    parser.add_argument("--list-sections", action="store_true")
    parser.add_argument("--sleep", type=int)

    args, unknown = parser.parse_known_args(argv)
    for extra in unknown:
        print(f"[경고] 알 수 없는 인자: {extra}", file=sys.stderr)

    if args.sleep is not None:
        variables.SLEEP_INTERVAL_MS = args.sleep

    usage = (
        "사용법: python driver.python/main.py --url <DART_URL> --out <저장경로.html> "
        "[--main-only] [--section <지정자>] [--list-sections] [--sleep <ms>]"
    )

    if not args.url or (not args.out and not args.list_sections):
        print(usage, file=sys.stderr)
        return 2

    if args.section and args.main_only:
        print("[실패] --section 과 --main-only 는 함께 쓸 수 없습니다.", file=sys.stderr)
        return 2

    print(f"[1/3] 메인 HTML 요청: {args.url}")
    main_html = dart_page_loader.load_main_html(args.url)

    if not main_html:
        print("[실패] 메인 HTML이 비어 있습니다 (네트워크/타임아웃).", file=sys.stderr)
        return 1

    if http_client_helper.is_blocked_page(main_html):
        print("[실패] DART 차단/검토중 페이지가 반환되었습니다 (<title>거부</title>).", file=sys.stderr)
        return 1

    # --list-sections / --section 은 메인 HTML의 목차 트리를 먼저 파싱한다.
    toc: list[dict] = []
    if args.list_sections or args.section:
        toc = toc_helper.parse_toc(main_html)
        if not toc:
            print(
                "[실패] 목차를 찾지 못했습니다 (makeToc 미발견 — 목차 없는 공시일 수 있음). "
                "전체 본문은 --section 없이 받으세요.",
                file=sys.stderr,
            )
            return 1

    if args.list_sections:
        print("[2/2] 목차:")
        print(toc_helper.format_toc(toc))
        return 0

    if args.section:
        node, error = toc_helper.find_section(toc, args.section)
        if node is None:
            print(f"[실패] {error}", file=sys.stderr)
            print(toc_helper.format_toc(toc), file=sys.stderr)
            return 2

        section_url = toc_helper.build_section_url(node)
        print(f'[2/3] 섹션 "{node["path"]}" 요청 + 클렌징... (eleId={node["eleId"]}, '
              f'offset={node.get("offset")}, length={node.get("length")})')
        # 메인 HTML을 비워 넘기면 로더가 이 URL을 그대로 상세 URL로 쓴다(클렌징 동일 적용).
        html = dart_page_loader.load_sub_html("", section_url)
        if not html:
            print("[실패] 섹션 HTML을 가져오지 못했습니다 (타임아웃/차단).", file=sys.stderr)
            return 1
    elif args.main_only:
        html = main_html
        print("[2/3] --main-only: 메인 HTML을 그대로 저장합니다.")
    else:
        print("[2/3] iframe 추출 후 상세 HTML 요청 + 클렌징...")
        html = dart_page_loader.load_sub_html(main_html, args.url)
        if not html:
            print("[실패] 상세 HTML을 가져오지 못했습니다 (iframe 미발견/타임아웃).", file=sys.stderr)
            return 1

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        f.write(html)

    print(f"[3/3] 저장 완료: {os.path.abspath(args.out)} ({len(html):,} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
