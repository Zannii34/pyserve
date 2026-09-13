# PyServe

![Python](https://img.shields.io/badge/python-3.11-blue) ![License](https://img.shields.io/badge/license-MIT-green) ![Tests](https://img.shields.io/badge/tests-20%20passed-brightgreen)


**A web server built from scratch in Python.** No Flask, no Django, no frameworks - just socket, threading, and the standard library.

## Live Demo

**Try it:** https://pyserve.fly.dev

## Features

- **Raw TCP sockets** - accepts connections on a listening socket
- **Thread pool** - handles concurrent requests
- **HTTP/1.1 parser** - request line, headers, body
- **Keep-alive** - persistent connections
- **Decorator-based routing** - @router.get("/path") like Flask
- **Middleware chain** - logging, CORS, rate limiting, compression, caching
- **Static file serving** - with correct MIME types
- **Path traversal protection** - blocks ../ attacks
- **Rate limiting** - token bucket per IP
- **Gzip compression** - auto-compresses text responses
- **ETag caching** - 304 Not Modified support
- **Colored access logs** - with timing, status, user agent
- **Live stats** - /stats endpoint with uptime, RPS, p95/p99
- **CLI tool** - pyserve --port 8000 --workers 8
- **Graceful shutdown** - Ctrl+C waits for active connections
- **Docker support** - docker build and docker-compose up
- **Fly.io ready** - deployed via Dockerfile

## Quick Start

Install with pip:

    pip install -e ".[yaml]"

Serve the demo public folder:

    pyserve --static examples/public

Custom port and workers:

    pyserve --port 3000 --workers 16

Or via Docker:

    docker-compose up

## Demo Endpoints

- / - demo page
- /api/ping - health check
- /api/time - current server time
- /api/echo - echoes your request
- /api/users/42 - path parameter demo
- /stats - live server metrics

## Architecture

    TCP Socket -> Thread Pool -> Parser -> Middleware -> Router -> Response -> Log

## Project Structure

    pyserve/
    |-- pyserve/          # 12 modules
    |-- tests/            # pytest suite
    |-- benchmarks/       # load test
    |-- examples/public/  # demo static site
    |-- Dockerfile
    |-- docker-compose.yml
    |-- pyproject.toml

## What I Learned

- HTTP/1.1 at the byte level
- Socket programming, concurrency, thread pools
- Security: path traversal, rate limiting, slowloris
- HTTP caching (ETag, Last-Modified, 304)
- Compression (gzip negotiation)
- Design patterns: middleware, decorators, factories
- Production readiness: signals, health checks, Docker

## License

MIT
