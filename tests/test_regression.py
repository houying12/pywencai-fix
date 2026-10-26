# -*- coding: utf-8 -*-
"""pywencai 修复版回归自检。

用法（无需安装，直接在仓库根目录运行）：
    python tests/test_regression.py

全部通过时最后一行输出 ALL PASSED。
注意：会向问财发起十余次真实请求，请勿频繁重复执行。
"""

import sys
import traceback
from pathlib import Path

# 允许未安装时直接从仓库根目录导入
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pywencai  # noqa: E402

QUERY = ('今日竞价量比>8,主板且非st,流通市值>12亿且<150亿,'
         '今日的前7交易日涨停天数<3')

results = []


def case(name, fn, check=None):
    try:
        out = fn()
        ok = True if check is None else bool(check(out))
        detail = f'shape={out.shape}' if hasattr(out, 'shape') else f'{type(out).__name__}'
        results.append(ok)
        print(f'[{"PASS" if ok else "FAIL"}] {name:26} {detail}')
    except Exception as e:
        results.append(False)
        print(f'[FAIL] {name:26} {type(e).__name__}: {str(e)[:120]}')
        traceback.print_exc(limit=1)


print(f'pywencai {pywencai.__version__} | {pywencai.__file__}\n')

case('基本查询', lambda: pywencai.get(query=QUERY),
     lambda d: hasattr(d, 'shape') and len(d) > 0)

case('单页 perpage=3', lambda: pywencai.get(query=QUERY, perpage=3),
     lambda d: len(d) <= 3)

case('循环分页 loop=2/5', lambda: pywencai.get(query=QUERY, loop=2, perpage=5),
     lambda d: len(d) <= 10)

case('全量分页 loop=True', lambda: pywencai.get(query='主板且非st', loop=True, perpage=100),
     lambda d: len(d) > 100)

case('排序 desc', lambda: pywencai.get(query='主板且非st,流通市值>100亿',
                                       sort_key='最新价', sort_order='desc', perpage=5),
     lambda d: float(d['最新价'].iloc[0]) > float(d['最新价'].iloc[-1]))

case('排序 asc', lambda: pywencai.get(query='主板且非st,流通市值>100亿',
                                      sort_key='最新价', sort_order='asc', perpage=5),
     lambda d: float(d['最新价'].iloc[0]) < float(d['最新价'].iloc[-1]))

case('find 参数', lambda: pywencai.get(query='主板', find=['600519', '000001'], perpage=10),
     lambda d: len(d) > 0)

case('详情类问题', lambda: pywencai.get(query='贵州茅台市盈率'),
     lambda d: isinstance(d, dict))

case('no_detail=True', lambda: pywencai.get(query='贵州茅台市盈率', no_detail=True),
     lambda d: d is None)

case('其它 query_type', lambda: pywencai.get(query='沪深300成分股', query_type='zhishu'),
     lambda d: isinstance(d, dict))


def expect_error():
    try:
        pywencai.get(query='')
    except pywencai.WencaiError:
        return True
    return False


case('空 query 抛 WencaiError', expect_error, lambda v: v is True)

print()
if all(results):
    print('ALL PASSED')
else:
    print(f'FAILED: {results.count(False)}/{len(results)}')
    sys.exit(1)
