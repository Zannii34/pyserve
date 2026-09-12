"""Middleware chain — run functions before and after each request."""
from typing import Callable, List, Optional
from pyserve.parser import Request
from pyserve.response import Response


class Middleware:
    """A single middleware — has optional before() and after() hooks.

    Subclass this or use Middleware.func() for simple cases.
    """

    def before(self, request: Request) -> Optional[Response]:
        """Called before the handler. Return a Response to short-circuit."""
        return None

    def after(self, request: Request, response: Response) -> Response:
        """Called after the handler. Return the (possibly modified) response."""
        return response


class FunctionMiddleware(Middleware):
    """Wrap plain functions into a Middleware object."""

    def __init__(self, before_fn: Optional[Callable] = None, after_fn: Optional[Callable] = None):
        self._before = before_fn
        self._after = after_fn

    def before(self, request: Request) -> Optional[Response]:
        return self._before(request) if self._before else None

    def after(self, request: Request, response: Response) -> Response:
        return self._after(request, response) if self._after else response


class MiddlewareChain:
    """Runs a list of middlewares in order."""

    def __init__(self):
        self.middlewares: List[Middleware] = []

    def add(self, mw: Middleware) -> None:
        self.middlewares.append(mw)

    def add_function(self, before_fn=None, after_fn=None) -> None:
        self.middlewares.append(FunctionMiddleware(before_fn, after_fn))

    def run_before(self, request: Request) -> Optional[Response]:
        """Run all before() hooks. If any returns a Response, stop and return it."""
        for mw in self.middlewares:
            try:
                resp = mw.before(request)
            except Exception as e:
                return Response.server_error(f"Middleware error: {e}")
            if resp is not None:
                return resp
        return None

    def run_after(self, request: Request, response: Response) -> Response:
        """Run all after() hooks in reverse order (like a stack unwinding)."""
        for mw in reversed(self.middlewares):
            try:
                response = mw.after(request, response)
            except Exception:
                # Don't let a broken after() hook break the response
                pass
        return response

    def __len__(self) -> int:
        return len(self.middlewares)


# ---------------- Built-in middlewares ----------------


class LoggerMiddleware(Middleware):
    """Logs each request with method, path, status, duration."""

    def __init__(self, log_fn: Optional[Callable] = None):
        self.log_fn = log_fn or self._default_log
        self._start_times = {}

    def before(self, request: Request) -> Optional[Response]:
        import time
        self._start_times[id(request)] = time.time()
        return None

    def after(self, request: Request, response: Response) -> Response:
        import time
        start = self._start_times.pop(id(request), None)
        duration_ms = (time.time() - start) * 1000 if start else 0

        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        line = (
            f"{timestamp} "
            f"{request.remote_addr or '-':15s} "
            f"{request.method:6s} "
            f"{request.path[:40]:40s} "
            f"{response.status} "
            f"{len(response.body):>7d}B "
            f"{duration_ms:7.2f}ms"
        )
        self.log_fn(line)
        return response

    @staticmethod
    def _default_log(line: str) -> None:
        print(line)


class CorsMiddleware(Middleware):
    """Adds CORS headers to every response."""

    def __init__(self, origin: str = "*", methods: str = "GET, POST, PUT, DELETE, OPTIONS", headers: str = "Content-Type"):
        self.origin = origin
        self.methods = methods
        self.headers = headers

    def before(self, request: Request) -> Optional[Response]:
        # Respond to preflight OPTIONS requests
        if request.method == "OPTIONS":
            resp = Response(status=204)
            resp.set_header("Access-Control-Allow-Origin", self.origin)
            resp.set_header("Access-Control-Allow-Methods", self.methods)
            resp.set_header("Access-Control-Allow-Headers", self.headers)
            resp.set_header("Access-Control-Max-Age", "86400")
            return resp
        return None

    def after(self, request: Request, response: Response) -> Response:
        response.set_header("Access-Control-Allow-Origin", self.origin)
        response.set_header("Access-Control-Allow-Methods", self.methods)
        response.set_header("Access-Control-Allow-Headers", self.headers)
        return response


class SecurityHeadersMiddleware(Middleware):
    """Adds common security headers to every response."""

    def after(self, request: Request, response: Response) -> Response:
        response.set_header("X-Content-Type-Options", "nosniff")
        response.set_header("X-Frame-Options", "SAMEORIGIN")
        response.set_header("Referrer-Policy", "strict-origin-when-cross-origin")
        return response


class TimingMiddleware(Middleware):
    """Adds X-Response-Time header."""

    def before(self, request: Request) -> Optional[Response]:
        import time
        request._start_time = time.time()
        return None

    def after(self, request: Request, response: Response) -> Response:
        import time
        start = getattr(request, "_start_time", None)
        if start:
            duration_ms = (time.time() - start) * 1000
            response.set_header("X-Response-Time", f"{duration_ms:.2f}ms")
        return response