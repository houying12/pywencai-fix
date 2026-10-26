# -*- coding: utf-8 -*-
"""同花顺问财 hexin-v / cookie(v) 指纹算法（纯 Python 实现）。

算法来源: https://s.thsi.cn/js/chameleon/chameleon.1.9.min.js
- 自定义 URL-safe Base64 字母表
- XOR 流压缩 + djb 校验和
- 18 字段指纹包

hexin-v 请求头与 Cookie 中的 v 值必须一致。
"""

import random
import time

ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'

# 各字段序列化宽度（字节数）
WIDTHS = [4, 4, 4, 4, 1, 1, 1, 3, 2, 2, 2, 2, 2, 2, 2, 4, 2, 1]

FIELD_NAMES = [
    'random', 'serverTime', 'clientTime', 'uaHash', 'osType', 'browserType',
    'pluginNum', 'clickCount', 'scrollCount', 'reserved9', 'mouseX', 'mouseY',
    'reserved12', 'reserved13', 'reserved14', 'sessionCounter', 'updateCounter',
    'versionFlag',
]

_INDEX = {ch: i for i, ch in enumerate(ALPHABET)}


def _b64decode(s):
    out = bytearray()
    buf = 0
    bits = 0
    for ch in s:
        v = _INDEX.get(ch)
        if v is None:
            continue
        buf = (buf << 6) | v
        bits += 6
        if bits >= 8:
            bits -= 8
            out.append((buf >> bits) & 255)
            buf &= (1 << bits) - 1
    return bytes(out)


def _b64encode(data):
    out = []
    n = len(data)
    for i in range(0, n, 3):
        a = data[i]
        b = data[i + 1] if i + 1 < n else 0
        c = data[i + 2] if i + 2 < n else 0
        tri = (a << 16) | (b << 8) | c
        out.append(ALPHABET[(tri >> 18) & 63])
        out.append(ALPHABET[(tri >> 12) & 63])
        if i + 1 < n:
            out.append(ALPHABET[(tri >> 6) & 63])
        if i + 2 < n:
            out.append(ALPHABET[tri & 63])
    return ''.join(out)


def _checksum(data):
    """djb 风格校验和，取低 8 位。"""
    u = 0
    for n in data:
        u = ((u << 5) - u + n) & 0xFFFFFFFF
    return u & 255


def _compress_xor(raw, cs):
    out = bytearray([3, cs])
    c = cs
    for b in raw:
        out.append(b ^ (c & 255))
        c = (~(131 * c)) & 0xFFFFFFFF
    return bytes(out)


def _decompress_xor(data, start, cs):
    out = bytearray()
    c = cs
    for i in range(start, len(data)):
        out.append(data[i] ^ (c & 255))
        c = (~(131 * c)) & 0xFFFFFFFF
    return bytes(out)


def _pack(fields):
    raw = bytearray()
    for i, width in enumerate(WIDTHS):
        f = (fields[i] if i < len(fields) else 0) & 0xFFFFFFFF
        for k in range(width - 1, -1, -1):
            raw.append((f >> (8 * k)) & 255)
    return bytes(raw)


def _unpack(raw):
    fields = []
    e = 0
    for width in WIDTHS:
        f = 0
        for _ in range(width):
            f = (f << 8) | (raw[e] if e < len(raw) else 0)
            e += 1
        fields.append(f & 0xFFFFFFFF)
    return fields


def encode(fields):
    """把 18 个 uint32 字段编码成 hexin-v token。"""
    if len(fields) != len(WIDTHS):
        raise ValueError(f'expected {len(WIDTHS)} fields, got {len(fields)}')
    raw = _pack(fields)
    cs = _checksum(raw)
    return _b64encode(_compress_xor(raw, cs))


def decode(token):
    """解码 hexin-v token，返回 {'checksum': int, 'fields': [...], 'meta': {...}}。"""
    data = _b64decode(token)
    if not data or data[0] != 3:
        raise ValueError(f'invalid prefix: {data[0] if data else None}')
    cs = data[1]
    raw = _decompress_xor(data, 2, cs)
    if _checksum(raw) != cs:
        raise ValueError('checksum mismatch')
    fields = _unpack(raw)
    return {
        'checksum': cs,
        'fields': fields,
        'meta': dict(zip(FIELD_NAMES, fields)),
    }


def _djb_hash(s):
    h = 0
    for ch in s:
        h = ((h << 5) - h + ord(ch)) & 0xFFFFFFFF
    return h


def build_fingerprint(server_time=None, client_time=None, user_agent=None, **extra):
    """构造问财 Web 端 18 字段指纹。"""
    now = int(time.time())
    server_time = int(server_time if server_time else now)
    client_time = int(client_time if client_time else now)
    ua = user_agent or DEFAULT_USER_AGENT

    return [
        random.randint(0, 0xFFFFFFFF),
        server_time,
        client_time,
        _djb_hash(ua),
        1,                                   # osType: Windows
        10,                                  # browserType: Chrome
        5,                                   # pluginNum
        int(extra.get('click_count', 0)),
        int(extra.get('scroll_count', 0)),
        0,
        int(extra.get('mouse_x', 0)),
        int(extra.get('mouse_y', 0)),
        0,
        int(extra.get('reserved13', 0)),
        0,
        int(extra.get('session_counter', 0)),
        int(extra.get('update_counter', 0)),
        3,                                   # versionFlag
    ]


DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
)


def get_token(server_time=None, user_agent=None):
    """生成一个 hexin-v token。"""
    return encode(build_fingerprint(server_time=server_time, user_agent=user_agent))

