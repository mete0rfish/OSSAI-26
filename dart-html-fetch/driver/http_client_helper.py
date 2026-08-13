"""GET/POST 요청, 차단 페이지 판별, 인코딩 판별. 원본 driver/HttpClientHelper.cs 대응."""

import re

import requests
import urllib3

from enums import RequestMethod, ReturnType

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/115.0.0.0 Safari/537.36"
)
_DEFAULT_REFERER = "https://dart.fss.or.kr"
_COOKIE_HEADER = "WMONID=...; JSESSIONID=..."

_CHARSET_RE = re.compile(r'charset\s*=\s*["\']?\s*([\w\-]+)', re.IGNORECASE)


def _create_session() -> requests.Session:
    session = requests.Session()
    session.verify = False
    session.headers.update(
        {
            "User-Agent": _DEFAULT_USER_AGENT,
            "Referer": _DEFAULT_REFERER,
            "Cookie": _COOKIE_HEADER,
        }
    )
    return session


_SESSION = _create_session()


def get_html_with_headers(url: str) -> str | None:
    """GET 요청."""
    try:
        response = _SESSION.get(url)
        if not response.ok:
            return None
        return _decode(response)
    except requests.RequestException:
        return None


def _decode(response: requests.Response) -> str:
    charset = _charset_from_content_type(response.headers.get("content-type"))
    encoding = resolve_encoding(charset, response.content)
    return response.content.decode(encoding, errors="replace")


def _charset_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    match = re.search(r"charset=([\w\-]+)", content_type, re.IGNORECASE)
    return match.group(1) if match else None


def is_blocked_page(html: str) -> bool:
    return "<title>거부</title>" in html and "검토중인 문서입니다." in html


def read_url(
    url: str,
    parameter: str = "",
    method: RequestMethod = RequestMethod.POST,
    return_type: ReturnType = ReturnType.STRING,
    referer: str = "",
):
    """POST 우선 시도 후 실패 시 GET 폴백. 원본과 동일하게 예외를 "Error: ..." 문자열로 반환."""
    try:
        response = None

        if method == RequestMethod.POST:
            response = _send_post(url, parameter, referer)
            if response is None or not response.ok:
                get_url = _append_parameter_to_url(url, parameter)
                response = _send_get(get_url, referer)
        else:
            get_url = _append_parameter_to_url(url, parameter)
            response = _send_get(get_url, referer)

        if response is None or not response.ok:
            return ""

        if return_type == ReturnType.STRING:
            return _decode(response)
        return response.content
    except requests.RequestException as ex:
        return f"Error: {ex}"


def _send_post(url: str, parameter: str, referer: str) -> requests.Response:
    headers = _referer_header(referer)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    return _SESSION.post(url, data=(parameter or "").encode("utf-8"), headers=headers)


def _send_get(url: str, referer: str) -> requests.Response:
    headers = _referer_header(referer)
    return _SESSION.get(url, headers=headers)


def _referer_header(referer: str) -> dict:
    return {"Referer": referer if referer and referer.strip() else _DEFAULT_REFERER}


def _append_parameter_to_url(url: str, parameter: str) -> str:
    if not parameter or not parameter.strip():
        return url

    parameter = parameter.lstrip("?&")

    if "?" in url:
        if url.endswith("?") or url.endswith("&"):
            return url + parameter
        return url + "&" + parameter

    return url + "?" + parameter


def resolve_encoding(charset: str | None, html_bytes: bytes | None = None) -> str:
    """인코딩 판별: 1) Content-Type charset -> 2) meta charset -> 3) UTF-8 폴백."""
    if charset:
        try:
            "x".encode(charset)
            return charset
        except LookupError:
            pass

    if html_bytes:
        prefix = html_bytes[:2048].decode("iso-8859-1")
        match = _CHARSET_RE.search(prefix)
        if match:
            try:
                "x".encode(match.group(1))
                return match.group(1)
            except LookupError:
                pass

    return "utf-8"
