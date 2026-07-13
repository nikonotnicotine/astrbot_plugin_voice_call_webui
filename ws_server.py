"""
VoiceCall Plugin - WebUI / WebSocket 服务端

同一个端口同时提供：
- 普通 HTTP 静态文件：/、/index.html、/js/app.js 等
- WebSocket 实时通话协议：/ws
"""

import json
import logging
import mimetypes
import os
import hmac
import secrets
from pathlib import Path
from typing import Awaitable, Callable, Optional
from urllib.parse import unquote, urlsplit

from aiohttp import WSMsgType, web

logger = logging.getLogger("voice_call.ws_server")


class WsServer:
    """
    WebUI + WebSocket 服务端。

    用法:
        server = WsServer(host="127.0.0.1", port=6888, static_root=...)
        server.on_message = my_handler
        await server.start()
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 6888,
        static_root: Optional[str | Path] = None,
    ):
        self.host = host
        self.port = port
        self.static_root = Path(static_root).resolve() if static_root else None
        self.password = ""
        self._auth_cookie_name = "voicecall_auth"
        self._auth_token = secrets.token_urlsafe(32)

        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._client: Optional[web.WebSocketResponse] = None

        self._message_handler: Optional[Callable[[dict], Awaitable[None]]] = None
        self._connect_handler: Optional[Callable[[], Awaitable[None]]] = None
        self._disconnect_handler: Optional[Callable[[], Awaitable[None]]] = None
        self._running = False

    # ── 事件回调设置 ──────────────────────────────────

    @property
    def on_message(self) -> Optional[Callable]:
        return self._message_handler

    @on_message.setter
    def on_message(self, handler: Optional[Callable[[dict], Awaitable[None]]]):
        self._message_handler = handler

    @property
    def on_connect(self) -> Optional[Callable]:
        return self._connect_handler

    @on_connect.setter
    def on_connect(self, handler: Optional[Callable[[], Awaitable[None]]]):
        self._connect_handler = handler

    @property
    def on_disconnect(self) -> Optional[Callable]:
        return self._disconnect_handler

    @on_disconnect.setter
    def on_disconnect(self, handler: Optional[Callable[[], Awaitable[None]]]):
        self._disconnect_handler = handler

    # ── 服务端生命周期 ────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._client is not None and not self._client.closed

    async def start(self) -> None:
        if self._running:
            logger.warning("WebUI 服务已在运行")
            return

        self._app = web.Application(client_max_size=10 * 1024 * 1024)
        self._app.router.add_post("/auth", self._handle_auth)
        self._app.router.add_post("/logout", self._handle_logout)
        self._app.router.add_get("/ws", self._handle_ws)
        self._app.router.add_get("/{tail:.*}", self._handle_static)

        self._runner = web.AppRunner(self._app)
        try:
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, self.host, self.port)
            await self._site.start()
        except OSError as e:
            logger.error(f"无法启动 WebUI 服务 (端口 {self.port} 可能被占用): {e}")
            await self.stop()
            raise

        self._running = True
        logger.info(f"WebUI 服务已启动: http://{self.host}:{self.port}/")
        logger.info(f"WebSocket 服务已启动: ws://{self.host}:{self.port}/ws")

    async def stop(self) -> None:
        self._running = False

        if self._client and not self._client.closed:
            await self._client.close()
            self._client = None

        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            self._app = None

        logger.info("WebUI/WebSocket 服务已停止")

    # ── HTTP / WebSocket 处理 ─────────────────────────

    async def _handle_static(self, request: web.Request) -> web.Response:
        if self._auth_required() and not self._is_authenticated(request):
            return self._login_response(request)
        status, headers, body = self._serve_static_file(request.path)
        return web.Response(status=status, headers=dict(headers), body=body)

    async def _handle_ws(self, request: web.Request) -> web.StreamResponse:
        if self._auth_required() and not self._is_authenticated(request):
            return web.Response(status=401, text="Unauthorized")

        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=10 * 1024 * 1024)
        await ws.prepare(request)

        client_addr = request.remote or "unknown"
        previous_client = self._client
        # 先交接当前客户端，再关闭旧连接。否则旧连接的 finally 会把
        # “手机接管桌面网页”误判为所有客户端断开，并重置通话状态。
        self._client = ws
        if previous_client and not previous_client.closed:
            logger.info(f"新客户端 {client_addr} 连接，关闭旧连接")
            await previous_client.close()

        logger.info(f"WebUI 已连接: {client_addr}")

        if self._connect_handler:
            try:
                await self._connect_handler()
            except Exception as e:
                logger.error(f"on_connect 回调异常: {e}")

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_ws_text(msg.data)
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket 异常: {ws.exception()}")
        finally:
            is_current_client = self._client is ws
            if is_current_client:
                self._client = None
            logger.info("WebUI 已断开")

            # 被新设备接管的旧连接不应触发断线回调，否则会中断新设备上的通话。
            if is_current_client and self._disconnect_handler:
                try:
                    await self._disconnect_handler()
                except Exception as e:
                    logger.error(f"on_disconnect 回调异常: {e}")

        return ws

    async def _handle_auth(self, request: web.Request) -> web.Response:
        if not self._auth_required():
            return web.HTTPFound("/")

        password = ""
        try:
            if request.content_type == "application/json":
                payload = await request.json()
                password = str(payload.get("password", "") or "")
            else:
                payload = await request.post()
                password = str(payload.get("password", "") or "")
        except Exception:
            password = ""

        if hmac.compare_digest(password, self.password):
            response = web.HTTPFound("/")
            response.set_cookie(
                self._auth_cookie_name,
                self._auth_token,
                max_age=7 * 24 * 3600,
                httponly=True,
                samesite="Lax",
                path="/",
            )
            return response
        return web.HTTPFound("/?login_error=1")

    async def _handle_logout(self, request: web.Request) -> web.Response:
        response = web.HTTPFound("/")
        response.del_cookie(self._auth_cookie_name, path="/")
        return response

    def _auth_required(self) -> bool:
        return bool((self.password or "").strip())

    def _is_authenticated(self, request: web.Request) -> bool:
        token = request.cookies.get(self._auth_cookie_name, "")
        return bool(token) and hmac.compare_digest(token, self._auth_token)

    def _login_response(self, request: web.Request) -> web.Response:
        error_html = "<p class='error'>密码错误，请重试。</p>" if request.query.get("login_error") == "1" else ""
        body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VoiceCall 登录</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#111827;color:#f9fafb}}.login{{width:min(360px,calc(100vw - 32px));padding:28px;border:1px solid rgba(255,255,255,.12);border-radius:16px;background:rgba(31,41,55,.94);box-shadow:0 24px 80px rgba(0,0,0,.36)}}h1{{margin:0 0 8px;font-size:24px}}p{{margin:0 0 20px;color:#cbd5e1;line-height:1.5}}label{{display:block;margin-bottom:8px;color:#e5e7eb}}input{{width:100%;height:44px;border:1px solid #475569;border-radius:10px;background:#0f172a;color:#fff;padding:0 12px;font-size:16px}}button{{width:100%;height:44px;margin-top:16px;border:0;border-radius:10px;background:#22c55e;color:#052e16;font-size:16px;font-weight:700;cursor:pointer}}.error{{padding:10px 12px;border-radius:10px;background:#7f1d1d;color:#fecaca;margin-bottom:14px}}
</style>
</head>
<body>
<form class="login" method="post" action="/auth">
<h1>VoiceCall</h1>
<p>请输入访问密码后继续。</p>
{error_html}
<label for="password">访问密码</label>
<input id="password" name="password" type="password" autocomplete="current-password" autofocus>
<button type="submit">进入通话网页</button>
</form>
</body>
</html>"""
        return web.Response(text=body, content_type="text/html", charset="utf-8")

    async def _handle_ws_text(self, raw_message: str) -> None:
        try:
            data = json.loads(raw_message)
            if self._message_handler:
                await self._message_handler(data)
            else:
                logger.debug(f"收到消息但未设置 handler: {data.get('type', 'unknown')}")
        except json.JSONDecodeError as e:
            logger.warning(f"收到无效 JSON: {e}")
            await self._send_error("无效的 JSON 格式")
        except Exception as e:
            logger.error(f"消息处理异常: {e}")
            await self._send_error(str(e))

    # ── 静态文件 ──────────────────────────────────────

    def _serve_static_file(self, path: str):
        if not self.static_root:
            return self._http_response(404, "text/plain; charset=utf-8", b"WebUI not configured")

        parsed_path = urlsplit(path).path
        rel_path = unquote(parsed_path).lstrip("/")
        if not rel_path:
            rel_path = "index.html"

        candidate = (self.static_root / rel_path.replace("/", os.sep)).resolve()
        try:
            if os.path.commonpath([str(self.static_root), str(candidate)]) != str(self.static_root):
                return self._http_response(403, "text/plain; charset=utf-8", b"Forbidden")
        except ValueError:
            return self._http_response(403, "text/plain; charset=utf-8", b"Forbidden")

        if candidate.is_dir():
            candidate = candidate / "index.html"

        if not candidate.is_file():
            return self._http_response(404, "text/plain; charset=utf-8", b"Not Found")

        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        if content_type.startswith("text/") or candidate.suffix in {".js", ".json", ".svg"}:
            content_type = f"{content_type}; charset=utf-8"

        try:
            body = candidate.read_bytes()
        except OSError:
            logger.exception("读取 WebUI 静态文件失败: %s", candidate)
            return self._http_response(500, "text/plain; charset=utf-8", b"Internal Server Error")

        return self._http_response(200, content_type, body)

    @staticmethod
    def _http_response(status: int, content_type: str, body: bytes):
        return (
            status,
            [
                ("Content-Type", content_type),
                ("Cache-Control", "no-cache"),
            ],
            body,
        )

    # ── 发送消息 ──────────────────────────────────────

    async def send(self, message: dict) -> bool:
        if not self.is_connected:
            logger.warning("WebUI 未连接，无法发送消息")
            return False

        try:
            await self._client.send_str(json.dumps(message, ensure_ascii=False))
            return True
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            self._client = None
            return False

    # ── 便捷发送方法 ──────────────────────────────────

    async def send_incoming_call(self, call_id: str, message: str = "") -> bool:
        return await self.send({
            "type": "incoming_call",
            "payload": {
                "call_id": call_id,
                "message": message,
            },
        })

    async def send_call_connected(self, call_id: str) -> bool:
        return await self.send({
            "type": "call_connected",
            "payload": {
                "call_id": call_id,
            },
        })

    async def send_call_ended(self, call_id: str, reason: str = "hangup") -> bool:
        return await self.send({
            "type": "call_ended",
            "payload": {
                "call_id": call_id,
                "reason": reason,
            },
        })

    async def send_play_audio(
        self,
        call_id: str,
        audio_b64: str,
        text: str = "",
        audio_format: str = "mp3",
    ) -> bool:
        return await self.send({
            "type": "play_audio",
            "payload": {
                "call_id": call_id,
                "audio_data": audio_b64,
                "text": text,
                "format": audio_format,
            },
        })

    async def send_subtitle(self, call_id: str, speaker: str, text: str) -> bool:
        return await self.send({
            "type": "subtitle",
            "payload": {
                "call_id": call_id,
                "speaker": speaker,
                "text": text,
            },
        })

    async def send_config(self, config: dict) -> bool:
        return await self.send({
            "type": "config",
            "payload": config,
        })

    async def send_error(self, message: str) -> bool:
        return await self._send_error(message)

    async def _send_error(self, message: str) -> bool:
        return await self.send({
            "type": "error",
            "payload": {
                "message": message,
            },
        })
