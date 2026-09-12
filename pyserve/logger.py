"""Access logging — Apache-style logs with rotation and color output."""
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TextIO


# ANSI colors for terminal output
class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"


def status_color(status: int) -> str:
    if 200 <= status < 300:
        return Color.GREEN
    if 300 <= status < 400:
        return Color.CYAN
    if 400 <= status < 500:
        return Color.YELLOW
    return Color.RED


def method_color(method: str) -> str:
    return {
        "GET": Color.CYAN,
        "POST": Color.GREEN,
        "PUT": Color.YELLOW,
        "DELETE": Color.RED,
        "OPTIONS": Color.DIM,
        "HEAD": Color.DIM,
    }.get(method.upper(), Color.RESET)


class AccessLogger:
    """Thread-safe access logger with optional file rotation."""

    def __init__(
        self,
        file_path: Optional[str] = None,
        use_color: bool = True,
        max_bytes: int = 10 * 1024 * 1024,  # 10 MB
        keep_files: int = 5,
        stream: Optional[TextIO] = None,
    ):
        self.file_path = Path(file_path) if file_path else None
        self.use_color = use_color and stream is None  # No color for custom streams
        self.stream = stream if stream is not None else sys.stdout
        self.max_bytes = max_bytes
        self.keep_files = keep_files
        self.lock = threading.Lock()

        if self.file_path:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def _rotate_if_needed(self) -> None:
        """Rotate log file if it exceeds max_bytes."""
        if not self.file_path or not self.file_path.exists():
            return
        if self.file_path.stat().st_size < self.max_bytes:
            return

        # Shift old files: access.log.4 → access.log.5, etc.
        for i in range(self.keep_files - 1, 0, -1):
            old = self.file_path.with_suffix(self.file_path.suffix + f".{i}")
            new = self.file_path.with_suffix(self.file_path.suffix + f".{i + 1}")
            if old.exists():
                if new.exists():
                    new.unlink()
                old.rename(new)

        # Current → .1
        first_backup = self.file_path.with_suffix(self.file_path.suffix + ".1")
        if first_backup.exists():
            first_backup.unlink()
        self.file_path.rename(first_backup)

    def log(self, request, response, duration_ms: float) -> None:
        """Write one log line for a request/response pair."""
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        ip = request.remote_addr or "-"
        method = request.method
        path = request.path
        if request.query:
            from urllib.parse import urlencode
            path = path + "?" + urlencode(request.query, doseq=True)
        status = response.status
        size = len(response.body)
        ua = request.user_agent or "-"
        if len(ua) > 60:
            ua = ua[:57] + "..."

        # Colorized version (terminal)
        if self.use_color:
            colored = (
                f"{Color.DIM}{timestamp}{Color.RESET}  "
                f"{ip:15s}  "
                f"{method_color(method)}{method:6s}{Color.RESET}  "
                f"{path[:45]:45s}  "
                f"{status_color(status)}{status}{Color.RESET}  "
                f"{size:>7d}B  "
                f"{duration_ms:7.2f}ms  "
                f"{Color.DIM}{ua}{Color.RESET}"
            )
        else:
            colored = (
                f"{timestamp}  "
                f"{ip:15s}  "
                f"{method:6s}  "
                f"{path[:45]:45s}  "
                f"{status}  "
                f"{size:>7d}B  "
                f"{duration_ms:7.2f}ms  "
                f"{ua}"
            )

        # Plain version (log file)
        plain = (
            f"{timestamp}  "
            f"{ip:15s}  "
            f"{method:6s}  "
            f"{path[:80]:80s}  "
            f"{status}  "
            f"{size:>7d}B  "
            f"{duration_ms:7.2f}ms  "
            f"{ua}"
        )

        with self.lock:
            # Terminal output
            print(colored, file=self.stream, flush=True)

            # File output
            if self.file_path:
                self._rotate_if_needed()
                with open(self.file_path, "a", encoding="utf-8") as f:
                    f.write(plain + "\n")

    def log_error(self, message: str) -> None:
        """Log an error message."""
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        plain = f"{timestamp}  [ERROR]  {message}"

        with self.lock:
            if self.use_color:
                print(f"{Color.RED}{plain}{Color.RESET}", file=self.stream, flush=True)
            else:
                print(plain, file=self.stream, flush=True)

            if self.file_path:
                self._rotate_if_needed()
                with open(self.file_path, "a", encoding="utf-8") as f:
                    f.write(plain + "\n")

    def log_info(self, message: str) -> None:
        """Log an informational message."""
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        plain = f"{timestamp}  [INFO]   {message}"

        with self.lock:
            if self.use_color:
                print(f"{Color.GREEN}{plain}{Color.RESET}", file=self.stream, flush=True)
            else:
                print(plain, file=self.stream, flush=True)

            if self.file_path:
                with open(self.file_path, "a", encoding="utf-8") as f:
                    f.write(plain + "\n")


# Backwards-compatible simple API


_default_logger: Optional[AccessLogger] = None


def get_logger() -> AccessLogger:
    """Return the global logger, creating it if necessary."""
    global _default_logger
    if _default_logger is None:
        _default_logger = AccessLogger()
    return _default_logger


def set_logger(logger: AccessLogger) -> None:
    """Set the global logger."""
    global _default_logger
    _default_logger = logger