from __future__ import annotations

import json
import struct
from typing import Any


MAX_FRAME_SIZE = 2 * 1024 * 1024


def encode_frame(message: dict[str, Any]) -> bytes:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_FRAME_SIZE:
        raise ValueError("frame too large")
    return struct.pack(">I", len(payload)) + payload


def decode_frames(buffer: bytearray) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    while True:
        if len(buffer) < 4:
            return out
        (n,) = struct.unpack(">I", buffer[:4])
        if n <= 0 or n > MAX_FRAME_SIZE:
            raise ValueError("invalid frame size")
        if len(buffer) < 4 + n:
            return out
        payload = bytes(buffer[4 : 4 + n])
        del buffer[: 4 + n]
        msg = json.loads(payload.decode("utf-8"))
        if not isinstance(msg, dict):
            raise ValueError("invalid message")
        out.append(msg)


class ProtocolError(Exception):
    pass

