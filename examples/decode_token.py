# -*- coding: utf-8 -*-
"""调试工具：解码一个 hexin-v token，查看 18 个指纹字段。

用法：
    python examples/decode_token.py <hexin-v token>
    python examples/decode_token.py                # 不带参数则现场生成一个并解码

典型用途：从浏览器开发者工具里复制请求头 hexin-v 的值，确认 serverTime 是否过期。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pywencai.hexin import build_fingerprint, decode, encode  # noqa: E402


def main():
    if len(sys.argv) > 1:
        token = sys.argv[1].strip()
        print(f'输入 token: {token}  (长度 {len(token)})')
    else:
        fields = build_fingerprint()
        token = encode(fields)
        print(f'现场生成 token: {token}  (长度 {len(token)})')

    try:
        result = decode(token)
    except ValueError as e:
        print(f'解码失败: {e}')
        raise SystemExit(1)

    print(f'校验和: {result["checksum"]}')
    print('字段:')
    print(json.dumps(result['meta'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
