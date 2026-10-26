# -*- coding: utf-8 -*-
"""问财数据抓取核心（2026 版接口适配）。

2026 年起，同花顺问财做了几处调整，旧版 pywencai 会直接 403：
1. 反爬指纹 hexin-v 改为 chameleon 算法，且必须与 Cookie 中的 v 一致；
2. 原 ``/customized/chart/get-robot-data`` 整个前缀被 WAF 封禁，
   新地址为 ``/unifiedwap/unified-wap/v2/result/get-robot-data``；
3. 请求体改为 form-urlencoded，并需要携带 ``rsh`` 会话标识；
4. 调用前需要先访问 ``/screener`` 预热，对齐服务器时间。

本模块已按上述变更重写，同时保持原有 ``pywencai.get()`` 参数完全兼容。
"""

import json
import logging
import math
import re
import threading
import time
import uuid
from email.utils import parsedate_to_datetime
from typing import List
from urllib.parse import quote, urlencode

import pandas as pd
import pydash as _
import requests as rq

from . import hexin
from .convert import WencaiError, convert
from .headers import get_token

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('[pywencai] %(asctime)s - %(levelname)s - %(message)s'))
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ==== 接口地址 ====
ROBOT_DATA_URL = 'https://www.iwencai.com/unifiedwap/unified-wap/v2/result/get-robot-data'
DATALIST_URL = 'https://www.iwencai.com/gateway/urp/v7/landing/getDataList'
FIND_URL = 'https://www.iwencai.com/unifiedwap/unified-wap/v2/stock-pick/find'
WARMUP_URL = 'https://www.iwencai.com/screener'

WARMUP_TTL = 600          # 预热会话有效期（秒）
ADD_INFO = '{"urp":{"scene":1,"company":1,"business":1},"contentType":"json","searchInfo":true}'
LOG_INFO = '{"input_type":"click"}'

_TIMEOUT = (5, 20)


# ---------------------------------------------------------------- 会话管理

def _parse_cookie_string(cookie):
    '''把浏览器复制的 cookie 字符串解析成 dict。'''
    result = {}
    if not cookie:
        return result
    if isinstance(cookie, dict):
        return {str(k): str(v) for k, v in cookie.items()}
    for item in str(cookie).split(';'):
        item = item.strip()
        if not item or '=' not in item:
            continue
        k, v = item.split('=', 1)
        result[k.strip()] = v.strip()
    return result


def _server_time_from_response(res):
    '''从响应的 Date 头取服务器时间（秒）。'''
    try:
        date = res.headers.get('Date')
        if date:
            return int(parsedate_to_datetime(date).timestamp())
    except Exception:
        pass
    return None


def _server_time_from_html(text):
    '''页面里若内联了 TOKEN_SERVER_TIME 则优先使用。'''
    if not text:
        return None
    m = re.search(r'TOKEN_SERVER_TIME\s*=\s*([\d.]+)', text)
    if m:
        return int(float(m.group(1)))
    return None


class _SessionManager:
    '''维护一个带预热与指纹的 requests.Session（按需重建）。'''

    def __init__(self):
        self._lock = threading.RLock()
        self.session = None
        self.server_time = None
        self.rsh = None
        self.warmed_at = 0
        self.cookie = None
        self.user_agent = None

    def acquire(self, cookie=None, user_agent=None, request_params=None, log=False):
        ua = user_agent or hexin.DEFAULT_USER_AGENT
        with self._lock:
            need = (
                self.session is None
                or cookie != self.cookie
                or ua != self.user_agent
                or (time.time() - self.warmed_at) > WARMUP_TTL
            )
            if need:
                self._warmup(cookie, ua, request_params, log)
            return self.session

    def _warmup(self, cookie, ua, request_params, log=False):
        '''访问 /screener 预热：拿服务器时间、会话标识，建立可复用的连接池。'''
        session = rq.Session()
        session.headers.update({
            'User-Agent': ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        })

        # 用户自带 cookie（可含登录态），但 v 稍后会覆盖为新指纹
        for k, v in _parse_cookie_string(cookie).items():
            if k != 'v':
                session.cookies.set(k, v)

        server_time = None
        rsh = None
        params = self._extra_params(request_params)
        params.setdefault('timeout', 15)
        try:
            res = session.get(WARMUP_URL, **params)
            server_time = _server_time_from_html(res.text) or _server_time_from_response(res)
            m = re.search(r'other_uid=([^;"\'\s]+)', res.text)
            if m:
                rsh = m.group(1)
            elif session.cookies.get('other_uid'):
                rsh = session.cookies.get('other_uid')
        except Exception as e:
            log and logger.warning(f'预热失败，使用本地时间兜底: {e}')

        self.session = session
        self.server_time = server_time or int(time.time())
        self.rsh = rsh or f'Ths_iwencai_Xuangu_{uuid.uuid4().hex}'
        self.cookie = cookie
        self.user_agent = ua
        self.warmed_at = time.time()
        log and logger.info(f'会话预热完成 server_time={self.server_time} rsh={self.rsh}')

    @staticmethod
    def _extra_params(request_params):
        '''过滤出可以安全传给 requests 的参数（避免与 data/headers 冲突）。'''
        params = dict(request_params or {})
        for key in ('data', 'json', 'headers', 'url', 'method'):
            params.pop(key, None)
        return params

    def fresh_token(self, user_agent=None):
        '''生成新指纹，并同步写入 cookie v（二者必须一致）。'''
        token = get_token(server_time=self.server_time, user_agent=user_agent or self.user_agent)
        self.session.cookies.set('v', token)
        return token

    def build_headers(self, question, request_params=None):
        ua = self.user_agent or hexin.DEFAULT_USER_AGENT
        token = self.fresh_token(ua)
        referer = (
            'https://www.iwencai.com/screener/result?'
            f'w={quote(question or "")}&querytype=stock&sign={int(time.time() * 1000)}'
        )
        return {
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': 'https://www.iwencai.com',
            'Referer': referer,
            'User-Agent': ua,
            'hexin-v': token,
        }

    def post(self, url, body, question, request_params=None, timeout=_TIMEOUT):
        '''线程安全地发一次请求：生成指纹 -> 同步 cookie v -> POST。

        hexin-v 头与 cookie v 必须成对出现，加锁可避免多线程交叉导致 403。
        '''
        params = self._extra_params(request_params)
        params.setdefault('timeout', timeout)
        with self._lock:
            headers = self.build_headers(question, request_params)
            return self.session.post(url, data=body, headers=headers, **params)

    def request_params(self, request_params):
        return self._extra_params(request_params)

    def reset(self):
        with self._lock:
            self.session = None
            self.warmed_at = 0


_SESSION = _SessionManager()


def reset_session():
    '''重置内部会话（cookie 失效、IP 被限流后可手动调用）。'''
    _SESSION.reset()


# ---------------------------------------------------------------- 通用工具

def while_do(do, retry=10, sleep=0, log=False):
    '''失败重试。业务错误（WencaiError）不重试。'''
    count = 0
    last_error = None
    while count < retry:
        time.sleep(sleep)
        try:
            return do()
        except WencaiError:
            raise
        except Exception as e:
            last_error = e
            count += 1
            log and logger.warning(f'{count}次尝试失败: {e}')
    if last_error is not None:
        log and logger.error(f'重试{retry}次后仍失败: {last_error}')
    return None


def replace_key(key):
    '''替换key'''
    key_map = {
        'question': 'query',
        'sort_key': 'urp_sort_index',
        'sort_order': 'urp_sort_way'
    }
    return key_map.get(key, key)


# ---------------------------------------------------------------- 第一步：问句 -> 条件

def get_robot_data(**kwargs):
    '''获取condition'''
    retry = kwargs.get('retry', 10)
    sleep = kwargs.get('sleep', 0)
    question = kwargs.get('query')
    log = kwargs.get('log', False)
    query_type = kwargs.get('query_type', 'stock')
    cookie = kwargs.get('cookie', None)
    user_agent = kwargs.get('user_agent', None)
    request_params = kwargs.get('request_params', {})
    pro = kwargs.get('pro', False)

    if not question:
        raise WencaiError('query 不能为空')

    _SESSION.acquire(cookie, user_agent, request_params, log)   # 确保预热完成
    log and logger.info('获取condition开始')

    body = {
        'source': 'Ths_iwencai_Xuangu',
        'version': '2.0',
        'query_area': '',
        'block_list': '',
        'add_info': ADD_INFO,
        'question': question,
        'perpage': '10',
        'page': '1',
        'secondary_intent': query_type,
        'log_info': LOG_INFO,
        'rsh': _SESSION.rsh,
    }
    if pro:
        body['iwcpro'] = 1

    params = _SESSION.request_params(request_params)

    def do():
        res = _SESSION.post(ROBOT_DATA_URL, urlencode(body), question, request_params)
        if res.status_code == 403:
            raise RuntimeError('403 被风控拦截（指纹或频率问题）')
        if res.status_code != 200:
            raise RuntimeError(f'HTTP {res.status_code}')
        result = convert(res)
        log and logger.info('获取get_robot_data成功')
        return result

    result = while_do(do, retry, sleep, log)

    if result is None:
        log and logger.info('获取get_robot_data失败')

    return result


# ---------------------------------------------------------------- 第二步：分页取全量

def get_page(url_params, **kwargs):
    '''获取每页数据'''
    retry = kwargs.pop('retry', 10)
    sleep = kwargs.pop('sleep', 0)
    log = kwargs.pop('log', False)
    cookie = kwargs.pop('cookie', None)
    user_agent = kwargs.get('user_agent', None)
    find = kwargs.pop('find', None)
    query_type = kwargs.get('query_type', 'stock')
    request_params = kwargs.get('request_params', {})
    pro = kwargs.get('pro', False)
    question = kwargs.get('query')
    perpage = kwargs.pop('perpage', 100)
    perpage = min(int(perpage or 100), 100)   # 问财单页上限 100
    page = kwargs.pop('page', 1)
    comp_data = kwargs.get('data') if isinstance(kwargs.get('data'), dict) else {}

    _SESSION.acquire(cookie, user_agent, request_params, log)   # 确保预热完成

    data = dict(url_params or {})
    data.update({
        'perpage': perpage,
        'page': page,
        'query_type': query_type,
        'source': 'Ths_iwencai_Xuangu',
        'version': '2.0',
        'add_info': ADD_INFO,
        'log_info': LOG_INFO,
        'secondary_intent': query_type,
        'question': question,
        'rsh': _SESSION.rsh,
    })
    # 组件条件（condition / comp_id / uuid）必须带上，否则服务端返回“组件不存在”
    for k, v in (comp_data or {}).items():
        if v is not None:
            data[k] = v
    if kwargs.get('urp_sort_index'):
        data['urp_sort_index'] = kwargs['urp_sort_index']
    if kwargs.get('urp_sort_way'):
        data['urp_sort_way'] = kwargs['urp_sort_way']

    if find is None:
        target_url = DATALIST_URL
        path = 'answer.components.0.data.datas'
        if pro:
            target_url = f'{target_url}?iwcpro=1'
    else:
        if isinstance(find, List):
            find = ','.join(find)
        target_url = FIND_URL
        path = 'data.data.datas'
        data['question'] = find
        data['query_type'] = query_type

    log and logger.info(f'第{data.get("page")}页开始')

    def do():
        res = _SESSION.post(target_url, data, question or find, request_params)
        if res.status_code == 403:
            raise RuntimeError('403 被风控拦截（指纹或频率问题）')
        if res.status_code != 200:
            raise RuntimeError(f'HTTP {res.status_code}')

        result_do = json.loads(res.text)
        code = result_do.get('status_code')
        if code is not None and str(code) != '0':
            raise WencaiError(f'分页接口返回错误 status_code={code}: {result_do.get("status_msg")}')

        data_list = _.get(result_do, path)

        if not data_list:
            log and logger.error(f'第{data.get("page")}页返回空！')
            raise Exception('data_list is empty!')
        log and logger.info(f'第{data.get("page")}页成功')
        return pd.DataFrame.from_dict(data_list)

    result = while_do(do, retry, sleep, log)

    if result is None:
        log and logger.error(f'第{data.get("page")}页失败')

    return result


def can_loop(loop, count):
    return count < loop


def loop_page(loop, row_count, url_params, **kwargs):
    '''循环分页'''
    count = 0
    perpage = kwargs.pop('perpage', 100) or 100
    perpage = min(int(perpage), 100)          # 问财单页上限 100
    kwargs['perpage'] = perpage               # 显式回填，否则内层会退回默认 100
    max_page = math.ceil(row_count / perpage) if row_count else 1
    result = None
    if 'page' not in kwargs:
        kwargs['page'] = 1
    initPage = kwargs['page']
    loop_count = max_page if loop is True else loop
    while can_loop(loop_count, count):
        kwargs['page'] = initPage + count
        resultPage = get_page(url_params, **kwargs)
        count = count + 1
        if resultPage is None:
            break
        if result is None:
            result = resultPage
        else:
            result = pd.concat([result, resultPage], ignore_index=True)

    return result


# ---------------------------------------------------------------- 对外入口

def get(loop=False, **kwargs):
    '''获取结果'''
    kwargs = {replace_key(key): value for key, value in kwargs.items()}
    params = get_robot_data(**kwargs)
    if params is None:
        return None

    data = params.get('data')
    url_params = params.get('url_params') or {}
    condition = _.get(data, 'condition')

    if condition is not None:
        kwargs = {**kwargs, **data}
        find = kwargs.get('find', None)
        if loop and find is None:
            row_count = params.get('row_count')
            result = loop_page(loop, row_count, url_params, **kwargs)
        else:
            result = get_page(url_params, **kwargs)
        return _maybe_sort(result, kwargs)
    else:
        no_detail = kwargs.get('no_detail')
        if no_detail != True:
            return data
        else:
            return None


def _maybe_sort(df, kwargs):
    '''本地排序兜底。

    2026 版服务端的 urp_sort_index / urp_sort_way 已不再生效（传了也不排），
    这里在拿到数据后按列名本地排序，保证 sort_key / sort_order 的语义可用。
    '''
    sort_key = kwargs.get('urp_sort_index')
    sort_order = (kwargs.get('urp_sort_way') or 'asc')
    if df is None or not sort_key or not hasattr(df, 'columns'):
        return df
    if sort_key not in df.columns:
        # 支持传入不带日期后缀的列名，如 '量比' 匹配 '分时量比[20261026 09:25]'
        matched = [c for c in df.columns if isinstance(c, str) and c.startswith(str(sort_key))]
        if not matched:
            return df
        sort_key = matched[0]
    ascending = str(sort_order).lower() not in ('desc', 'descend', 'false', '0')
    try:
        numeric = pd.to_numeric(df[sort_key], errors='coerce')
        if numeric.notna().sum() >= max(1, len(df) // 2):
            return df.assign(__sort__=numeric).sort_values(
                '__sort__', ascending=ascending, kind='mergesort'
            ).drop(columns='__sort__').reset_index(drop=True)
        return df.sort_values(sort_key, ascending=ascending, kind='mergesort').reset_index(drop=True)
    except Exception:
        return df
