"""Response compression — gzip and deflate, negotiated via Accept-Encoding."""
import gzip
import zlib
from typing import Optional

from pyserve.parser import Request
from pyserve.response import Response
from pyserve.middleware import Middleware


# Content types that benefit from compression
COMPRESSIBLE_TYPES = (
    "text/",
    "application/json",
    "application/javascript",
    "application/xml",
    "application/xhtml+xml",
    "image/svg+xml",
)

# Below this size, compression isn't worth it
MIN_COMPRESS_SIZE = 512


def _is_compressible(content_type: str) -> bool:
    if not content_type:
        return False
    ct = content_type.lower()
    return any(ct.startswith(prefix) for prefix in COMPRESSIBLE_TYPES)


def _parse_accept_encoding(header: str) -> list:
    """Parse 'gzip, deflate, br' into [('gzip', 1.0), ('deflate', 0.9), ...]."""
    if not header:
        return []
    items = []
    for part in header.split(","):
        part = part.strip()
        if not part:
            continue
        # Handle q= values: "gzip;q=0.8"
        if ";q=" in part:
            name, _, q_str = part.partition(";q=")
            try:
                q = float(q_str.strip())
            except ValueError:
                q = 1.0
            items.append((name.strip().lower(), q))
        else:
            items.append((part.lower(), 1.0))
    # Sort by q descending
    items.sort(key=lambda x: -x[1])
    return items


def choose_encoding(accept_encoding: str) -> Optional[str]:
    """Pick the best supported encoding from the client's Accept-Encoding."""
    items = _parse_accept_encoding(accept_encoding)
    for name, q in items:
        if q <= 0:
            continue
        if name in ("gzip", "x-gzip"):
            return "gzip"
        if name == "deflate":
            return "deflate"
    return None


def compress_body(body: bytes, encoding: str) -> bytes:
    """Compress bytes using the specified encoding."""
    if encoding == "gzip":
        # mtime=0 makes gzip output deterministic (important for caching)
        return gzip.compress(body, compresslevel=6, mtime=0)
    if encoding == "deflate":
        # zlib format for deflate
        return zlib.compress(body, level=6)
    return body


class CompressionMiddleware(Middleware):
    """Compress responses if:
       - client sent Accept-Encoding: gzip or deflate
       - response Content-Type is compressible
       - body size > MIN_COMPRESS_SIZE
       - response doesn't already have Content-Encoding
       - status is 200 (don't compress errors/redirects)
    """

    def __init__(self, min_size: int = MIN_COMPRESS_SIZE, level: int = 6):
        self.min_size = min_size
        self.level = level

    def after(self, request: Request, response: Response) -> Response:
        # Skip if already encoded
        if response.get_header("Content-Encoding"):
            return response

        # Skip errors and redirects
        if response.status != 200:
            return response

        # Skip small responses
        if len(response.body) < self.min_size:
            return response

        # Check content type
        content_type = response.get_header("Content-Type")
        if not _is_compressible(content_type):
            return response

        # Negotiate encoding
        accept_encoding = request.headers.get("accept-encoding", "")
        encoding = choose_encoding(accept_encoding)
        if not encoding:
            return response

        original_size = len(response.body)
        compressed = compress_body(response.body, encoding)

        # Only use compressed if actually smaller
        if len(compressed) >= original_size:
            return response

        response.body = compressed
        response.set_header("Content-Encoding", encoding)
        response.set_header("Vary", "Accept-Encoding")
        # Note: Content-Length is set later in to_bytes()

        return response


# ---------------- Cache utilities ----------------


class CacheMiddleware(Middleware):
    """Handle ETag / If-None-Match and Last-Modified / If-Modified-Since.

    Returns 304 Not Modified if the client already has the current version.
    """

    def after(self, request: Request, response: Response) -> Response:
        # Only for GET
        if request.method != "GET":
            return response

        # Only for successful responses
        if response.status != 200:
            return response

        etag = response.get_header("ETag")
        last_modified = response.get_header("Last-Modified")

        # Check If-None-Match (ETag)
        if etag:
            client_etag = request.headers.get("if-none-match", "")
            if client_etag and self._etag_matches(client_etag, etag):
                return self._not_modified(response)

        # Check If-Modified-Since (Last-Modified)
        if last_modified:
            client_since = request.headers.get("if-modified-since", "")
            if client_since and client_since == last_modified:
                return self._not_modified(response)

        return response

    @staticmethod
    def _etag_matches(client_etag: str, current_etag: str) -> bool:
        # Handle "*" (matches any) and comma-separated lists
        if client_etag.strip() == "*":
            return True
        for tag in client_etag.split(","):
            if tag.strip() == current_etag:
                return True
        return False

    @staticmethod
    def _not_modified(original: Response) -> Response:
        resp = Response(status=304)
        # 304 responses must include ETag if 200 would have
        for header in ("ETag", "Last-Modified", "Cache-Control"):
            value = original.get_header(header)
            if value:
                resp.set_header(header, value)
        return resp