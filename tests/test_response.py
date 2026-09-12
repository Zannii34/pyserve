"""Tests for pyserve.response."""
from pyserve.response import Response, guess_content_type, http_date


def test_response_text():
    r = Response.text("Hello")
    assert r.status == 200
    assert r.body == b"Hello"
    assert r.get_header("Content-Type") == "text/plain; charset=utf-8"


def test_response_json():
    r = Response.json({"a": 1, "b": "two"})
    assert r.status == 200
    assert b'"a": 1' in r.body
    assert "application/json" in r.get_header("Content-Type")


def test_response_not_found():
    r = Response.not_found()
    assert r.status == 404


def test_to_bytes_structure():
    r = Response.text("OK")
    raw = r.to_bytes(keep_alive=True)
    assert raw.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b"Content-Type: text/plain" in raw
    assert b"Content-Length: 2" in raw
    assert raw.endswith(b"OK")


def test_to_bytes_keep_alive_header():
    r = Response.text("x")
    keep = r.to_bytes(keep_alive=True)
    assert b"Connection: keep-alive" in keep

    close = r.to_bytes(keep_alive=False)
    assert b"Connection: close" in close


def test_guess_content_type():
    assert "text/html" in guess_content_type("index.html")
    assert "text/css" in guess_content_type("style.css")
    assert "javascript" in guess_content_type("app.js")
    assert "json" in guess_content_type("data.json")


def test_set_get_header():
    r = Response.text("x")
    r.set_header("X-Custom", "value")
    assert r.get_header("X-Custom") == "value"
    assert r.get_header("x-custom") == "value"  # case insensitive