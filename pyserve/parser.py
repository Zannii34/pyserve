"""HTTP/1.1 request parser — turns raw bytes into Request objects."""
from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import urlparse, parse_qs


@dataclass
class Request:
    """A parsed HTTP request."""
    method: str = "GET"
    path: str = "/"
    http_version: str = "HTTP/1.1"
    headers: Dict[str, str] = field(default_factory=dict)
    query: Dict[str, list] = field(default_factory=dict)
    body: bytes = b""
    remote_addr: str = ""

    @property
    def content_length(self) -> int:
        try:
            return int(self.headers.get("content-length", "0"))
        except ValueError:
            return 0

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")

    @property
    def user_agent(self) -> str:
        return self.headers.get("user-agent", "")

    @property
    def host(self) -> str:
        return self.headers.get("host", "")

    @property
    def wants_keep_alive(self) -> bool:
        """HTTP/1.1 defaults to keep-alive unless explicitly closed."""
        conn = self.headers.get("connection", "").lower()
        if self.http_version == "HTTP/1.1":
            return conn != "close"
        return conn == "keep-alive"


class ParseError(Exception):
    """Raised when the incoming bytes don't form a valid HTTP request."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def parse_request(raw: bytes, remote_addr: str = "") -> Request:
    """Parse raw HTTP request bytes into a Request object.

    Raises ParseError if the request is malformed.
    """
    if not raw:
        raise ParseError("Empty request")

    # Split headers and body at the first double CRLF
    try:
        header_bytes, _, body = raw.partition(b"\r\n\r\n")
    except ValueError:
        raise ParseError("Invalid request format")

    try:
        header_text = header_bytes.decode("iso-8859-1")
    except UnicodeDecodeError:
        raise ParseError("Headers are not valid ISO-8859-1")

    lines = header_text.split("\r\n")
    if not lines:
        raise ParseError("Empty request line")

    # Parse request line: METHOD PATH HTTP/VERSION
    request_line = lines[0].strip()
    parts = request_line.split(" ")
    if len(parts) != 3:
        raise ParseError(f"Invalid request line: {request_line!r}")

    method, target, http_version = parts
    if not http_version.startswith("HTTP/"):
        raise ParseError(f"Invalid HTTP version: {http_version}")

    # Parse query string
    parsed = urlparse(target)
    path = parsed.path or "/"
    query = parse_qs(parsed.query, keep_blank_values=True)

    # Parse headers
    headers: Dict[str, str] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        if ":" not in line:
            raise ParseError(f"Invalid header line: {line!r}")
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()

    return Request(
        method=method.upper(),
        path=path,
        http_version=http_version,
        headers=headers,
        query=query,
        body=body,
        remote_addr=remote_addr,
    )