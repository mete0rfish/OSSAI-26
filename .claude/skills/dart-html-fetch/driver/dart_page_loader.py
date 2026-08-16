"""메인/상세 HTML 로드 + 클렌징 + (더미)캐시. 원본 driver/DartPageLoader.cs 대응.

원본은 async/await + Task.Delay 폴링이지만, 이 드라이버는 단발성 CLI라
동기 함수 + time.sleep 으로 단순화했다.
"""

import hashlib
import html as html_module
import os
import re
import time
from datetime import datetime, timedelta, timezone

import http_client_helper
import iframe_helper
import variables

_DEFAULT_MAX_DURATION = timedelta(minutes=20)
_BLOCKED_TITLE = "이페이지에연결할수없음"

# 매 요청마다 재컴파일 방지 — 모듈 로드 시 한 번만 컴파일
_RE_XML_COMMENT = re.compile(r"<!--\?[^>]*\?-->")
_RE_BR = re.compile(r"<br\b[^>]*>", re.IGNORECASE)
_RE_OPEN_P_DIV = re.compile(r"<(p|div)\b[^>]*>", re.IGNORECASE)
_RE_CLOSE_P_DIV = re.compile(r"</(p|div)>", re.IGNORECASE)
_RE_NEWLINE_SPACE = re.compile(r"\r?\n[ ]+")
_RE_MULTI_SPACE = re.compile(r"[ ]{2,}")
_RE_MULTI_NEWLINE = re.compile(r"(\r?\n){2,}")
_RE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _cache_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "HtmlCache")


def _to_cache_path(url: str) -> str:
    hex_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
    return os.path.join(_cache_dir(), hex_hash + ".html")


def _try_read_cache(url: str):
    if not variables.USE_HTML_CACHE:
        return None
    path = _to_cache_path(url)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write_cache(url: str, html: str) -> None:
    if not variables.USE_HTML_CACHE or not html:
        return
    os.makedirs(_cache_dir(), exist_ok=True)
    with open(_to_cache_path(url), "w", encoding="utf-8") as f:
        f.write(html)


def _extract_title(html: str) -> str:
    match = _RE_TITLE.search(html)
    return (match.group(1) if match else "").replace(" ", "")


def load_main_html(entry_url: str, max_duration: timedelta = _DEFAULT_MAX_DURATION):
    cached = _try_read_cache(entry_url)
    if cached is not None:
        return cached

    deadline = datetime.now(timezone.utc) + max_duration

    while datetime.now(timezone.utc) < deadline:
        html = http_client_helper.get_html_with_headers(entry_url)
        if not html:
            time.sleep(variables.SLEEP_INTERVAL_MS / 1000)
            continue

        if http_client_helper.is_blocked_page(html):
            return html

        if _extract_title(html) != _BLOCKED_TITLE:
            _write_cache(entry_url, html)
            return html

        time.sleep(variables.SLEEP_INTERVAL_MS / 1000)

    return None


def load_sub_html(main_html: str, entry_url: str, max_duration: timedelta = _DEFAULT_MAX_DURATION):
    deadline = datetime.now(timezone.utc) + max_duration

    while datetime.now(timezone.utc) < deadline:
        try:
            if main_html:
                sub_url = iframe_helper.extract_iframe_url(main_html)
                if not sub_url:
                    return None  # iframe 못 찾으면 재시도 의미 없음
            else:
                sub_url = entry_url

            cached_detail = _try_read_cache(sub_url)
            if cached_detail is not None:
                return cached_detail

            # 메인→서브 사이 대기
            if variables.SLEEP_INTERVAL_MS > 0:
                time.sleep(variables.SLEEP_INTERVAL_MS / 1000)

            detail_html = http_client_helper.read_url(sub_url)

            # 네트워크 오류 시 read_url은 "" 또는 "Error:..." 문자열을 반환하므로 예외로 전환해 재시도
            if not detail_html or detail_html.startswith("Error:"):
                raise RuntimeError(f"HTML 응답 오류: {sub_url}")

            detail_html = _RE_XML_COMMENT.sub("", detail_html)
            detail_html = html_module.unescape(detail_html)
            detail_html = detail_html.replace("\xa0", " ")
            detail_html = _RE_BR.sub("\r\n", detail_html)
            detail_html = _RE_OPEN_P_DIV.sub("\r\n", detail_html)
            detail_html = _RE_CLOSE_P_DIV.sub("\r\n", detail_html)
            detail_html = detail_html.replace("\t", "")
            detail_html = _RE_NEWLINE_SPACE.sub("\r\n", detail_html)
            detail_html = _RE_MULTI_SPACE.sub(" ", detail_html)
            detail_html = _RE_MULTI_NEWLINE.sub("\r\n", detail_html)

            if detail_html and _extract_title(detail_html) != _BLOCKED_TITLE:
                _write_cache(sub_url, detail_html)
                return detail_html

        except Exception:
            pass

        time.sleep(variables.SLEEP_INTERVAL_MS / 1000)

    return None
