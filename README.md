# pywencai-fix

**同花顺问财数据抓取 —— 2026 接口修复版。纯 Python 实现反爬指纹，不再需要 Node.js。**

> A community fix for `pywencai` 0.13.1. In 2026 iwencai (ths) rotated its anti-bot fingerprint
> to the *chameleon* algorithm and moved `get-robot-data` behind a new path, so the original
> package gets a hard `403` on every request. This fork reverses the new fingerprint scheme in
> pure Python (no Node.js) and targets the current endpoints. Public API is unchanged.

---

## 1. 症状

原版 `pywencai` 0.13.1 调用会直接崩在解析阶段：

```
Traceback (most recent call last):
  File "main.py", line 5, in <module>
    res = pywencai.get(query=query)
  File "...\pywencai\wencai.py", line 185, in get
    data = params.get('data')
AttributeError: 'NoneType' object has no attribute 'get'
```

这个 `AttributeError` 只是表象。真正发生的是：**服务端返回 403**，`get_robot_data()` 内部吞掉异常后返回 `None`，
而 `get()` 里没有做空值保护。把请求抓出来看就是一行 `403 Forbidden`。

## 2. 根因

三个变化叠加，任何单独修一个都不够：

### 2.1 旧接口的整个路径前缀被 WAF 封了

```
POST https://www.iwencai.com/customized/chart/get-robot-data      -> 403 (openresty)
POST https://www.iwencai.com/customized/chart/get-robot-data-v2   -> 403 (同样的页面)
GET  https://www.iwencai.com/customized/chart/get-robot-data      -> 403
```

注意第二个请求：`get-robot-data-v2` 这个路径**根本不存在**，却返回了完全相同的 403 页面。
说明拦截发生在 `/customized/chart/*` 前缀层，不是在业务代码里校验参数 —— 换参数、换 UA、补 Cookie 都没用。

### 2.2 `hexin-v` 指纹算法换代，旧 token 里的时间戳是写死的

旧版 `hexin-v.bundle.js` 生成的 token 长度 60，看起来正常，但解出来是这样：

```json
{
  "random": 3255198308,
  "serverTime": 1670329000,   // ← 2022-12-06，写死在 js 里
  "clientTime": 1792982498,
  "uaHash": 2137073146,
  "osType": 1, "browserType": 0, "pluginNum": 0,
  "versionFlag": 3
}
```

`serverTime` 是个 2022 年的常量，服务端判定 token 过期，直接拒绝。
新版用的是 chameleon 算法（对应前端脚本 `s.thsi.cn/js/chameleon/chameleon.1.9.min.js`），
要求 `serverTime` 与真实服务器时间对齐，并且 `hexin-v` 请求头必须与 Cookie 里的 `v` **完全一致**。

### 2.3 请求形态变了

- 新增 `/screener` 预热步骤，用来对齐服务器时间和拿会话标识 `rsh`
- 请求体从 `application/json` 改为 `application/x-www-form-urlencoded`
- 必须携带 `rsh`，否则会话对不上

## 3. 当前可用的请求链路

```
GET  https://www.iwencai.com/screener
     └─ 预热：从响应 Date 头取服务器时间，建立会话

POST https://www.iwencai.com/unifiedwap/unified-wap/v2/result/get-robot-data
     └─ 自然语言问句 -> condition 表达式 + footer url（含分页所需的全部参数）

POST https://www.iwencai.com/gateway/urp/v7/landing/getDataList
     └─ 分页取全量数据（参数来自上一步的 footer url）

POST https://www.iwencai.com/unifiedwap/unified-wap/v2/stock-pick/find
     └─ find 参数（指定股票列表）走这条
```

好消息是响应结构基本没变，仍然是 `data.answer[].txt[].content.components[]`，
组件类型还是 `xuangu_tableV1`，`meta.extra` 里 `condition` / `row_count` 都在，
`config.other_info.footer_info.url` 也还在。所以解析层改动很小。

## 4. `hexin-v` 指纹算法

纯 Python 复刻，见 [`pywencai/hexin.py`](pywencai/hexin.py)，**零 Node.js 依赖**。

| 项 | 说明 |
|---|---|
| 字段数 | 18 个 uint32 |
| 字节宽度 | `[4,4,4,4,1,1,1,3,2,2,2,2,2,2,2,4,2,1]`，共 43 字节 |
| 校验 | djb 风格哈希取低 8 位 |
| 压缩 | 前置 `[0x03, checksum]`，再按 `c = ~(131 * c) & 0xFFFFFFFF` 逐字节 XOR |
| 编码 | 自定义 URL-safe base64（字母表 `A-Za-z0-9-_`，无填充） |
| 长度 | 45 字节 → **60 字符** |

关键字段含义：

| 字段 | 值 | 说明 |
|---|---|---|
| `random` | 随机 | 每次请求变化 |
| `serverTime` | 服务器时间(秒) | **旧版就错在这里**，必须是真实时间 |
| `clientTime` | 本地时间(秒) | |
| `uaHash` | djb(User-Agent) | 必须与请求头 UA 一致 |
| `osType` / `browserType` | 1 / 10 | Windows / Chrome |
| `versionFlag` | 3 | |

正确性验证方式（与 JS 实现逐字节比对）：

```python
# 同一组字段，Python 与 JS 的编码结果完全相同
# 500 次随机字段往返，encode -> decode 无损
python examples/decode_token.py <任意 token>   # 解码查看 18 个字段
```

## 5. 安装

```bash
git clone https://github.com/houying12/pywencai-fix.git
cd pywencai-fix
pip install -e .
```

或者直接：

```bash
pip install git+https://github.com/houying12/pywencai-fix.git
```

> **注意**：发行包名仍然是 `pywencai`（版本 `0.13.1.post1`），目的是直接替换掉失效的官方 0.13.1，
> 这样原有代码 `import pywencai` 无需任何改动。
> 因此 **请不要把它发布到 PyPI**，会与上游冲突。本仓库只做 GitHub 分发。

依赖只有三个：`requests`、`pandas`、`pydash`。
原版要求的 `Node.js`、`PyExecJS`、`fake-useragent`、`ipykernel` 全部去掉了。

## 6. 使用

API 与原版完全一致：

```python
import pywencai

query = ('主板且非st')

df = pywencai.get(query=query)
print(df)
```

```python
# 取全量（自动分页）
df = pywencai.get(query='主板且非st', loop=True, perpage=100)

# 排序
df = pywencai.get(query='主板且非st,流通市值>100亿',
                  sort_key='最新价', sort_order='desc', perpage=5)

# 指定股票范围
df = pywencai.get(query='主板', find=['600519', '000001'], perpage=20)

# 其它品类
pywencai.get(query='沪深300成分股', query_type='zhishu')
```

新增的两个能力：

```python
# 1. 结构化错误（原版是静默返回 None / 空 DataFrame）
try:
    pywencai.get(query='')
except pywencai.WencaiError as e:
    print('问句有问题:', e)

# 2. 手动重置会话（cookie 失效或 IP 被限流后）
pywencai.reset_session()
```

## 7. 相对原版的改动

| 文件 | 改动 |
|---|---|
| `hexin.py` | **新增**。chameleon 指纹算法的纯 Python 实现，含 `decode()` 可用于调试 token |
| `headers.py` | 改用新指纹；固定 Chrome UA（`fake-useragent` 的随机 UA 反而更容易触发风控）；去掉 Node 调用 |
| `wencai.py` | 新增 `_SessionManager`：`/screener` 预热、`cookie v` 与 `hexin-v` 成对同步、线程锁防止并发交叉导致 403；切换到新接口；表单编码 + `rsh`；`WencaiError` 不参与重试；新增 `reset_session()` |
| `convert.py` | 遍历全部 `answer`/`txt` 块收集组件（原来只取 `answer.0.txt.0`）；校验 `status_code`，非 0 抛中文错误；非 JSON 响应明确报错 |
| `__init__.py` | 导出 `get` / `reset_session` / `WencaiError` / `__version__` |

顺手修掉的两个原有 bug：

- **`loop_page` 的 `perpage` 一直无效**：`kwargs.pop('perpage')` 之后没有回填，内层 `get_page` 退回默认 100。
  现在 `loop=2, perpage=5` 真的只取 10 行。
- **服务端排序已失效**：`urp_sort_index` 传合法列名也不排序（传非法列名直接返回 0 行）。
  改为拿到 DataFrame 后本地稳定排序，并支持列名前缀匹配（`sort_key='量比'` 可命中 `分时量比[20261026 09:25]`）。

## 8. 已知限制

- **排序在本地做**：服务端参数已不生效，`loop=True` 全量拉取后排序结果才是完整的；
  只取单页时，排序只作用于这一页。
- **单页上限 100**：`perpage` 传入大于 100 会被截断到 100。
- **问句子句数限制**：问财服务端对解析后的子句数有上限（约 10 条），超了会返回业务错误，
  本版会直接抛 `WencaiError` 而不是返回空表。条件多时建议拆成多次查询再求交集。
- **频率**：高频调用会触发风控。遇到 403 建议加 `sleep`、降低频率或换网络出口。
- **接口随时会变**：这是抓取网页端接口的实现，不是官方开放平台 API，出现变化属正常。

## 9. 自检

```bash
python tests/test_regression.py
```

覆盖：基本查询、单页、循环分页、全量分页、升/降序排序、`find`、详情类返回 dict、
`no_detail`、其它 `query_type`、异常问句。全部通过会输出 `ALL PASSED`。

## 10. 声明

- 本项目为开源社区的个人修复分支，**与同花顺官方无关**。
- 数据来自同花顺问财的公开网页接口，实现方式与浏览器访问网页一致。
- 仅供个人学习与量化研究，**请低频使用**，高频调用会被风控；商用请自行评估法律与合规风险。
- 请遵守同花顺的服务条款与 robots 协议。

## License

[MIT](LICENSE)

基于 [pywencai](https://pypi.org/project/pywencai/)（作者 pluto）修复，保留原始 MIT 版权声明。
指纹算法依据同花顺前端脚本 `chameleon.1.9.min.js` 的行为还原。
