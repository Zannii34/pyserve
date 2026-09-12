"""HTTP/1.1 response builder — turns Python objects into wire bytes."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional
import json as json_module
import mimetypes


# Standard reason phrases for status codes
STATUS_REASONS = {
    200: "OK",
    201: "Created",
    204: "No Content",
    301: "Moved Permanently",
    302: "Found",
    304: "Not Modified",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    413: "Payload Too Large",
    429: "Too Many Requests",
    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
}


def http_date(dt: Optional[datetime] = None) -> str:
    """Format a datetime as an HTTP-date (RFC 7231)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


@dataclass
class Response:
    """An HTTP response."""

    status: int = 200
    body: bytes = b""
    headers: Dict[str, str] = field(default_factory=dict)
    http_version: str = "HTTP/1.1"

    # ---------- Convenience constructors ----------

    @classmethod
    def text(cls, content: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> "Response":
        return cls(
            status=status,
            body=content.encode("utf-8"),
            headers={"Content-Type": content_type},
        )

    @classmethod
    def html(cls, content: str, status: int = 200) -> "Response":
        return cls.text(content, status=status, content_type="text/html; charset=utf-8")

    @classmethod
    def json(cls, data, status: int = 200) -> "Response":
        return cls(
            status=status,
            body=json_module.dumps(data, indent=2, default=str).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

    @classmethod
    def redirect(cls, location: str, status: int = 302) -> "Response":
        return cls(status=status, headers={"Location": location})

    @classmethod
    def no_content(cls) -> "Response":
        return cls(status=204)

    @classmethod
    def not_found(cls) -> "Response":
        return cls.html(
            "<!DOCTYPE html><html><head><title>404 Not Found</title></head>"
            "<body><h1>404 Not Found</h1><p>The requested resource was not found.</p></body></html>",
            status=404,
        )

    @classmethod
    def server_error(cls, message: str = "Internal Server Error") -> "Response":
        return cls.html(
            f"<!DOCTYPE html><html><head><title>500 Server Error</title></head>"
            f"<body><h1>500 Server Error</h1><p>{message}</p></body></html>",
            status=500,
        )

    # ---------- Header helpers ----------

    def set_header(self, name: str, value: str) -> None:
        self.headers[name] = value

    def get_header(self, name: str, default: str = "") -> str:
        for k, v in self.headers.items():
            if k.lower() == name.lower():
                return v
        return default

    # ---------- Serialization ----------

    def to_bytes(self, keep_alive: bool = True) -> bytes:
        """Serialize the response to HTTP/1.1 wire format."""
        if self.status not in STATUS_REASONS:
            reason = "Unknown"
        else:
            reason = STATUS_REASONS[self.status]

        # Status line
        status_line = f"{self.http_version} {self.status} {reason}\r\n"

        # Ensure required headers
        headers = dict(self.headers)
        if "Server" not in headers:
            headers["Server"] = "PyServe/0.1.0"
        if "Date" not in headers:
            headers["Date"] = http_date()
        headers["Content-Length"] = str(len(self.body))

        # Connection header
        if keep_alive:
            if self.http_version == "HTTP/1.1" and headers.get("Connection", "").lower() != "close":
                headers.setdefault("Connection", "keep-alive")
        else:
            headers["Connection"] = "close"

        # Format headers
        header_lines = "".join(f"{k}: {v}\r\n" for k, v in headers.items())

        # Combine
        return status_line.encode("iso-8859-1") + header_lines.encode("iso-8859-1") + b"\r\n" + self.body


def guess_content_type(path: str) -> str:
    """Return the MIME type for a file path."""
    content_type, _ = mimetypes.guess_type(path)
    if content_type is None:
        return "application/octet-stream"
    # Add charset for text types
    if content_type.startswith("text/") and "charset" not in content_type:
        return f"{content_type}; charset=utf-8"
    return content_type