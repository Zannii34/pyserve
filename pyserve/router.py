"""URL routing — decorator-based like Flask, but built from scratch."""
import re
from typing import Callable, Dict, List, Optional, Tuple, Pattern
from pyserve.parser import Request


class Route:
    """A single route: method + path pattern + handler function."""

    def __init__(self, method: str, pattern: str, handler: Callable, name: Optional[str] = None):
        self.method = method.upper()
        self.pattern = pattern
        self.handler = handler
        self.name = name or handler.__name__
        self.regex, self.param_names = self._compile_pattern(pattern)

    @staticmethod
    def _compile_pattern(pattern: str) -> Tuple[Pattern, List[str]]:
        """Turn '/users/<id>' into a regex with capture groups."""
        # Escape regex special chars (except our <...> markers)
        param_names = []
        regex_parts = []

        # Split on <...> markers
        i = 0
        while i < len(pattern):
            if pattern[i] == "<":
                j = pattern.find(">", i)
                if j == -1:
                    raise ValueError(f"Unclosed < in pattern: {pattern}")
                param_name = pattern[i + 1 : j].strip()
                # Support <int:id> and <str:name> and <path:filepath>
                if ":" in param_name:
                    ptype, pname = param_name.split(":", 1)
                    ptype = ptype.strip()
                    pname = pname.strip()
                else:
                    ptype, pname = "str", param_name
                param_names.append((pname, ptype))

                if ptype == "int":
                    regex_parts.append(r"(\d+)")
                elif ptype == "path":
                    regex_parts.append(r"(.+?)")
                else:  # str
                    regex_parts.append(r"([^/]+)")

                i = j + 1
            else:
                # Regular character — escape it
                regex_parts.append(re.escape(pattern[i]))
                i += 1

        regex = re.compile("^" + "".join(regex_parts) + "$")
        return regex, param_names

    def match(self, method: str, path: str) -> Optional[Dict[str, object]]:
        """Try to match this route against a request. Returns kwargs or None."""
        if method.upper() != self.method:
            return None
        m = self.regex.match(path)
        if not m:
            return None

        kwargs = {}
        for (pname, ptype), value in zip(self.param_names, m.groups()):
            if ptype == "int":
                try:
                    kwargs[pname] = int(value)
                except ValueError:
                    return None
            else:
                kwargs[pname] = value
        return kwargs


class Router:
    """Holds all registered routes and dispatches requests."""

    def __init__(self):
        self.routes: List[Route] = []
        self._not_found_handler: Optional[Callable] = None

    # ---------- Decorator API ----------

    def route(self, path: str, methods: Optional[List[str]] = None):
        """Decorator: @router.route('/path', methods=['GET', 'POST'])"""
        methods = methods or ["GET"]

        def decorator(fn: Callable) -> Callable:
            for method in methods:
                self.routes.append(Route(method, path, fn))
            return fn

        return decorator

    def get(self, path: str):
        return self.route(path, ["GET"])

    def post(self, path: str):
        return self.route(path, ["POST"])

    def put(self, path: str):
        return self.route(path, ["PUT"])

    def delete(self, path: str):
        return self.route(path, ["DELETE"])

    def not_found(self, fn: Callable) -> Callable:
        """Decorator: @router.not_found"""
        self._not_found_handler = fn
        return fn

    # ---------- Dispatch ----------

    def dispatch(self, request: Request) -> Tuple[Optional[Callable], Dict[str, object]]:
        """Find the handler for this request. Returns (handler, kwargs) or (None, {}).

        If the path matches but the method doesn't, sets request._method_not_allowed=True.
        """
        path = request.path

        # First pass: try exact method match
        for route in self.routes:
            kwargs = route.match(request.method, path)
            if kwargs is not None:
                return route.handler, kwargs

        # Try without trailing slash
        if path != "/" and path.endswith("/"):
            for route in self.routes:
                kwargs = route.match(request.method, path.rstrip("/"))
                if kwargs is not None:
                    return route.handler, kwargs

        # Second pass: is it a path match with wrong method?
        for route in self.routes:
            # Try to match any method
            for method in ("GET", "POST", "PUT", "DELETE"):
                kwargs = route.match(method, path)
                if kwargs is not None:
                    # Path exists but method doesn't
                    request._method_not_allowed = True
                    return None, {}

        return None, {}

    def get_not_found_handler(self) -> Optional[Callable]:
        return self._not_found_handler

    def __len__(self) -> int:
        return len(self.routes)

    def __repr__(self) -> str:
        return f"<Router with {len(self.routes)} routes>"