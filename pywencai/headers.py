# -*- coding: utf-8 -*-
"""请求头构造。

2026 版问财要求每次请求携带 hexin-v 指纹头，且必须与 Cookie 中的 v 值一致。
指纹由 chameleon 算法生成（见 hexin.py），已改为纯 Python 实现，不再依赖 Node.js。
"""

from .hexin import DEFAULT_USER_AGENT, get_token as _get_token


def get_token(server_time=None, user_agent=None):
    '''获取 hexin-v token（纯 Python 实现，无需 Node.js）。'''
    return _get_token(server_time=server_time, user_agent=user_agent)


def headers(cookie=None, user_agent=None, server_time=None):
    '''构造请求头。

    注意：Cookie 里的 v 必须与头里的 hexin-v 相同，否则服务端返回 403。
    '''
    if user_agent is None:
        user_agent = DEFAULT_USER_AGENT

    token = get_token(server_time=server_time, user_agent=user_agent)
    h = {
        'hexin-v': token,
        'User-Agent': user_agent,
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Origin': 'https://www.iwencai.com',
        'Referer': 'https://www.iwencai.com/screener/result?querytype=stock',
    }
    if cookie:
        h['Cookie'] = cookie
    return h
