# -*- coding: utf-8 -*-
"""最简示例：一次问财查询。

运行： python examples/basic.py
"""

import pywencai

QUERY = (
    '今日竞价量比>8,主板且非st,流通市值>12亿且<150亿,'
    '今日的前7交易日涨停天数<3,竞价量>1万手,今日竞价金额>1500万,'
    '竞价量/自由流通股<0.022,特大单净量>-0.15,'
    '今日的前5交易日有涨停且未出现炸板,开盘价>ma10,所属行业'
)

df = pywencai.get(query=QUERY)

if df is None:
    print('未获取到数据')
elif isinstance(df, dict):          # 详情类问题会返回 dict
    print('返回内容:', list(df.keys()))
else:
    print(f'共 {len(df)} 只，{df.shape[1]} 个字段')
    cols = [c for c in df.columns if c in ('股票代码', '股票简称', '最新价')]
    print(df[cols].to_string(index=False) if cols else df.head().to_string())
