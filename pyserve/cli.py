"""PyServe CLI — command-line entry point."""
import argparse
import sys
import signal
from pathlib import Path

from pyserve import __version__
from pyserve.config import load_config
from pyserve.server import Server
from pyserve.router import Router
from pyserve.response import Response
from pyserve.handlers import StaticFileHandler
from pyserve.middleware import MiddlewareChain, CorsMiddleware, SecurityHeadersMiddleware
from pyserve.security import RateLimitMiddleware, RequestSizeLimitMiddleware, UserAgentBlockMiddleware
from pyserve.compression import CompressionMiddleware, CacheMiddleware
from pyserve.logger import AccessLogger


BANNER = r"""
  ___       ____
 | _ \_  _ / __| ___ _ ___ _____
 |  _/ || |\__ \/ -_) '_\ V / -_)
 |_|  \_, |___/\___|_|  \_/\___|
      |__/
"""


def build_router(static_root: str) -> Router:
    """Create a demo router with a static handler + built-in routes."""
    router = Router()
    static = StaticFileHandler(static_root)

    # --- API endpoints ---

    @router.get("/api/ping")
    def ping(request):
        return Response.json({"message": "pong", "server": "PyServe"})

    @router.get("/api/time")
    def time_endpoint(request):
        from datetime import datetime, timezone
        return Response.json({
            "utc": datetime.now(timezone.utc).isoformat(),
            "unix": datetime.now(timezone.utc).timestamp(),
        })

    @router.get("/api/echo")
    def echo(request):
        return Response.json({
            "method": request.method,
            "path": request.path,
            "query": request.query,
            "headers": dict(request.headers),
        })

    @router.post("/api/echo")
    def echo_post(request):
        return Response.json({
            "method": "POST",
            "body_size": len(request.body),
            "body_preview": request.body[:500].decode("utf-8", errors="replace"),
            "content_type": request.content_type,
        })

    @router.get("/api/users/<int:user_id>")
    def get_user(request, user_id):
        return Response.json({"id": user_id, "name": f"User {user_id}"})

    # --- Stats dashboard ---

    @router.get("/stats")
    def stats_endpoint(request):
        snap = server_ref["server"].stats.snapshot()
        return Response.json(snap)

    # --- Static file fallback ---

    @router.get("/<path:filepath>")
    def serve_static(request, filepath):
        return static.handle(request, "/" + filepath)

    @router.get("/")
    def home(request):
        return static.handle(request, "/")

    return router


# Reference to server, filled in by main()
server_ref = {}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pyserve",
        description="A web server built from scratch in Python.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  pyserve                          # serve ./public on port 8000
  pyserve --port 3000              # custom port
  pyserve --workers 16             # more threads
  pyserve --static ./dist          # custom static folder
  pyserve --config pyserve.yml     # use config file
  pyserve --ssl-cert cert.pem --ssl-key key.pem   # HTTPS
""",
    )
    parser.add_argument("--host", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", "-p", type=int, help="Port to bind (default: 8000)")
    parser.add_argument("--workers", "-w", type=int, help="Number of worker threads (default: 8)")
    parser.add_argument("--static", "-s", help="Static files folder (default: ./public)")
    parser.add_argument("--config", "-c", help="Path to YAML config file")
    parser.add_argument("--log-file", help="Write access logs to file")
    parser.add_argument("--ssl-cert", help="Path to SSL certificate (enables HTTPS)")
    parser.add_argument("--ssl-key", help="Path to SSL private key")
    parser.add_argument("--no-cors", action="store_true", help="Disable CORS headers")
    parser.add_argument("--no-compression", action="store_true", help="Disable gzip compression")
    parser.add_argument("--no-rate-limit", action="store_true", help="Disable rate limiting")
    parser.add_argument("--no-color", action="store_true", help="Disable colored terminal output")
    parser.add_argument("--version", "-v", action="version", version=f"PyServe {__version__}")
    args = parser.parse_args(argv)

    # Load config
    config = load_config(args.config)

    # CLI args override config
    if args.host:
        config["host"] = args.host
    if args.port:
        config["port"] = args.port
    if args.workers:
        config["workers"] = args.workers
    if args.static:
        config["static_root"] = args.static
    if args.log_file:
        config["log_file"] = args.log_file
    if args.ssl_cert:
        config["ssl"]["cert"] = args.ssl_cert
    if args.ssl_key:
        config["ssl"]["key"] = args.ssl_key
    if args.no_cors:
        config["cors"]["enabled"] = False
    if args.no_compression:
        config["compression"]["enabled"] = False
    if args.no_rate_limit:
        config["rate_limit"]["enabled"] = False

    # Check static root exists
    static_root = config["static_root"]
    if not Path(static_root).exists():
        print(f"[WARN] Static folder '{static_root}' doesn't exist — creating it")
        Path(static_root).mkdir(parents=True, exist_ok=True)
        Path(static_root, "index.html").write_text(
            "<!DOCTYPE html><html><head><title>PyServe</title></head>"
            "<body><h1>PyServe is running!</h1>"
            "<p>Edit <code>public/index.html</code> to customize.</p>"
            "<p><a href='/stats'>Server stats</a> · "
            "<a href='/api/ping'>API ping</a></p></body></html>",
            encoding="utf-8",
        )

    # Logger
    logger = AccessLogger(
        file_path=config.get("log_file"),
        use_color=not args.no_color,
    )

    # Router
    router = build_router(static_root)

    # Middleware chain
    middleware = MiddlewareChain()
    middleware.add_function(
        after_fn=lambda req, resp: resp  # placeholder hook
    )

    # Security first
    middleware.add(RequestSizeLimitMiddleware(max_bytes=10 * 1024 * 1024))
    middleware.add(UserAgentBlockMiddleware())
    if config["rate_limit"]["enabled"]:
        middleware.add(RateLimitMiddleware(
            rate=config["rate_limit"]["rate"],
            per=config["rate_limit"]["per"],
            burst=config["rate_limit"]["burst"],
        ))

    # CORS
    if config["cors"]["enabled"]:
        middleware.add(CorsMiddleware(origin=config["cors"]["origin"]))

    # Security headers
    middleware.add(SecurityHeadersMiddleware())

    # Compression + caching
    if config["compression"]["enabled"]:
        middleware.add(CompressionMiddleware(min_size=config["compression"]["min_size"]))
    middleware.add(CacheMiddleware())

    # Server
    server = Server(
        host=config["host"],
        port=config["port"],
        workers=config["workers"],
        router=router,
        middleware=middleware,
        logger=logger,
        max_connections_per_ip=config["max_connections_per_ip"],
        ssl_cert=config["ssl"].get("cert"),
        ssl_key=config["ssl"].get("key"),
    )
    server_ref["server"] = server

    print(BANNER)
    try:
        server.run()
    except KeyboardInterrupt:
        print("\nShutdown requested")
    return 0


if __name__ == "__main__":
    sys.exit(main())