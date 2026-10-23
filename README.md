# 麦门渠道官 · McRoute

> 基于 **麦当劳中国 MCP（McDonald's China MCP）** 开发的**渠道决策** Skill：
> 回答一个被所有点餐助手忽略的问题——**这一顿，点外送还是到店自取？**
>
> 麦当劳程序员创意开发大赛参赛作品 · 非麦当劳官方产品。

![Python](https://img.shields.io/badge/python-3.8%2B-blue) ![零依赖](https://img.shields.io/badge/dependencies-0-brightgreen) ![自测](https://img.shields.io/badge/selftest-253%20passed-success) ![License](https://img.shields.io/badge/license-MIT-green)

---

## 它解决什么问题

所有人都在比「哪家店怎么点最便宜」，但**很少有人问「我到底该点外送还是自己跑一趟」**。

而这个决策远比想象的复杂：

| | 外送 | 到店自取 |
|---|---|---|
| 配送费 | 有，随距离与时段浮动 | 无 |
| **打包费** | **有**（实测 ¥2.80） | 无 |
| 起送价 | **硬门槛**，未达标直接不可下单 | 无 |
| 券可用性 | 券绑**商品**，还可能**仅到店可用** | 同左 |
| 券绑定 | 绑「能送到你家」的门店 | 绑「离你最近」的门店 |
| 时间成本 | 等餐 | 往返路程 + 出餐 |

关键在于两点：

1. **能送外卖的店，和离你最近的店，常常不是同一家。** 所以「到店更便宜」不等于「去那家店更便宜」——券是绑门店的。
2. **券是商品券，不是满减券。** 券名里的「11.9元」是用券价，
   抵扣额要拿菜单原价减出来。而且**券只对绑定的那款商品生效**——
   你买套餐，这张单品券就用不上。

**核心洞察：取数交给 MCP，算术交给代码，表达交给 Agent。**

| 角色 | 职责 |
|---|---|
| 麦当劳 MCP | 实时门店、菜单、券、价格、配送费、打包费、起送价 |
| `scripts/decider.py` | 确定性渠道计价与对比，输出可执行建议 |
| WorkBuddy Agent | 理解需求、编排调用、讲解方案、确认后下单 |

---

## 🎮 在线试算（无需登录，浏览器打开即玩）

**→ <https://Seing-yu.github.io/mcd-route/>**

拖动配送费、打包费、起送价、等待时间、**每分钟时间成本**，实时看出哪个渠道更划算；
勾掉某张券，立刻看到结论怎么变。

> 页面上的计算逻辑是 `decider.py` 的**同一套实现**，
> `scripts/parity_check.py` 会逐场景对拍两端结果（56 项比对）防止漂移。
>
> 页面使用样例数据，不连接麦当劳接口、不读取你的任何账户信息。
> 想用真实数据请在本地配置 Token 后运行 `real_run.py`。

---

## 一句话安装

```bash
git clone <本仓库> && cp -r skills/mcd-route ~/.workbuddy/skills/
```

（Windows 为 `%USERPROFILE%\.workbuddy\skills\`；MCP Token 配置见下文「安装」。）

---

## 安装

### 1. 申请麦当劳 MCP Token

前往麦当劳 MCP 开放平台 <https://open.mcd.cn/mcp>，用手机号登录后
在「控制台」点击「激活」，复制 Token。

### 2. 配置 MCP Token

**Windows 一键配置（推荐，Token 不经过对话）**：

```powershell
powershell -ExecutionPolicy Bypass -File .\skills\mcd-route\scripts\setup_mcp.ps1
```

脚本从 `~/.workbuddy/.mcd_token` 读 Token → 备份原 `mcp.json` →
写出新配置 → 校验 JSON 与编码，全程**不回显 Token**。

**手动配置**：左侧边栏【专家·技能·连接器】→【连接器】→
右上角【自定义连接器】→【配置 MCP】，填入
[`mcp-config.example.json`](mcp-config.example.json) 的内容，
把 `${MCD_MCP_TOKEN}` 替换为**真实 Token 字面值**，保存 → 点【信任】→ 开启开关 → 重启 WorkBuddy。

> ⚠️ **三个会让连接器加载不出来的坑**
>
> | 坑 | 后果 | 对策 |
> |---|---|---|
> | 桌面端**不展开** `${MCD_MCP_TOKEN}` 占位符 | 会把 `Bearer ${MCD_MCP_TOKEN}` 原样发给服务器，**必然 401** | 配置里必须写真实 Token 字面值（占位符只对本 Skill 的脚本有效） |
> | `type` 写成 `streamablehttp` | 官方 README 给的是这个值，但桌面端源码只认 `stdio`/`sse`/`http` | 本仓库统一用 `http`，**连不上就改成 `http` 试试** |
> | PowerShell 写 JSON 带 UTF-8 BOM | 严格 JSON 解析报 `Unexpected UTF-8 BOM` | 用 `setup_mcp.ps1`（已规避），手写时用 `UTF8Encoding($false)` |
>
> 这三条在 `scripts/selftest.py` 里都有对应断言，回归时自动检查。

**为什么用凭据文件而不是把 Token 贴进对话**：
MCP Token 与你的麦当劳会员账号强绑定，等同于账号操作权限；
对话内容会经过第三方模型服务商处理，凭据文件则完全在你的机器上。
`scripts/selftest.py` 里有一项断言会**扫描整个仓库**，
确认不存在任何真实 Token 形态的字符串。

> 桌面端 `~/.workbuddy/mcp.json` 里的 Token 是**明文**存放的
> （该文件不在任何 git 仓库内，但请勿截图或分享该文件）。

### 3. 安装本 Skill

把 `skills/mcd-route/` 整个目录复制到 WorkBuddy 的用户技能目录：

```bash
cp -r skills/mcd-route ~/.workbuddy/skills/
```

装好后在对话框里直接说「**点外卖还是去店里更划算**」即可触发。

---

## 三种使用方式

> 这是一个 **Agent Skill**，不是一个网站或小程序。官方要的形态就是 Skill
> （「基于麦当劳 MCP 能力开发创意 Skill，开源到 GitHub」）。
> 但"怎么用"这件事有三种层次，都给你备好了。

### 方式 A · 在 WorkBuddy 里对话（正式形态，也是官方要的形态）

这是**唯一能拿到真实数据**的方式。装好 Skill + 连上 MCP 之后，
你在对话框里正常说话，它自己去调麦当劳的 Tool：

```
你：我晚上想吃麦当劳，点外送还是自己去店里？
```

它会依次调用 `query-nearby-stores` → `query-meals` → `query-store-coupons`
→ `calculate-price`，然后给你一个带数字的结论。

**真实调用过程**（2026-10-23 实采，可在
[`docs/index.html`](docs/index.html) 的「在 WorkBuddy 里，它长这样」看到）：

| Tool | 实参 | 返回 |
|---|---|---|
| `query-nearby-stores` | `city=北京, keyword=望京, beType=1` | 5 家门店，含 distance（米） |
| `query-meals` | `storeCode=1950980, orderType=1, beType=1` | 11 分类 118 款餐品 |
| `query-store-coupons` | `storeCode=1950980` | `data:[]`（该门店到店渠道无券） |
| `calculate-price` | 3 件商品 | `price=4350`（分）= ¥43.50 |

### 方式 B · 命令行跑决策（无需 Token也能跑通）

```bash
python skills/mcd-route/scripts/decider.py \
  --scenario skills/mcd-route/scripts/sample_data/scenario.json \
  --minute-cost 0.5
```

输出结构化 JSON，含 `verdict`（结论 + 理由）、`coupon_audit`（券体检）。
用 `sample_data/live_20261023.json` 可以跑出**真实数据**的决策。

### 方式 C · 打开在线试算页（零门槛，给评审和围观群众）

访问 `docs/index.html`（GitHub Pages 开启后就是一条链接），
拖动参数立刻看到结论。**不需要 Token、不联网、不收集任何东西。**

页面上有两个可切换的数据源：
- **样例数据**：虚构场景，演示算法
- **真实实采数据**：2026-10-23 原生 MCP 通道实采的那一组，
  点「载入真实实采数据」即可看到真实数字跑出来的结果

---

## 使用示例

**示例 1 · 最典型的场景**
> 用户：我晚上想吃麦当劳，点外送还是自己去店里？

渠道官：并行查 `delivery-query-stores` 与 `query-nearby-stores` → 两路分别查券 →
算价 → 「**建议到店自取**。到店那家 ¥32（门店券满40减15），
外送那家 ¥47（配送费 9 元被免配送费券抵掉），到手价差 15 元；
算上往返 28 分钟的时间成本后，仍净省 13.5 元。」

**示例 2 · 券的场景限制**
> 用户：我有一张 15 元券，用外送划算还是到店划算？

渠道官：券体检发现该券 `channel=pickup` → 「这张券**只能到店用**，外送场景用不了。
到店 ¥32，外送 ¥47——差的不只是配送费，是券本身。」

**示例 3 · 起送价拦住了**
> 用户：就买一个 12 元的甜筒，外送还是到店？

渠道官：查起送价 → 「外送起送价 20 元，**这单达不到**。到店自取，12 元。」
（诚实降级，不硬凑一个外送方案）

**示例 4 · 结论随你的时间观改变**
> 用户：钱一样的话哪个快？我一小时时薪 100 元，外送真划算吗？

渠道官：同一个购物篮，`--minute-cost 0` → 「到手价一样，外送等 25 分钟，
到店往返 28 分钟，**外送**更省事」；
`--minute-cost 1.67` → 「外送多花 25 分钟 ≈ 41.7 元，已超过 15 元的价差，
**真该自己去**。」

---

## 核心算法

### 决策式

```
到手总价 = 商品原价 − 可用券抵扣 + 配送费
总成本   = 到手总价 + 时间成本（分钟数 × 时间单价）
```

时间成本是**参数化**的，因为「时间值多少钱」因人而异。
这是本项目与「比价助手」的本质区别：结论不是「哪个便宜」，
而是「**哪个对我更划算**」。

### 三条保守计价原则

1. **只取单张最优券，不做券叠加** —— 避免报出实际无法成交的虚假低价。
2. **券的渠道限制严格生效** —— 到店券不进外送的计算，反之亦然。
3. **数据缺失就明说** —— 接口没返回配送费，本次不计入并显式声明，绝不估算。

### 券体检

逐张券给出三个口径，而不只是面额：

| 口径 | 含义 |
|---|---|
| 名义面额 | 券上写的金额 |
| 实际能用 | 门槛 + 渠道限制过滤后的结果 |
| 渠道归属 | 仅到店 / 仅外送 / 两边都能用 |

**实测里最容易亏的券不是「假券」，而是「小券挤掉大组合」**——
单看每张都在省钱，但用了它就吃不到更大的那档。

---

## 命令行快速体验（无需 Token）

```bash
cd skills/mcd-route/scripts

python decider.py --pretty                    # 看决策结果（内置样例数据）
python decider.py --minute-cost 1.67          # 调时间单价（0=不在乎时间）
python selftest.py                             # 跑 253 项自测
python parity_check.py                         # 对拍：页面与 CLI 是否一致（需 Node）

# 需 Token 的真实链路自检
python setup_token.py                          # 交互式配置 Token（不回显）
python mcp_probe.py                            # 四层连通性自检
python real_run.py                             # 端到端真实走查（12 次调用，全程只读）
```

**真实走查输出节选**（2026-10-22 实测）：

```
1) query-nearby-stores   → 5 家门店，含 distance=312m
2) query-meals            → 到店在售 118 款
3) query-store-coupons    → 2 张（JSON 格式）
4) query-my-coupons       → 2 张（Markdown 格式）
6) calculate-price 到店   → 商品 ¥22.5，无配送费无打包费
7) 外送侧                  → 配送费 ¥6.0 打包费 ¥2.8
8) 渠道决策                → 到店自取，净省 ¥7.30
9) 券体检                  → 11.9元券抵扣 ¥10.6（命中）；19.9元券抵扣 0（未命中）
```

---

## 真实性对照表

| 项目 | 性质 | 说明 |
|---|---|---|
| MCP 客户端握手 | ✅ **真实实测** | 协议 2025-06-18，服务器 `mcd-mcp` v1.0.0，35 个 Tool |
| **WorkBuddy 原生 MCP 通道** | ✅ **真实实测** | 通过连接器 `mcd-mcp`（`mcp__mcd-mcp__*`）实调 4 个 Tool 成功，见 `sample_data/live_20261023.json` |
| 端到端链路走查 | ✅ **真实实测** | `real_run.py` 12 次真实调用跑通，**全程只读** |
| 渠道计价与对比 | ✅ 真实 | `decider.py` 纯标准库实现，253 项自测覆盖各决策分支 |
| 页面与 CLI 一致 | ✅ 真实 | `parity_check.py` 逐场景对拍两端（56 项比对），防止两份实现漂移 |
| 真实数据回归 | ✅ **真实实测** | 24 项断言锁定真实接口契约，见 `sample_data/real_snapshot.json` |
| **两次独立采集交叉验证** | ✅ **真实实测** | 10-22 脚本采集 vs 10-23 原生通道采集，到店核价返回字段集完全一致 |
| 「到店省 7.30 元」结论 | ✅ **真实算出** | 真实数据跑出的结果：到店 ¥11.90 / 外送 ¥20.70 |
| 配送费与打包费 | ✅ **真实实测** | 外送核价返回 `deliveryPrice=600`、`packingPrice=280`（单位：分） |
| 券的抵扣额 | ✅ **真实实测** | 麦辣鸡腿汉堡 ¥22.5，券价 ¥11.9 → 抵扣 ¥10.6 |
| 门店距离 | ✅ **真实实测** | `query-nearby-stores` 返回 `distance=312`（米） |
| 券池内容 | 🟡 随账号变动 | 券是账号资产，随活动变化；结构真实，内容会变 |
| 到店往返时间 | 🟡 经验值 | 往返 20 分钟为经验值；**距离本身是接口真实返回的**，可据此推算 |
| 下单能力 | ✅ 真实 | 经 MCP 核价 → 下单（`create-order`），**本仓库脚本不下单** |

---

## 🔐 你的 Token 与个人信息安全

> 评审一定会问：**「我把 Token 放进去，会不会被人爬走？」**
> 这个问题不用你信我的说法 —— 下面每一条都是可复现的验证。

### 你的 Token 不会随仓库泄露

| 防护层 | 做法 | 验证方式 |
|---|---|---|
| 仓库内 | 只有 `Bearer ${MCD_MCP_TOKEN}` 占位符 | 自测断言扫全仓库 |
| **git 全历史** | 每个提交逐个 diff 扫描 | `git log --all -p` 全量 grep，**0 处真实 Token** |
| 本地存放 | `~/.workbuddy/.mcd_token`（不在任何 git 仓库内） | 路径断言 |
| 桌面端配置 | `~/.workbuddy/mcp.json`（明文，但在仓库外） | 路径断言 |
| 写入方式 | `setup_token.py` / `setup_mcp.ps1` 交互式写入 | `getpass` 不回显，**Token 不经过对话** |

脚本按优先级读取：`显式传参` > `环境变量 MCD_MCP_TOKEN` > `~/.workbuddy/.mcd_token`。

**clone 之后配你自己的 Token**（这也是「任何人都能用自己的 Token 跑」的含义）：

```bash
git clone https://github.com/Seing-yu/mcd-route.git
cd mcd-route/skills/mcd-route/scripts

# 到 https://open.mcd.cn/mcp 手机号登录 → 控制台 → 激活，拿到你自己的 Token
python setup_token.py          # 交互式输入，不回显，写入 ~/.workbuddy/.mcd_token
python real_run.py             # 用【你自己的】账号跑真实链路
```

### 这个项目没有服务器，也没有数据出口

它不是"网站"，是一堆**跑在你自己机器上的文件**。
**无服务端、无数据库、无上传接口**（全仓库无 `flask`/`fastapi`/`express`/db 命中）。

| 环节 | 数据流向 | 谁能拿到 |
|---|---|---|
| Token | `~/.workbuddy/` → `mcp.mcd.cn` 请求头 | 只有麦当劳服务器 |
| 你的地址 | 你**主动**给 → `mcp.mcd.cn` | 只有麦当劳服务器 |
| 门店/菜单/价格 | `mcp.mcd.cn` → 本地内存 | 无人 |
| 试算页 | **全部计算在浏览器本地**，零 `fetch`、零外部 `<script>` | 无人 |
| 样例数据 | 硬编码在仓库里 | 所有人（本来就不是隐私） |

**结构上不存在「接收别人凭据」的接口**：唯一涉及 Token 的入口是本地终端脚本（不经过浏览器）；
`delivery-query-addresses` 是**麦当劳官方 MCP 的 Tool**，本项目只调用、不实现，地址也不落盘。
别人 fork 你的仓库，他的 Token 存进**他自己的** `~/.workbuddy/`，与你的完全隔离。

### 配送地址：不会主动向你索取

查外送需要 `addressId`（属个人数据）。拿不到时，Skill 只做到店侧，
并在结论里明说"外送侧未采集，原因是什么"，**不会用猜测值凑一个方案**。

官方规则第五条要求「请勿在与 AI 的对话中输入 MCP Token」——
本项目从设计上遵守：Token 走本地文件，**不进入对话、不经过第三方模型服务商**。

> **一句话总结**：没有中心，没有服务器，没有数据出口。
> 你的 Token 从你的机器直接到麦当劳服务器，中间不经过任何人 —— 包括我。

---

## 费用与合规

### 费用

| 项目 | 规则 |
|---|---|
| 平台接入费 | **免费**，无接入服务费、无企业付费套餐（官方 FAQ 原文："No charge"） |
| Token 申请 | 手机号登录即领，免费 |
| 调用限流 | 600 次/分钟/Token，超出返回 429 |
| 实际产生消费的操作 | 仅 `create-order`（付款在官方 APP 完成）、`mall-create-order`（扣积分）、`draw-lottery`（耗积分） |
| 其余 31 个 Tool | 全部为只读查询，不产生任何费用或权益变动 |

> 唯一的真实成本是你自己的餐饮消费与积分消耗。

### 《麦当劳 MCP 服务规则》遵循说明

本项目完整对照《麦当劳 MCP 服务规则》（版本日期 2025-12-03）执行，
原文快照存档于 [`docs/mcp-rules-20251203.html`](docs/mcp-rules-20251203.html)。

规则第六条禁止「利用脚本、爬虫或任何自动化工具调用本服务」，
第三条要求「仅面向个人正常使用场景，不支持任何形式的批量、高频或自动化调用」。
本项目的立场与实现如下：

| 规则要求 | 本项目做法 |
|---|---|
| 个人非商业用途（第一条第 2 项） | 参赛作品，非商业分发；不含任何引流变现 |
| 禁止批量/自动化调用（第三条第 2 项） | **代码级护栏**：单次会话调用上限 120 次（远低于官方 600/分钟 限流），超出即抛 `ComplianceError` 拒绝执行 |
| 禁止高频调用（第三条第 2 项） | **强制限速**：两次调用间隔 ≥ 0.35 秒，节奏为交互式而非压测式 |
| 凭证不得分享/公开（第二条第 2 项） | Token 从不进入对话；`setup_token.py` 交互式写入 `~/.workbuddy/.mcd_token`（用户主目录，权限 600）；仓库内只有 `${MCD_MCP_TOKEN}` 占位符；自测含**全仓库 Token 扫描**断言 |
| 禁止代下单/代领券牟利（第六条第 1 项） | 不提供任何代领券、倒卖、转售功能；`create-order` 仅在用户明确确认后建单，**付款由用户在官方 APP 完成** |
| 最小必要数据原则（第三条第 1 项） | 只调用渠道决策所必需的 Tool；不读取与决策无关的订单、积分、商城数据 |
| 隐私（第五条） | 不在对话中索取 Token/密码/证件号；地址等个人数据不完整复述到输出 |
| 免责（第四条） | README 与 SKILL.md 均声明：AI 生成内容不保证准确，一切以麦当劳 APP 显示为准 |

**调用模式说明**：本项目的 MCP 调用是**人在对话中发起、Agent 按需少量取数**的交互式调用，
与规则禁止的「无人值守批量爬取」有本质区别——
每次调用都对应用户的一个具体问题，调用次数受上述配额硬约束。

---

## 参赛合规自查

对照《麦当劳程序员节创意开发大赛活动规则》逐条自查：

| 规则要求 | 本仓库情况 |
|---|---|
| 仓库创建时间在 2025-12-25 ~ 2026-10-25 之间 | ✅ |
| 仓库公开可访问 | ✅ public |
| `README.md`（介绍 / 安装 / 使用示例 / 目标用户） | ✅ 四个部分均有独立章节 |
| `CONTEST_DECLARATION.md` | ✅ 与官方原文**逐字节一致**，未作任何改写 |
| `MCP_INTEGRATION.md`（Server / Tool / 调用流程 / 业务价值） | ✅ 见该文件 |
| `mcp-config.example.json`（只允许环境变量占位符） | ✅ 仅 `Bearer ${MCD_MCP_TOKEN}` |
| `workbuddy.md`（WorkBuddy 专项） | ✅ 含开发环境、时间线、协作方式与已知边界 |
| 源代码 | ✅ `skills/mcd-route/scripts/` |
| 真实使用麦当劳 MCP | ✅ 原生连接器 `mcd-mcp` 实调 4 个 Tool（`mcp__mcd-mcp__*`），快照见 `sample_data/live_20261023.json`；`mcp_probe.py` 可复现握手 + tools/list + 调用 |
| 真实使用 WorkBuddy | ✅ 本项目全程在 WorkBuddy 中开发，过程见 `workbuddy.md` |
| 未包含真实 Token / 密钥 | ✅ 全仓库仅含环境变量占位符 |
| 内容合规 | ✅ 中性表述，不与其它品牌对比，不贬损麦当劳 |

---

## 目标用户

- **公司 / 学校周边中午纠结的外卖党**：算不清外送到底贵多少。
- **离门店很近的人**：配送费往往比跑一趟还贵，但很少有人去比。
- **优惠券囤了一堆的人**：不知道哪张券在哪个渠道能用。
- **赶时间的人**：愿意用时间换钱，或反过来。

---

## 目录结构

```
.
├── README.md                    # 本文件
├── CONTEST_DECLARATION.md       # 参赛声明（官方原文，未改动）
├── MCP_INTEGRATION.md           # Tool 清单 / 调用流程 / 业务价值 / 规则对照
├── mcp-config.example.json      # 脱敏 MCP 配置（仅环境变量占位符）
├── workbuddy.md                 # WorkBuddy 开发对话上下文
├── docs/
│   ├── index.html               # ← 在线试算页（单文件，零外部依赖）
│   ├── 推广物料.md               # 冲 Star 用素材
│   └── mcp-rules-20251203.html  # 官方 MCP 服务规则存档（纯文本离线版）
└── skills/mcd-route/            # ← Skill 本体
    ├── SKILL.md                 # 技能指令（Agent 加载）
    ├── scripts/
    │   ├── mcp_client.py        # 纯标准库 MCP 客户端（握手/工具/调用/合规护栏）
    │   ├── decider.py           # 决策引擎：计价、对比、券体检、单位归一化
    │   ├── selftest.py          # 253 项自测
    │   ├── parity_check.py|.mjs # 前后端对拍（页面 vs CLI）
    │   ├── setup_token.py       # 交互式配置 Token（不回显）
    │   ├── setup_mcp.ps1        # Windows 一键写入连接器配置
    │   ├── mcp_probe.py         # 连通性自检（四层）
    │   └── sample_data/         # 样例 + 两份真实接口快照
    └── references/mcp-tools.md  # Tool 清单、字段映射、金额单位契约
```

---

## 技术亮点

- **纯标准库 MCP 客户端** —— 不装 `mcp` 包，零依赖，clone 即可跑。
- **确定性算术** —— 所有金额由代码计算或 MCP 返回，大模型不口算价格。
- **时间成本参数化** —— 结论随用户的时间价值观变化，而非固定答案。
- **券的场景建模** —— 建模 `channel` 字段，解决「券用不了」这个真实痛点。
- **保守计价** —— 不叠加券、不猜价格，宁可少报优惠也不给假低价。
- **诚实降级** —— 起送价未达标、距离不可得、字段缺失，都有明确的降级说明。
- **253 项自测** —— 覆盖券可用性、选券策略、计价、决策分支、字段归一化、金额单位契约、合规护栏、静态页无外发、**长数字标识符**、**个人位置地标**十类。
- **前后端对拍** —— 在线试算页与 CLI 是同一套逻辑，逐场景比对 56 项，防止漂移。

---

## 搜索关键词

<details>
<summary>🔍 想用哪些词搜到本项目？（点开查看）</summary>

**中文**：麦当劳 · 麦门 · 麦当劳外卖 · 麦当劳外送 vs 到店 · 麦当劳点哪个划算 ·
配送费 · 起送价 · 优惠券渠道 · 门店券 · 外卖贵不贵 · 自取 · 到店自取 ·
渠道决策 · 时间成本 · 麦当劳程序员创意开发大赛 · WorkBuddy 技能 · Agent Skill

**English**: McDonald's / McDonalds China / MCD · MCP (Model Context Protocol) ·
mcd-mcp · delivery vs pickup · delivery fee · min order · coupon channel ·
channel decision · time cost · food delivery arbitrage · WorkBuddy skill · AI agent

</details>

---

## 免责声明

本项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，**非麦当劳官方产品**。
项目输出仅供参考，不构成医疗、营养或其他专业建议；餐品信息、价格及供应状态
以麦当劳官方渠道的实时结果为准。使用麦当劳 MCP 服务须遵守其《使用条款》与
《麦当劳 MCP 服务规则》。

## 许可

MIT License（见 [LICENSE](LICENSE)）。
