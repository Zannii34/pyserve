"""Simple load test for PyServe. No external deps."""
import sys
import time
import socket
import threading
from collections import defaultdict


def make_request(host, port, path="/", method="GET"):
    """Make a single HTTP request, return status code."""
    try:
        with socket.create_connection((host, port), timeout=5) as s:
            req = f"{method} {path} HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n"
            s.sendall(req.encode())
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            if not data:
                return 0
            first_line = data.split(b"\r\n", 1)[0].decode()
            parts = first_line.split()
            if len(parts) >= 2:
                return int(parts[1])
            return 0
    except Exception:
        return 0


def worker(host, port, path, duration, results, lock):
    """Run requests for `duration` seconds, record status codes."""
    start = time.time()
    count = 0
    times = []
    while time.time() - start < duration:
        t0 = time.perf_counter()
        status = make_request(host, port, path)
        elapsed = time.perf_counter() - t0
        times.append(elapsed)
        count += 1
    with lock:
        results["total"] += count
        results["times"].extend(times)


def main():
    host = "127.0.0.1"
    port = 8000
    path = "/"
    duration = 10
    concurrency = 10

    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    if len(sys.argv) > 2:
        path = sys.argv[2]
    if len(sys.argv) > 3:
        duration = int(sys.argv[3])
    if len(sys.argv) > 4:
        concurrency = int(sys.argv[4])

    print(f"\n=== PyServe Benchmark ===")
    print(f"  URL:         http://{host}:{port}{path}")
    print(f"  Duration:    {duration}s")
    print(f"  Concurrency: {concurrency} threads")
    print(f"  Starting...\n")

    results = {"total": 0, "times": []}
    lock = threading.Lock()
    threads = [
        threading.Thread(target=worker, args=(host, port, path, duration, results, lock))
        for _ in range(concurrency)
    ]

    start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - start

    total = results["total"]
    times = results["times"]

    print(f"=== Results ===")
    print(f"  Total requests:  {total}")
    print(f"  Duration:        {elapsed:.2f}s")
    print(f"  Requests/sec:    {total / elapsed:.1f}")

    if times:
        times.sort()
        print(f"  Avg latency:     {sum(times) / len(times) * 1000:.2f}ms")
        print(f"  p50 latency:     {times[len(times) // 2] * 1000:.2f}ms")
        print(f"  p95 latency:     {times[int(len(times) * 0.95)] * 1000:.2f}ms")
        print(f"  p99 latency:     {times[int(len(times) * 0.99)] * 1000:.2f}ms")
        print(f"  Fastest:         {times[0] * 1000:.2f}ms")
        print(f"  Slowest:         {times[-1] * 1000:.2f}ms")


if __name__ == "__main__":
    main()