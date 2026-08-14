"""HTTP 요청 메서드/응답 반환 타입. 원본 driver/Enums.cs 대응."""

from enum import Enum


class RequestMethod(Enum):
    GET = "GET"
    POST = "POST"


class ReturnType(Enum):
    STRING = "string"
    BYTE_ARRAY = "bytes"
