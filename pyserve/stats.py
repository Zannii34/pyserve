"""Runtime statistics — track requests, timing, and connections."""
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone


class Stats:
    """Thread-safe runtime statistics."""

    def __init__(self, window_seconds: int = 60):
        self.window = window_seconds
        self.lock = threading.Lock()

        # Counters
        self.total_requests = 0
        self.total_connections = 0
        self.active_connections = 0
        self.start_time = time.time()

        # Status code counts
        self.status_counts = defaultdict(int)

        # Response times (last N)
        self.response_times = deque(maxlen=1000)

        # Requests per second — circular buffer
        self._rps_buckets = deque(maxlen=window_seconds)
        for _ in range(window_seconds):
            self._rps_buckets.append([0, time.time() // 1])

        # Per-endpoint counts
        self.endpoint_counts = defaultdict(int)

    # ---------- Request lifecycle ----------

    def request_started(self) -> None:
        with self.lock:
            self.total_requests += 1
            now = time.time()
            current_bucket = int(now) % self.window
            # Advance buckets if stale
            last_second = int(now)
            for i, bucket in enumerate(self._rps_buckets):
                if bucket[1] != last_second:
                    if int(now) - last_second < self.window:
                        self._rps_buckets[i] = [0, last_second]
            # Increment current second's bucket
            for bucket in self._rps_buckets:
                if bucket[1] == last_second:
                    bucket[0] += 1
                    break

    def request_finished(self, status: int, duration_ms: float) -> None:
        with self.lock:
            self.status_counts[status] += 1
            self.response_times.append(duration_ms)

    def track_endpoint(self, path: str) -> None:
        with self.lock:
            self.endpoint_counts[path] += 1

    # ---------- Connection lifecycle ----------

    def connection_opened(self) -> None:
        with self.lock:
            self.total_connections += 1
            self.active_connections += 1

    def connection_closed(self) -> None:
        with self.lock:
            if self.active_connections > 0:
                self.active_connections -= 1

    # ---------- Queries ----------

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.start_time

    @property
    def uptime_human(self) -> str:
        seconds = int(self.uptime_seconds)
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")
        return " ".join(parts)

    def requests_per_second(self) -> float:
        """Average RPS over the last few seconds."""
        with self.lock:
            now = int(time.time())
            # Sum counts for buckets with recent timestamps
            recent = [count for count, ts in self._rps_buckets if now - ts < 5]
            if not recent:
                return 0.0
            return sum(recent) / min(5, len(recent))

    def avg_response_time(self) -> float:
        with self.lock:
            if not self.response_times:
                return 0.0
            return sum(self.response_times) / len(self.response_times)

    def p95_response_time(self) -> float:
        with self.lock:
            if not self.response_times:
                return 0.0
            sorted_times = sorted(self.response_times)
            idx = int(len(sorted_times) * 0.95)
            return sorted_times[min(idx, len(sorted_times) - 1)]

    def p99_response_time(self) -> float:
        with self.lock:
            if not self.response_times:
                return 0.0
            sorted_times = sorted(self.response_times)
            idx = int(len(sorted_times) * 0.99)
            return sorted_times[min(idx, len(sorted_times) - 1)]

    def top_endpoints(self, n: int = 10) -> list:
        with self.lock:
            sorted_endpoints = sorted(self.endpoint_counts.items(), key=lambda x: -x[1])
            return sorted_endpoints[:n]

    def snapshot(self) -> dict:
        """Return a complete snapshot of current stats."""
        with self.lock:
            return {
                "uptime_seconds": round(self.uptime_seconds, 1),
                "uptime_human": self.uptime_human,
                "total_requests": self.total_requests,
                "total_connections": self.total_connections,
                "active_connections": self.active_connections,
                "requests_per_second": round(self.requests_per_second(), 2),
                "avg_response_ms": round(self.avg_response_time(), 2),
                "p95_response_ms": round(self.p95_response_time(), 2),
                "p99_response_ms": round(self.p99_response_time(), 2),
                "status_counts": dict(self.status_counts),
                "top_endpoints": [
                    {"path": path, "count": count}
                    for path, count in self.top_endpoints(10)
                ],
                "server_time": datetime.now(timezone.utc).isoformat(),
            }

    def reset(self) -> None:
        with self.lock:
            self.total_requests = 0
            self.total_connections = 0
            self.status_counts.clear()
            self.response_times.clear()
            self.endpoint_counts.clear()
            self.start_time = time.time()