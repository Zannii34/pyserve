"""Tests for pyserve.router."""
import pytest
from pyserve.router import Router
from pyserve.parser import Request


def test_basic_route():
    r = Router()

    @r.get("/hello")
    def hello(req):
        return "hi"

    handler, kwargs = r.dispatch(Request(method="GET", path="/hello"))
    assert handler is not None
    assert kwargs == {}


def test_path_param_int():
    r = Router()

    @r.get("/users/<int:user_id>")
    def get_user(req, user_id):
        return user_id

    handler, kwargs = r.dispatch(Request(method="GET", path="/users/42"))
    assert handler is not None
    assert kwargs == {"user_id": 42}


def test_path_param_str():
    r = Router()

    @r.get("/posts/<slug>")
    def get_post(req, slug):
        return slug

    handler, kwargs = r.dispatch(Request(method="GET", path="/posts/hello-world"))
    assert kwargs == {"slug": "hello-world"}


def test_path_param_path():
    r = Router()

    @r.get("/files/<path:filepath>")
    def serve(req, filepath):
        return filepath

    handler, kwargs = r.dispatch(Request(method="GET", path="/files/css/style.css"))
    assert kwargs == {"filepath": "css/style.css"}


def test_method_mismatch():
    r = Router()

    @r.get("/only-get")
    def only_get(req):
        return "ok"

    handler, _ = r.dispatch(Request(method="POST", path="/only-get"))
    assert handler is None


def test_not_found():
    r = Router()
    handler, _ = r.dispatch(Request(method="GET", path="/missing"))
    assert handler is None


def test_route_count():
    r = Router()

    @r.get("/a")
    def a(req):
        return "a"

    @r.post("/b")
    def b(req):
        return "b"

    assert len(r) == 2