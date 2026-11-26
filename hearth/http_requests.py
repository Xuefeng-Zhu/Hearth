"""Request framing, JSON shapes, and route metadata for the Hearth HTTP server."""

import json
import re
from dataclasses import dataclass, field

from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header

from .storage import HearthError

JSON_LIMIT = 24_000
MULTIPART_HEADER_LIMIT = 8_192
MULTIPART_CHUNK = 64 * 1024
MULTIPART_BOUNDARY = re.compile(rb"[\x21-\x7e]{1,70}")


class RequestError(HearthError):
    def __init__(self, message, status=400, *, headers=None):
        super().__init__(message)
        self.status = status
        self.headers = headers


def check_type(value, expected):
    if isinstance(expected, (type, tuple)):
        types = expected if isinstance(expected, tuple) else (expected,)
        return type(value) in types
    return expected(value)


def list_of(expected):
    return lambda value: isinstance(value, list) and all(check_type(item, expected) for item in value)


@dataclass(frozen=True)
class JSONShape:
    required: dict = field(default_factory=dict)
    optional: dict = field(default_factory=dict)

    def __call__(self, value):
        if not isinstance(value, dict):
            return False
        fields = self.required | self.optional
        return (self.required.keys() <= value.keys() <= fields.keys()
                and all(check_type(item, fields[key]) for key, item in value.items()))


@dataclass(frozen=True)
class Request:
    path: str
    query: dict
    params: dict
    body: dict | int | None
    operation: str = ""


@dataclass(frozen=True)
class Route:
    handler: str
    operation: str = ""
    shape: JSONShape | None = None
    media: str = "none"
    limit: int = 0
    origin: bool = False
    tick_token: bool = False
    during_restore: bool = False
    # None leaves locking to the handler or service. -1 waits, 0 tries once.
    lock_timeout: int | None = None
    storage_error: str = ""


def body_length(headers, limit):
    lengths = headers.get_all("Content-Length", [])
    if headers.get_all("Transfer-Encoding") or len(lengths) > 1:
        raise RequestError("Invalid request body framing.")
    if not lengths:
        return 0
    length = lengths[0].strip()
    if not re.fullmatch(r"[0-9]+", length):
        raise RequestError("Invalid request body length.")
    length = length.lstrip("0") or "0"
    if len(length) > len(str(limit)) or int(length) > limit:
        raise RequestError("The request body exceeds the size limit.", 413)
    return int(length)


def unique_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError
    return result


def read_json(stream, length):
    try:
        raw = stream.read(length)
        if len(raw) != length:
            raise ValueError
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_fields)
        # Reject non-finite numbers and escapes that cannot be written as UTF-8.
        json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, RecursionError):
        raise RequestError("Invalid JSON request.") from None
    if not isinstance(body, dict):
        raise RequestError("Expected a JSON object.")
    return body


def receive_multipart(stream, length, content_type, output, *, max_bytes):
    """Read a single file part in bounded chunks without buffering it in memory."""
    media_type, options = parse_options_header(content_type)
    boundary = options.get(b"boundary", b"")
    if media_type.lower() != b"multipart/form-data" or not MULTIPART_BOUNDARY.fullmatch(boundary):
        raise RequestError("Expected a multipart file upload.", 415)
    if length > max_bytes + 2 * MULTIPART_HEADER_LIMIT:
        raise RequestError("Each attachment can be up to 20 MB.", 413)
    if length <= 0:
        raise RequestError("No attachment was received.")
    headers = {}
    field, value = bytearray(), bytearray()
    header_size = size = parts = 0
    filename = None
    finished = False

    def start():
        nonlocal parts
        parts += 1
        if parts != 1:
            raise RequestError("Send one file in each upload request.")

    def extend(target, data, left, right):
        nonlocal header_size
        header_size += right - left
        if header_size > MULTIPART_HEADER_LIMIT or len(headers) >= 24:
            raise RequestError("The attachment headers are too large.", 413)
        target.extend(data[left:right])

    def header_end():
        headers[bytes(field).lower()] = bytes(value)
        field.clear()
        value.clear()

    def headers_finished():
        nonlocal filename
        disposition, params = parse_options_header(headers.get(b"content-disposition", b""))
        name = params.get(b"filename", b"")
        if disposition != b"form-data" or params.get(b"name") != b"file" or not name:
            raise RequestError("Expected a file part named file.")
        filename = name.decode("utf-8", "replace")

    def write(data, left, right):
        nonlocal size
        size += right - left
        if size > max_bytes:
            raise RequestError("Each attachment can be up to 20 MB.", 413)
        output.write(memoryview(data)[left:right])

    def end():
        nonlocal finished
        finished = True

    parser = MultipartParser(boundary, {
        "on_part_begin": start,
        "on_header_field": lambda *args: extend(field, *args),
        "on_header_value": lambda *args: extend(value, *args),
        "on_header_end": header_end,
        "on_headers_finished": headers_finished,
        "on_part_data": write,
        "on_end": end,
    })
    try:
        remaining = length
        while remaining:
            data = stream.read(min(MULTIPART_CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            parser.write(data)
        parser.finalize()
    except TimeoutError:
        raise RequestError("The attachment upload timed out.", 408) from None
    except MultipartParseError:
        raise RequestError("The multipart attachment is malformed.") from None
    if remaining or not finished or parts != 1 or filename is None:
        raise RequestError("The attachment upload was interrupted.")
    if not size:
        raise RequestError("The attachment is empty.")
    return filename, size
