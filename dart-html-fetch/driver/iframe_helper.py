"""viewDoc(...) JS 호출에서 상세 문서 iframe URL 추출. 원본 driver/IframeHelper.cs 대응."""

import re

_VIEW_DOC_RE = re.compile(
    r'viewDoc\(\s*"(?P<rcpNo>\d+)",\s*"(?P<dcmNo>\d+)",.*?'
    r'"(?P<eleId>[^"]*)",.*?"(?P<offset>[^"]*)",.*?"(?P<length>[^"]*)",\s*"(?P<dtd>[^"]+)"',
    re.IGNORECASE,
)


def extract_iframe_url(html: str) -> str:
    match = _VIEW_DOC_RE.search(html)
    if not match:
        return ""

    rcp_no = match.group("rcpNo")
    dcm_no = match.group("dcmNo")
    ele_id = match.group("eleId")
    dtd = match.group("dtd")

    if not rcp_no or not dcm_no:
        return ""

    dtd_param = f"&dtd={dtd}" if dtd else ""
    return (
        f"https://dart.fss.or.kr/report/viewer.do?rcpNo={rcp_no}&dcmNo={dcm_no}"
        f"&eleId={ele_id}&offset=0&length=0{dtd_param}"
    )
