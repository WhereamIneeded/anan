"""离线验证图片编辑协议、有限读取和敏感信息隔离。"""

import base64
import importlib
import io
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
from urllib.error import HTTPError, URLError

import pytest
from PIL import Image


SECRET = "sk-offline-secret-do-not-store"


def api():
    return importlib.import_module("anan_pet.image_service")


def png():
    stream = io.BytesIO()
    Image.new("RGBA", (2, 2), (30, 50, 60, 100)).save(stream, "PNG")
    return stream.getvalue()


class Response(io.BytesIO):
    status = 200
    headers = {"x-request-id": "req_offline_123"}


def response(**extra):
    return Response(json.dumps({"data": [{"b64_json": base64.b64encode(png()).decode()}], **extra}).encode())


def test_edit_sends_fixed_json_contract_and_multiple_references():
    calls = []

    def transport(request, timeout):
        calls.append((request, timeout))
        return response(usage={"total_tokens": 5, "input_tokens": 3,
                               "input_tokens_details": {"image_tokens": 2, "text_tokens": 1, "secret": SECRET},
                               "secret": SECRET})

    result = api().ImageService(SECRET, transport).edit("中文角色说明", [png(), png()])
    request, timeout = calls[0]
    assert request.full_url == "https://api.openai.com/v1/images/edits"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer " + SECRET
    body = json.loads(request.data)
    assert body == {"model": "gpt-image-2.5-sunburst-2026-09-08", "prompt": "中文角色说明",
                    "images": [{"image_url": "data:image/png;base64," + base64.b64encode(png()).decode()}] * 2,
                    "background": "transparent", "output_format": "png", "quality": "high",
                    "size": "1024x1024", "n": 1}
    assert 0 < timeout <= 180
    assert len(calls) == 1 and result.png == png()
    assert result.request_id == "req_offline_123"
    assert result.usage == {"total_tokens": 5, "input_tokens": 3,
                            "input_tokens_details": {"image_tokens": 2, "text_tokens": 1}}


@pytest.mark.parametrize("error", [socket.timeout(SECRET), URLError(SECRET),
    IncompleteRead(SECRET.encode()),
    HTTPError("https://api.openai.com", 401, SECRET, {}, io.BytesIO(SECRET.encode())),
    HTTPError("https://api.openai.com", 503, SECRET, {}, io.BytesIO(SECRET.encode()))])
def test_remote_errors_are_sanitized_and_never_retried(error):
    calls = []

    def fail(*args):
        calls.append(args)
        raise error

    with pytest.raises(api().ServiceError) as caught:
        api().ImageService(SECRET, fail).edit("提示", [png()])
    assert len(calls) == 1
    assert SECRET not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("payload", [b"broken", b"{}", b'{"data": []}',
    b'{"data":[{"b64_json":"bad"}]}', b'{"data":[{"url":"https://example.com"}]}',
    b'{"data":[{"b64_json":"c2VjcmV0"}]}'])
def test_malformed_responses_are_rejected_without_remote_text(payload):
    with pytest.raises(api().ServiceError) as caught:
        api().ImageService(SECRET, lambda *_: Response(payload)).edit("提示", [png()])
    assert caught.value.uncertain and SECRET not in str(caught.value)


def test_response_size_is_bounded_and_redirect_is_rejected():
    class Oversize(Response):
        def read(self, size=-1):
            assert 0 < size <= api().MAX_RESPONSE_BYTES + 1
            return b"x" * size

    with pytest.raises(api().ServiceError, match="过大"):
        api().ImageService(SECRET, lambda *_: Oversize()).edit("提示", [png()])
    redirected = Response(b"")
    redirected.status = 302
    with pytest.raises(api().ServiceError, match="重定向"):
        api().ImageService(SECRET, lambda *_: redirected).edit("提示", [png()])
    handler = api().NoRedirect()
    assert handler.redirect_request(None, None, 302, "", {}, "https://example.com") is None


def test_default_opener_disables_redirects(monkeypatch):
    import urllib.request

    handlers = []

    class Opener:
        def open(self, request, data=None, timeout=None):
            assert data is None, "超时必须按关键字传给 urllib，不能覆盖请求正文"
            assert 0 < timeout <= 180
            return response()

    def build(*items):
        handlers.extend(items)
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build)
    api().ImageService(SECRET).edit("提示", [png()])
    assert any(isinstance(item, api().NoRedirect) for item in handlers)


def test_usage_and_request_id_only_keep_safe_known_fields():
    item = response(usage={"total_tokens": True, "input_tokens": -1, "output_tokens": float("inf"),
                           "input_tokens_details": {"image_tokens": 4, "text_tokens": "4"}})
    item.headers = {"x-request-id": SECRET + "\n"}
    result = api().ImageService(SECRET, lambda *_: item).edit("提示", [png()])
    assert result.usage == {"input_tokens_details": {"image_tokens": 4}}
    assert result.request_id is None


def test_empty_key_is_rejected_before_transport():
    with pytest.raises(api().ServiceError, match="密钥"):
        api().ImageService(" ", lambda *_: pytest.fail("不应调用网络"))


def test_request_id_echoing_key_is_not_returned():
    item = response()
    item.headers = {"x-request-id": "req_" + SECRET}
    assert api().ImageService(SECRET, lambda *_: item).edit("提示", [png()]).request_id is None


def test_default_transport_uses_real_local_http_and_blocks_redirect(monkeypatch):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append((self.path, self.headers.get("Authorization"),
                          self.rfile.read(int(self.headers["Content-Length"]))))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/leak")
                self.end_headers()
                return
            if self.path == "/timeout":
                threading.Event().wait(0.15)
            body = json.dumps({"data": [{"b64_json": base64.b64encode(png()).decode()}]}).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_GET(self):
            calls.append((self.path, self.headers.get("Authorization"), b""))
            self.send_response(500)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = f"http://127.0.0.1:{server.server_port}"
    try:
        monkeypatch.setattr(api(), "ENDPOINT", host + "/edit")
        result = api().ImageService(SECRET).edit("真实本地协议", [png()])
        assert result.png == png()
        assert calls[0][1] == "Bearer " + SECRET
        assert json.loads(calls[0][2])["prompt"] == "真实本地协议"
        monkeypatch.setattr(api(), "ENDPOINT", host + "/redirect")
        with pytest.raises(api().ServiceError, match="重定向"):
            api().ImageService(SECRET).edit("提示", [png()])
        assert [item[0] for item in calls] == ["/edit", "/redirect"]
        monkeypatch.setattr(api(), "ENDPOINT", host + "/timeout")
        monkeypatch.setattr(api(), "TIMEOUT_SECONDS", 0.03)
        with pytest.raises(api().ServiceError, match="超时"):
            api().ImageService(SECRET).edit("提示", [png()])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
