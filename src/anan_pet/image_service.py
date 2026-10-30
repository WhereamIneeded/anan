"""只发送一次图片编辑请求，并隔离远端错误及密钥。"""

import base64
import binascii
from dataclasses import dataclass
from http.client import HTTPException
import json
import re
import socket
from urllib import error, request


MODEL = "gpt-image-2.5-sunburst-2026-09-08"
ENDPOINT = "https://api.openai.com/v1/images/edits"
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
TIMEOUT_SECONDS = 180
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ServiceError(Exception):
    """可以安全展示给用户的固定中文错误。"""

    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


@dataclass(frozen=True)
class ImageResult:
    png: bytes
    usage: dict
    request_id: str | None


class NoRedirect(request.HTTPRedirectHandler):
    """拒绝转发携带授权的请求。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def safe_usage(value):
    """仅保留已知、非负的整数用量，不保存任意远端字段。"""
    if not isinstance(value, dict):
        return {}
    result = {name: value[name] for name in ("total_tokens", "input_tokens", "output_tokens")
              if type(value.get(name)) is int and value[name] >= 0}
    for name in ("input_tokens_details", "output_tokens_details"):
        detail = value.get(name)
        if isinstance(detail, dict):
            clean = {key: detail[key] for key in ("image_tokens", "text_tokens", "cached_tokens")
                     if type(detail.get(key)) is int and detail[key] >= 0}
            if clean:
                result[name] = clean
    return result


class ImageService:
    def __init__(self, key, transport=None):
        if not isinstance(key, str) or not key.strip() or any(c in key for c in "\r\n"):
            raise ServiceError("请提供有效的 OpenAI 密钥。")
        self._key = key.strip()
        if transport is None:
            opener = request.build_opener(NoRedirect())
            self._transport = lambda req, timeout: opener.open(req, timeout=timeout)
        else:
            self._transport = transport

    def edit(self, prompt, images):
        if not isinstance(prompt, str) or not prompt or not images or len(images) > 3:
            raise ServiceError("图片编辑输入无效。")
        if any(not isinstance(item, bytes) or not item.startswith(PNG_SIGNATURE) for item in images):
            raise ServiceError("参考图片必须是 PNG。")
        if sum(map(len, images)) > 30 * 1024 * 1024:
            raise ServiceError("参考图片总大小过大。")
        payload = {"model": MODEL, "prompt": prompt,
                   "images": [{"image_url": "data:image/png;base64," + base64.b64encode(item).decode("ascii")}
                              for item in images],
                   "background": "transparent", "output_format": "png", "quality": "high",
                   "size": "1024x1024", "n": 1}
        req = request.Request(ENDPOINT, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                              {"Authorization": "Bearer " + self._key, "Content-Type": "application/json"},
                              method="POST")
        try:
            with self._transport(req, TIMEOUT_SECONDS) as response:
                if 300 <= response.status < 400:
                    raise ServiceError("服务返回重定向，已停止请求。", uncertain=True)
                if response.status != 200:
                    raise ServiceError("图片服务拒绝请求，请检查账户与服务状态。", uncertain=True)
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ServiceError("服务响应过大，结果未确认。", uncertain=True)
                request_id = response.headers.get("x-request-id")
        except error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise ServiceError("服务返回重定向，已停止请求。", uncertain=True) from None
            raise ServiceError("图片服务拒绝请求，请检查密钥、账户额度与服务状态。",
                               uncertain=exc.code >= 500 or exc.code == 408) from None
        except (socket.timeout, TimeoutError):
            raise ServiceError("图片请求超时，结果未确认；请先检查账户用量。", uncertain=True) from None
        except (error.URLError, OSError, ValueError, HTTPException):
            raise ServiceError("图片请求连接中断，结果未确认；请先检查账户用量。", uncertain=True) from None
        try:
            value = json.loads(raw)
            data = value["data"]
            if not isinstance(data, list) or len(data) != 1:
                raise ValueError
            png = base64.b64decode(data[0]["b64_json"], validate=True)
            if not png.startswith(PNG_SIGNATURE):
                raise ValueError
        except (ValueError, KeyError, TypeError, IndexError, binascii.Error, UnicodeError):
            raise ServiceError("图片服务响应格式无效，结果未确认。", uncertain=True) from None
        safe_id = (request_id if isinstance(request_id, str) and self._key not in request_id
                   and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id) else None)
        return ImageResult(png, safe_usage(value.get("usage")), safe_id)
