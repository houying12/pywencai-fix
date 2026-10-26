# -*- coding: utf-8 -*-
"""
将 get-robot-data 的原始响应转换为内部结构。

2026 版接口的响应结构：data.answer[i].txt[j].content.components
本模块会遍历所有 answer / txt 块收集组件，兼容单表与多组件两种形态。
"""

import pandas as pd
import json
import pydash as _
import requests as rq
from urllib.parse import urlparse, parse_qs
from .headers import headers


class WencaiError(Exception):
    '''问财接口返回的业务错误（如问句无法识别、被风控等）。'''


def get_url(url):
    res = rq.request(
        method='GET',
        url=f'http://www.iwencai.com{url}',
        headers=headers()
    )
    result = json.loads(res.text)
    return result.get('data')


def xuangu_tableV1_handler(comp, comps):
    '''xuangu_tableV1类型'''
    return {
        'condition': _.get(comp, 'data.meta.extra.condition'),
        'comp_id': comp.get('cid'),
        'uuid': comp.get('puuid')
    }


def common_handler(comp, comps):
    '''common类型'''
    datas = _.get(comp, 'data.datas')
    if isinstance(datas, list):
        return pd.DataFrame.from_dict(datas)
    else:
        return _.get(comp, 'data')


def container_handler(comp, comps):
    '''container类型'''
    result = {}
    for uuid in _.get(comp, 'config.children', []) or []:
        child = _.find(comps, lambda c: c.get('uuid') == uuid)
        key = _.get(child, 'show_type')
        if key is not None and key != '':
            result[key] = show_type_handler(child, comps)
    return result


def txt_handler(comp, comps):
    '''txt类型'''
    return _.get(comp, 'data.content')


def tab4_handler(comp, comps):
    '''tab4类型'''
    result = {}
    for tab in comp.get('tab_list') or []:
        tab_name = tab.get('tab_name')
        tab_list = tab.get('list') or []
        if tab_name is not None:
            tabResult = result[tab_name] = {}
            for tcomp in tab_list:
                show_type = tcomp.get('show_type')
                tabResult[show_type] = show_type_handler(tcomp, tab_list)
    return result


def tab1_handler(comp, comps):
    '''tab1类型'''
    result = {}
    data = comp.get('data') or {}
    for tab in comp.get('tab_list') or []:
        tab_name = tab.get('tab_name')
        tab_list = tab.get('list') or []
        if tab_name is not None:
            tabResult = result[tab_name] = {}
            for tcomp in tab_list:
                show_type = tcomp.get('show_type')
                data_index = tcomp.get('data_index')
                tcomp.set('data', data.get(data_index))
                tabResult[show_type] = show_type_handler(tcomp, tab_list)
    return result


def dragon_tiger_stock_handler(comp, comps):
    '''龙虎榜分析'''
    result = {}
    data = _.get(comp, 'data.datas.0')
    detail = data.pop('detail', None)

    result['data'] = pd.DataFrame.from_dict([data])
    if detail is not None:
        result['detail'] = {
            'buy': pd.DataFrame.from_dict(_.get(detail[0], 'buy.datas')),
            'sell': pd.DataFrame.from_dict(_.get(detail[0], 'sell.datas'))
        }
    return result


def wiki1_handler(comp, comps):
    url = _.get(comp, 'data.url')
    if url is not None:
        wcomp = get_url(url)
        if wcomp is not None:
            return show_type_handler(wcomp, comps)
        else:
            return None
    return None


def textblocklinkone_handler(comp, comps):
    data = _.get(comp, 'data.result.data')
    return pd.DataFrame.from_dict(data)


def nestedblocks_handler(comp, comps):
    '''股东户数分析'''
    subBlocks = _.get(comp, 'data.result.subBlocks.0.subBlocks') or []
    result = []
    for sub in subBlocks:
        url = sub.get('url')
        sub_comp = get_url(url)
        if sub_comp is not None:
            result.append(show_type_handler(sub_comp, comps))
    return result


show_type_handler_dict = {
    'container': container_handler,
    'txt1': txt_handler,
    'txt2': txt_handler,
    'tab4': tab4_handler,
    'dragon_tiger_stock': dragon_tiger_stock_handler,
    'tab1': tab1_handler,
    # 'wiki1': wiki1_handler,
    'textblocklinkone': textblocklinkone_handler,
    'nestedblocks': nestedblocks_handler
}


def show_type_handler(comp, comps):
    '''处理每种不同的show_type类型'''
    show_type = comp.get('show_type')
    handler = show_type_handler_dict.get(show_type)
    if handler is not None:
        return handler(comp, comps)
    else:
        return common_handler(comp, comps)


def get_key(comp):
    '''获取每一项的key'''
    h1 = _.get(comp, 'title_config.data.h1') or _.get(comp, 'config.title') or _.get(comp, 'show_type')
    return h1


def multi_show_type_handler(components):
    '''处理多个show_type类型的数据'''
    result = {}
    for comp in components:
        key = get_key(comp)
        value = show_type_handler(comp, components)
        if key is not None and key != '' and value is not None:
            result[key] = value

    return result


def parse_url_params(url):
    """Parse URL parameters into a dictionary"""
    if not url:
        return {}

    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)

    # 单值列表展开为标量
    for key, value in query_params.items():
        if isinstance(value, list) and len(value) == 1:
            query_params[key] = value[0]

    return query_params


def iter_components(result):
    '''遍历所有 answer / txt 块，收集全部组件。'''
    components = []
    for answer in _.get(result, 'data.answer') or []:
        for block in answer.get('txt') or []:
            content = block.get('content')
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except (ValueError, TypeError):
                    continue
            comps = _.get(content, 'components')
            if isinstance(comps, list):
                components.extend([c for c in comps if isinstance(c, dict)])
    return components


def check_status(result):
    '''检查业务状态码，非 0 抛出 WencaiError。'''
    code = result.get('status_code', result.get('data', {}).get('status_code'))
    if code is None:
        return
    try:
        code_int = int(code)
    except (TypeError, ValueError):
        return
    if code_int != 0:
        msg = result.get('status_msg') or _.get(result, 'data.status_msg') or ''
        raise WencaiError(f'问财接口返回错误 status_code={code_int}: {msg}')


def convert(res):
    '''处理get_robot_data的结果'''
    try:
        result = res.json()
    except ValueError:
        raise WencaiError(
            f'返回内容不是 JSON（HTTP {res.status_code}）：{res.text[:200]!r}'
        )

    check_status(result)

    components = iter_components(result)
    if not components:
        raise WencaiError('返回中没有解析到组件（可能是问句无法识别或被风控）')

    url = _.get(components[0], 'config.other_info.footer_info.url')

    if len(components) == 1 and components[0].get('show_type') == 'xuangu_tableV1':
        params = {
            'data': xuangu_tableV1_handler(components[0], components),
            'row_count': _.get(components[0], 'data.meta.extra.row_count'),
            'url': url,
            'url_params': parse_url_params(url)
        }
    else:
        params = {
            'data': multi_show_type_handler(components),
            'url': url,
            'url_params': parse_url_params(url)
        }
    return params
