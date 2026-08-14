"""수집 범위/요청 간격 전역 설정. 원본 driver/Variables.cs 대응."""

# DART 차단 회피용 요청 간격(ms). 원본과 동일한 기본값 유지.
SLEEP_INTERVAL_MS = 2500

# 이전에 받은 HTML을 재사용할지 여부. 드라이버는 항상 새로 받도록 False.
USE_HTML_CACHE = False
