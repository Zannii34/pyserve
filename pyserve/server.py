"""PyServe main server — TCP socket listener + thread pool."""
import os
import signal
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from pyserve.parser import Request, ParseError, parse_request
from pyserve.response import Response
from pyserve.router import Router
from pyserve.middleware import MiddlewareChain
from pyserve.logger import AccessLogger, get_logger
from pyserve.security import SlowlorisDefense
from pyserve.stats import Stats  # We'll create this next

MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10 MB
SOCKET_TIMEOUT = 30  # seconds
HEADER_READ_TIMEOUT = 10  # for slowloris protection


class Server:
    """A multithreaded HTTP/1.1 server built on raw TCP sockets."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        workers: int = 8,
        router: Optional[Router] = None,
        middleware: Optional[MiddlewareChain] = None,
        logger: Optional[AccessLogger] = None,
        max_connections_per_ip: int = 20,
        ssl_cert: Optional[str] = None,
        ssl_key: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.workers = workers
        self.router = router or Router()
        self.middleware = middleware or MiddlewareChain()
        self.logger = logger or get_logger()
        self.slowloris = SlowlorisDefense(max_connections_per_ip)
        self.stats = Stats()

        # SSL setup
        self.ssl_context: Optional[ssl.SSLContext] = None
        if ssl_cert and ssl_key:
            self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.ssl_context.load_cert_chain(certfile=ssl_cert, keyfile=ssl_key)

        # Runtime state
        self._socket: Optional[socket.socket] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._shutdown_event = threading.Event()
        self._active_workers = 0
        self._workers_lock = threading.Lock()

    # ---------- Public API ----------

    def run(self, block: bool = True) -> None:
        """Start the server. If block=True, runs until interrupted."""
        self._setup_socket()
        self._setup_signal_handlers()

        self.logger.log_info(
            f"PyServe listening on "
            f"{'https' if self.ssl_context else 'http'}://{self.host}:{self.port}"
        )
        self.logger.log_info(f"Workers: {self.workers}")
        self.logger.log_info(f"Routes: {len(self.router)}")
        self.logger.log_info(f"Middleware: {len(self.middleware)}")
        self.logger.log_info("Press Ctrl+C to stop")

        if not block:
            # Non-blocking mode for testing
            self._executor = ThreadPoolExecutor(max_workers=self.workers)
            return

        self._serve_forever()

    def serve_once(self, timeout: float = 1.0) -> None:
        """Handle a single accept loop iteration (useful for tests)."""
        self._accept_loop(timeout)

    def stop(self) -> None:
        """Signal the server to shut down gracefully."""
        self.logger.log_info("Shutdown signal received")
        self._shutdown_event.set()
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass

    @property
    def address(self) -> tuple:
        return (self.host, self.port)

    # ---------- Setup ----------

    def _setup_socket(self) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, self.port))
        self._socket.listen(128)
        self._socket.settimeout(1.0)  # so we can check shutdown_event periodically

        if self.ssl_context:
            # For HTTPS, wrap the listening socket (though typically done per-connection)
            pass

    def _setup_signal_handlers(self) -> None:
        def handler(signum, frame):
            self.logger.log_info(f"Received signal {signum}")
            self.stop()

        try:
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGTERM, handler)
        except (ValueError, OSError):
            # Signal setup can fail in non-main threads (tests)
            pass

    # ---------- Main loop ----------

    def _serve_forever(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=self.workers)
        try:
            while not self._shutdown_event.is_set():
                self._accept_loop(timeout=1.0)
        except KeyboardInterrupt:
            self.logger.log_info("KeyboardInterrupt — shutting down")
        finally:
            self.logger.log_info("Waiting for active connections to finish...")
            self._executor.shutdown(wait=True, cancel_futures=False)
            if self._socket:
                try:
                    self._socket.close()
                except OSError:
                    pass
            self.logger.log_info("Server stopped")

    def _accept_loop(self, timeout: float = 1.0) -> None:
        try:
            conn, addr = self._socket.accept()
        except socket.timeout:
            return
        except OSError:
            return

        remote_ip = addr[0]

        # Slowloris defense
        if not self.slowloris.acquire(remote_ip):
            self.logger.log_error(f"Too many connections from {remote_ip} — rejecting")
            try:
                conn.close()
            except OSError:
                pass
            return

        # Hand off to worker pool
        self._executor.submit(self._handle_connection, conn, addr)

    # ---------- Connection handling ----------

    def _handle_connection(self, conn: socket.socket, addr: tuple) -> None:
        remote_ip = addr[0]
        remote_port = addr[1]
        remote_addr = f"{remote_ip}:{remote_port}"

        try:
            # Optionally wrap with SSL
            if self.ssl_context:
                try:
                    conn = self.ssl_context.wrap_socket(conn, server_side=True)
                except ssl.SSLError as e:
                    self.logger.log_error(f"TLS handshake failed from {remote_addr}: {e}")
                    return

            conn.settimeout(SOCKET_TIMEOUT)

            with self._workers_lock:
                self._active_workers += 1

            keep_alive = True
            while keep_alive and not self._shutdown_event.is_set():
                keep_alive = self._handle_single_request(conn, remote_addr)

        except socket.timeout:
            pass
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            self.logger.log_error(f"Unexpected error with {remote_addr}: {e}")
        finally:
            with self._workers_lock:
                self._active_workers -= 1
            try:
                conn.close()
            except OSError:
                pass
            self.slowloris.release(remote_ip)
            self.stats.connection_closed()

    def _handle_single_request(self, conn: socket.socket, remote_addr: str) -> bool:
        """Read one request, dispatch, send response. Return True if keep-alive."""
        start_time = time.time()
        self.stats.request_started()

        try:
            # Read headers first
            conn.settimeout(HEADER_READ_TIMEOUT)
            raw = self._read_request(conn)
        except socket.timeout:
            # Slow client — send 408
            try:
                resp = Response.text("Request Timeout", status=408)
                conn.sendall(resp.to_bytes(keep_alive=False))
            except OSError:
                pass
            return False

        if not raw:
            return False

        try:
            request = parse_request(raw, remote_addr)
        except ParseError as e:
            self.logger.log_error(f"Parse error from {remote_addr}: {e}")
            try:
                resp = Response.text(f"Bad Request: {e}", status=e.status_code)
                conn.sendall(resp.to_bytes(keep_alive=False))
            except OSError:
                pass
            self.stats.request_finished(400, 0)
            return False

        # Run before middlewares
        before_resp = self.middleware.run_before(request)
        if before_resp is not None:
            response = before_resp
        else:
            # Dispatch to router
            handler, kwargs = self.router.dispatch(request)
            if handler is None:
                # Check if path exists but method doesn't match
                if getattr(request, "_method_not_allowed", False):
                    response = Response.text("Method Not Allowed", status=405)
                    response.set_header("Allow", "GET, POST, PUT, DELETE")
                else:
                    not_found = self.router.get_not_found_handler()
                    if not_found:
                        response = not_found(request, **kwargs)
                    else:
                        response = Response.not_found()
            else:
                try:
                    response = handler(request, **kwargs)
                    if not isinstance(response, Response):
                        response = Response.text(str(response))
                except Exception as e:
                    self.logger.log_error(f"Handler raised: {e}")
                    import traceback
                    traceback.print_exc()
                    response = Response.server_error(str(e))

        # Run after middlewares (reverse order)
        response = self.middleware.run_after(request, response)

        # Send it
        keep_alive = request.wants_keep_alive
        try:
            conn.sendall(response.to_bytes(keep_alive=keep_alive))
        except (BrokenPipeError, ConnectionResetError):
            return False

        # Stats + logging
        duration_ms = (time.time() - start_time) * 1000
        self.stats.request_finished(response.status, duration_ms)
        self.logger.log(request, response, duration_ms)

        return keep_alive

    def _read_request(self, conn: socket.socket) -> bytes:
        """Read until we have headers + full body (per Content-Length)."""
        buf = b""

        # Read headers (up to \r\n\r\n)
        while b"\r\n\r\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return buf  # client closed
            buf += chunk
            if len(buf) > MAX_REQUEST_SIZE:
                raise ParseError("Headers too large", status_code=413)

        header_bytes, _, body_so_far = buf.partition(b"\r\n\r\n")

        # Parse Content-Length
        content_length = 0
        for line in header_bytes.decode("iso-8859-1", errors="replace").split("\r\n"):
            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    content_length = 0
                break

        # Read remaining body
        while len(body_so_far) < content_length:
            chunk = conn.recv(min(4096, content_length - len(body_so_far)))
            if not chunk:
                break
            body_so_far += chunk

        return header_bytes + b"\r\n\r\n" + body_so_far