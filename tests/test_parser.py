"""Tests for pyserve.parser."""
import pytest
from pyserve.parser import Request, parse_request, ParseError


def test_parse_simple_get():
    raw = b"GET /hello HTTP/1.1\r\nHost: localhost\r\n\r\n"
    req = parse_request(raw, remote_addr="127.0.0.1")
    assert req.method == "GET"
    assert req.path == "/hello"
    assert req.http_version == "HTTP/1.1"
    assert req.headers["host"] == "localhost"
    assert req.remote_addr == "127.0.0.1"


def test_parse_query_string():
    raw = b"GET /search?q=hello&page=2 HTTP/1.1\r\nHost: x\r\n\r\n"
    req = parse_request(raw)
    assert req.path == "/search"
    assert req.query["q"] == ["hello"]
    assert req.query["page"] == ["2"]


def test_parse_post_with_body():
    body = b'{"hello": "world"}'
    raw = b"POST /api HTTP/1.1\r\nHost: x\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    req = parse_request(raw)
    assert req.method == "POST"
    assert req.body == body
    assert req.content_length == len(body)


def test_empty_request_raises():
    with pytest.raises(ParseError):
        parse_request(b"")


def test_invalid_request_line_raises():
    with pytest.raises(ParseError):
        parse_request(b"INVALID\r\nHost: x\r\n\r\n")


def test_keep_alive_detection():
    req1 = parse_request(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
    assert req1.wants_keep_alive is True

    req2 = parse_request(b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
    assert req2.wants_keep_alive is False

    req3 = parse_request(b"GET / HTTP/1.0\r\nHost: x\r\n\r\n")
    assert req3.wants_keep_alive is False

    req4 = parse_request(b"GET / HTTP/1.0\r\nHost: x\r\nConnection: keep-alive\r\n\r\n")
    assert req4.wants_keep_alive is True