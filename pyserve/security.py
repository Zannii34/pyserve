"""Security utilities — rate limiting, request size limits, slowloris defense."""
import time
import threading
from collections import defaultdict, deque
from typing import Deque, Dict

from pyserve.parser import Request
from pyserve.response import Response
from pyserve.middleware import Middleware


# ---------------- Rate Limiting ----------------


class RateLimiter:
    """Token bucket rate limiter, keyed by client IP.

    Allows `rate` requests per `per` seconds, with a burst of `burst`.
    """

    def __init__(self, rate: int = 60, per: int = 60, burst: int = 10):
        self.rate = rate      # tokens refilled per `per` seconds
        self.per = per
        self.burst = burst    # max tokens (bucket capacity)
        self.buckets: Dict[str, tuple] = {}  # ip -> (tokens, last_refill_ts)
        self.lock = threading.Lock()

    def check(self, ip: str) -> tuple:
        """Return (allowed: bool, retry_after: float)."""
        now = time.monotonic()

        with self.lock:
            if ip not in self.buckets:
                self.buckets[ip] = (float(self.burst), now)
            tokens, last_refill = self.buckets[ip]

            # Refill based on time passed
            elapsed = now - last_refill
            refill_rate = self.rate / self.per
            tokens = min(self.burst, tokens + elapsed * refill_rate)

            if tokens >= 1:
                tokens -= 1
                self.buckets[ip] = (tokens, now)
                return True, 0.0
            else:
                self.buckets[ip] = (tokens, now)
                # Time until next token
                needed = 1 - tokens
                wait = needed / refill_rate
                return False, wait

    def cleanup(self, max_age: float = 3600):
        """Remove buckets that haven't been touched in max_age seconds."""
        now = time.monotonic()
        with self.lock:
            stale = [ip for ip, (_, ts) in self.buckets.items() if now - ts > max_age]
            for ip in stale:
                del self.buckets[ip]

    def __repr__(self) -> str:
        return f"<RateLimiter {self.rate}req/{self.per}s burst={self.burst}>"


class RateLimitMiddleware(Middleware):
    """Middleware: enforce per-IP rate limits."""

    def __init__(self, rate: int = 60, per: int = 60, burst: int = 10):
        self.limiter = RateLimiter(rate=rate, per=per, burst=burst)
        self._last_cleanup = time.monotonic()

    def before(self, request: Request):
        ip = request.remote_addr or "unknown"
        allowed, retry_after = self.limiter.check(ip)

        # Periodic cleanup
        now = time.monotonic()
        if now - self._last_cleanup > 300:  # every 5 min
            self.limiter.cleanup()
            self._last_cleanup = now

        if not allowed:
            resp = Response.json(
                {"error": "Too Many Requests", "retry_after": round(retry_after, 1)},
                status=429,
            )
            resp.set_header("Retry-After", str(int(retry_after) + 1))
            return resp
        return None


# ---------------- Request Size Limits ----------------


class RequestSizeLimitMiddleware(Middleware):
    """Reject requests with a body larger than max_bytes."""

    def __init__(self, max_bytes: int = 10 * 1024 * 1024):  # 10 MB default
        self.max_bytes = max_bytes

    def before(self, request: Request):
        content_length = request.content_length
        if content_length > self.max_bytes:
            return Response.json(
                {"error": "Payload Too Large", "max_bytes": self.max_bytes},
                status=413,
            )
        return None


# ---------------- Slowloris Protection ----------------


class SlowlorisDefense:
    """Track active connections per IP. Reject IPs opening too many sockets.

    Slowloris attacks open many connections and hold them open by sending
    headers very slowly. Our defense: cap connections per IP.
    """

    def __init__(self, max_connections_per_ip: int = 20):
        self.max = max_connections_per_ip
        self.active: Dict[str, int] = defaultdict(int)
        self.lock = threading.Lock()

    def acquire(self, ip: str) -> bool:
        with self.lock:
            if self.active[ip] >= self.max:
                return False
            self.active[ip] += 1
            return True

    def release(self, ip: str) -> None:
        with self.lock:
            if self.active[ip] > 0:
                self.active[ip] -= 1
            if self.active[ip] == 0:
                self.active.pop(ip, None)

    def stats(self) -> Dict[str, int]:
        with self.lock:
            return dict(self.active)


# ---------------- Path Validation ----------------


def is_safe_path(path: str) -> bool:
    """Return True if the path doesn't contain obvious traversal attempts."""
    if not path:
        return True
    if "\x00" in path:
        return False
    # Decode URL-encoded traversal
    from urllib.parse import unquote
    decoded = unquote(path)
    if ".." in decoded.split("/"):
        return False
    if decoded.startswith("/etc/") or decoded.startswith("/root/"):
        return False
    return True


# ---------------- Blocked User Agents ----------------


DEFAULT_BLOCKED_USER_AGENTS = [
    "sqlmap",
    "nikto",
    "nmap",
    "masscan",
    "acunetix",
    "nessus",
]


class UserAgentBlockMiddleware(Middleware):
    """Block requests with known malicious User-Agent strings."""

    def __init__(self, blocked: list = None):
        self.blocked = [b.lower() for b in (blocked or DEFAULT_BLOCKED_USER_AGENTS)]

    def before(self, request: Request):
        ua = request.user_agent.lower()
        for pattern in self.blocked:
            if pattern in ua:
                return Response.json(
                    {"error": "Forbidden", "reason": "Blocked User-Agent"},
                    status=403,
                )
        return None