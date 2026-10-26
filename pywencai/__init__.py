# -*- coding: utf-8 -*-
"""pywencai —— 同花顺问财数据抓取（2026 接口修复版）。

本包是 pywencai 0.13.1 的社区修复分支：
原版依赖的 hexin-v 指纹算法与 get-robot-data 接口已失效，请求会被 403 拦截。
本版改用 chameleon 指纹算法 + 新接口，并用纯 Python 重写指纹生成（不再需要 Node.js）。

对外 API 与原版完全兼容，仍是 ``pywencai.get(**kwargs)``。
"""

from .wencai import WencaiError, get, reset_session

__version__ = '0.13.1.post1'
__all__ = ['get', 'reset_session', 'WencaiError', '__version__']
