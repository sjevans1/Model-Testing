#!/usr/bin/env python3
"""Minimal Chrome DevTools Protocol client over a raw WebSocket (stdlib only).

Only what the benchmark needs: connect, open a target, evaluate JS (with awaitPromise),
query/set device metrics. No third-party libraries are installed in this environment.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import time
from typing import Any, Optional


class CDPError(RuntimeError):
    pass


class CDP:
    def __init__(self, host: str = "127.0.0.1", port: int = 9222, timeout: float = 20.0,
                 path: Optional[str] = None) -> None:
        if path is None:
            path = self._discover_path(host, port)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise CDPError("websocket handshake failed")
            buf += chunk
        if b"101" not in buf.split(b"\r\n")[0]:
            raise CDPError(f"handshake rejected: {buf.split(chr(13).encode())[0]!r}")
        self._id = 0
        self._buf = buf.split(b"\r\n\r\n", 1)[1]
        self.events: list[dict] = []

    # -- framing -------------------------------------------------------------------
    @staticmethod
    def _discover_path(host: str, port: int) -> str:
        """lightpanda serves the browser endpoint on /devtools/browser/<uuid>."""
        import urllib.request

        try:
            with urllib.request.urlopen(f"http://{host}:{port}/json/version", timeout=5) as fh:
                info = json.loads(fh.read().decode())
            url = info.get("webSocketDebuggerUrl") or ""
            if url.startswith("ws://"):
                return "/" + url.split("/", 3)[3]
        except Exception:  # noqa: BLE001
            pass
        return "/"

    def _send_frame(self, payload: bytes, opcode: int = 0x1) -> None:
        mask = os.urandom(4)
        header = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise CDPError("connection closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _read_frame(self) -> tuple[int, bytes]:
        b0, b1 = self._read_exact(2)
        opcode = b0 & 0x0F
        masked = b1 & 0x80
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if masked else b""
        payload = self._read_exact(length) if length else b""
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    def _recv_message(self) -> Optional[dict]:
        while True:
            opcode, payload = self._read_frame()
            if opcode == 0x8:
                raise CDPError("websocket closed by peer")
            if opcode == 0x9:
                self._send_frame(payload, opcode=0xA)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x2):
                text = payload.decode("utf-8", "replace")
                try:
                    return json.loads(text)
                except ValueError:
                    continue

    # -- protocol ------------------------------------------------------------------
    def call(self, method: str, session_id: Optional[str] = None, timeout: float = 30.0,
             **params: Any) -> dict:
        self._id += 1
        msg: dict[str, Any] = {"id": self._id, "method": method, "params": params}
        if session_id:
            msg["sessionId"] = session_id
        self._send_frame(json.dumps(msg).encode())
        deadline = time.time() + timeout
        while time.time() < deadline:
            reply = self._recv_message()
            if reply is None:
                continue
            if reply.get("id") == self._id:
                if "error" in reply:
                    raise CDPError(f"{method}: {reply['error']}")
                return reply.get("result", {})
            if reply.get("method"):
                self.events.append(reply)
        raise CDPError(f"{method}: no reply within {timeout}s")

    def open_page(self, url: str) -> str:
        target = self.call("Target.createTarget", url=url)
        target_id = target["targetId"]
        attached = self.call("Target.attachToTarget", targetId=target_id, flatten=True)
        session = attached["sessionId"]
        for _ in range(40):
            if any(e.get("method") in ("Page.loadEventFired", "Page.frameStoppedLoading")
                   for e in self.events):
                break
            try:
                self._recv_message()
            except socket.timeout:
                break
        return session

    def eval(self, session: str, expression: str, await_promise: bool = True,
             timeout: float = 30.0) -> Any:
        res = self.call(
            "Runtime.evaluate", session_id=session, timeout=timeout,
            expression=expression, awaitPromise=await_promise, returnByValue=True,
        )
        if res.get("exceptionDetails"):
            detail = res["exceptionDetails"]
            raise CDPError(f"JS error: {detail.get('exception', {}).get('description') or detail}")
        result = res.get("result", {})
        if result.get("type") == "undefined":
            return None
        return result.get("value")

    def close(self) -> None:
        try:
            self._send_frame(b"", opcode=0x8)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.sock.close()
        except Exception:  # noqa: BLE001
            pass
