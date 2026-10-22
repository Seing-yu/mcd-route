# 麦门渠道官 · McRoute

> 基于 **麦当劳中国 MCP（McDonald's China MCP）** 开发的**渠道决策** Skill：
> 回答一个被所有点餐助手忽略的问题——**这一顿，点外送还是到店自取？**
>
> 麦当劳程序员创意开发大赛参赛作品 · 非麦当劳官方产品。

![Python](https://img.shields.io/badge/python-3.8%2B-blue) ![零依赖](https://img.shields.io/badge/dependencies-0-brightgreen) ![自测](https://img.shields.io/badge/selftest-119%20passed-success) ![License](https://img.shields.io/badge/license-MIT-green)

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

Token 申请地址：<https://open.mcd.cn/mcp>（手机号登录 → 右上角「控制台」→「激活」）。

**推荐：交互式写入本地凭据文件（Token 不经过对话、不进入仓库）**

```bash
cd skills/mcd-route/scripts
python setup_token.py
```

脚本会提示你粘贴 Token（**输入不回显**），写入 `~/.workbuddy/.mcd_token`
（用户主目录，不在任何 git 仓库内，权限 600）。

也可以直接设置环境变量：

```bash
export MCD_MCP_TOKEN=你的token   # macOS / Linux
set MCD_MCP_TOKEN=你的token      # Windows
```

**在 WorkBuddy 里使用**：左侧边栏【专家·技能·连接器】→【连接器】→
右上角【自定义连接器】→【配置 MCP】，填入
[`mcp-config.example.json`](mcp-config.example.json) 的内容，
把 `${MCD_MCP_TOKEN}` 替换为你的真实 Token，保存 → 点【信任】→ 开启开关。

**Windows 一键配置（推荐，Token 不经过对话）**：

```powershell
powershell -ExecutionPolicy Bypass -File .\skills\mcd-route\scripts\setup_mcp.ps1
```

脚本会从 `~/.workbuddy/.mcd_token` 读 Token → 备份原 `mcp.json` →
写出新配置 → 校验 JSON 与编码，全程**不回显 Token**。

> 🪟 **两个 Windows 编码坑（脚本已规避，但你手写配置时会踩）**
>
> | 坑 | 后果 | 对策 |
> |---|---|---|
> | `Set-Content -Encoding UTF8` 写入 **BOM** | WorkBuddy 严格 JSON 解析，报 `Unexpected UTF-8 BOM`，连接器加载不出来 | 用 `UTF8Encoding($false)` 写；或直接用 `setup_mcp.ps1` |
> | `.ps1` 存成**无 BOM** UTF-8 | PowerShell 5.1 按 ANSI 解码，脚本里的中文注释乱码 | `.ps1` 存成 **UTF-8 with BOM**（仓库里这份已带 BOM） |
>
> 这两条都在 `scripts/selftest.py` 里有对应断言，回归时自动检查。

> ⚠️ **WorkBuddy 桌面端不会展开 `${MCD_MCP_TOKEN}` 这类环境变量占位符。**
> 它只会把字符串原样塞进请求头（实测：占位符会变成
> `Bearer ${MCD_MCP_TOKEN}` 发给服务器，必然 401）。
> 所以桌面端配置里必须写**真实 Token 字面值**。
> 环境变量占位符只对**本 Skill 自带的脚本**有效
> （`mcp_client.py` 自己解析 `MCD_MCP_TOKEN` 与 `~/.workbuddy/.mcd_token`），
> 仓库里的 `mcp-config.example.json` 保留占位符是为了**不泄露真实 Token**，
> 供他人复制时替换用。
>
> **为什么推荐用凭据文件而不是把 Token 贴进对话**：
> MCP Token 与你的麦当劳会员账号强绑定，等同于账号操作权限。
> 对话内容会经过第三方模型服务商处理，凭据文件则完全在你的机器上。
> `scripts/selftest.py` 里有一项断言会**扫描整个仓库**，
> 确认不存在任何真实 Token 形态的字符串。
>
> 桌面端 `~/.workbuddy/mcp.json` 里的 Token 是**明文**存放的
> （该文件不在任何 git 仓库内，但请勿截图或分享该文件）。

### 3. 安装本 Skill

把 `skills/mcd-route/` 整个目录复制到 WorkBuddy 的用户技能目录：

```bash
cp -r skills/mcd-route ~/.workbuddy/skills/
```

装好后在对话框里直接说「**点外卖还是去店里更划算**」即可触发。

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

**示例 4 · 我不在乎时间**
> 用户：钱一样的话哪个快？

渠道官：`--minute-cost 0` → 「到手价一样，外送等 25 分钟，到店往返 28 分钟。
按你不在乎时间算，**外送**更省事。」

**示例 5 · 我时间很贵
> 用户：我一小时的时薪 100 元，外送真划算吗？

渠道官：`--minute-cost 1.67` → 时间成本被放大，
「外送多花 25 分钟 ≈ 41.7 元，已经超过 15 元的价差，**真该自己去**。」

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

内置样例数据，可离线跑通完整决策流程：

```bash
cd skills/mcd-route/scripts

# 看决策结果
python decider.py --pretty

# 调整时间单价（0 = 不在乎时间；1.67 ≈ 时薪100元）
python decider.py --minute-cost 0
python decider.py --minute-cost 1.67

# 跑 119 项自测（改逻辑后必跑）
python selftest.py

# 前后端对拍：验证在线试算页与 CLI 结果一致（需 Node）
python parity_check.py

# 真实 MCP 连通自检（需 Token，证明数据链路是真的）
python setup_token.py      # 交互式配置 Token（不回显）
python mcp_probe.py

# 端到端真实走查（12 次真实调用，全程只读，不下单不领券）
python real_run.py
python real_run.py --city 北京 --keyword 望京
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
| 端到端链路走查 | ✅ **真实实测** | `real_run.py` 12 次真实调用跑通，**全程只读** |
| 渠道计价与对比 | ✅ 真实 | `decider.py` 纯标准库实现，119 项自测覆盖各决策分支 |
| 页面与 CLI 一致 | ✅ 真实 | `parity_check.py` 逐场景对拍两端（56 项比对），防止两份实现漂移 |
| 真实数据回归 | ✅ **真实实测** | 24 项断言锁定真实接口契约，见 `sample_data/real_snapshot.json` |
| 「到店省 7.30 元」结论 | ✅ **真实算出** | 真实数据跑出的结果：到店 ¥11.90 / 外送 ¥20.70 |
| 配送费与打包费 | ✅ **真实实测** | 外送核价返回 `deliveryPrice=600`、`packingPrice=280`（单位：分） |
| 券的抵扣额 | ✅ **真实实测** | 麦辣鸡腿汉堡 ¥22.5，券价 ¥11.9 → 抵扣 ¥10.6 |
| 门店距离 | ✅ **真实实测** | `query-nearby-stores` 返回 `distance=312`（米） |
| 券池内容 | 🟡 随账号变动 | 券是账号资产，随活动变化；结构真实，内容会变 |
| 到店往返时间 | 🟡 经验值 | 往返 20 分钟为经验值；**距离本身是接口真实返回的**，可据此推算 |
| 下单能力 | ✅ 真实 | 经 MCP 核价 → 下单（`create-order`），**本仓库脚本不下单** |

---

## 🔐 任何人都能用你自己的 Token 跑

**这个问题评审一定会问，所以做成了可验证的事实。**

开发者联调时用的是自己的 MCP Token，但那**只存在于开发者的机器上**：

```
C:\Users\<你>\.workbuddy\.mcd_token      ← 你的机器，不在仓库里
```

仓库里**没有任何真实凭据**。脚本按优先级读取：

| 优先级 | 来源 | 适用场景 |
|---|---|---|
| 1 | 显式传参 `McpClient(token=...)` | 一次性调试 |
| 2 | 环境变量 `MCD_MCP_TOKEN` | CI、临时使用 |
| 3 | 本地凭据文件 `~/.workbuddy/.mcd_token` | 本机日常使用 |

**你 clone 之后，只需配自己的 Token：**

```bash
git clone https://github.com/Seing-yu/mcd-route.git
cd mcd-route/skills/mcd-route/scripts

# 到 https://open.mcd.cn/mcp 手机号登录 → 控制台 → 激活，拿到你自己的 Token
python setup_token.py          # 交互式输入，不回显，写入 ~/.workbuddy/.mcd_token

python real_run.py              # 用【你自己的】账号跑真实链路
```

### 这件事是被验证过的，不是承诺

| 验证项 | 结果 |
|---|---|
| 全仓库扫描真实 Token | ✅ 0 处命中 |
| git 全部历史扫描 | ✅ 0 处命中 |
| 配置示例内容 | ✅ 仅 `Bearer ${MCD_MCP_TOKEN}` |
| 无 Token 时运行 | ✅ 返回空并提示申请，**不报错、不回退** |
| 换 Token 后运行 | ✅ 请求头换成你自己的 |
| 个人信息扫描 | ✅ 无手机号 / 身份证 / 邮箱（官方规则快照除外） |
| **固化为自测断言** | ✅ **8 项，随 CI 自动检查** |

> 也就是说：**「不含开发者凭据」这件事由 CI 守着**，将来任何人误提交真 Token，CI 会立刻失败。

### 隐私处理

| 数据 | 处理 |
|---|---|
| Token | 只在你的机器上，仓库内仅占位符 |
| 配送地址、电话 | 真实快照中已替换为「示例门店 A/B」 |
| 门店位置 | 真实快照已中性化；**但 `real_run.py` 与 `SKILL.md` 保留「望京」作为接口调用示例**——麦当劳北京望京店是公开门店，任何人都能照着跑通 |

> 保留示例位置是有意的：它是**可复现的调用示例**，不是隐私。

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
| 真实使用麦当劳 MCP | ✅ `mcp_probe.py` 可复现握手 + tools/list + 调用 |
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
├── README.md                      # 本文件
├── CONTEST_DECLARATION.md         # 参赛声明（官方原文，未改动）
├── MCP_INTEGRATION.md             # MCP 集成说明：Tool 清单 / 调用流程 / 业务价值 / 规则对照
├── mcp-config.example.json        # 脱敏 MCP 配置（仅环境变量占位符）
├── workbuddy.md                   # WorkBuddy 开发对话上下文
├── LICENSE                        # MIT
├── docs/
│   ├── index.html                 # ← 在线试算页（单文件，零外部依赖）
│   ├── 推广物料.md                 # 冲 Star 用：长文骨架 / 短文案 / 话术 / 节奏表
│   └── mcp-rules-20251203.html    # 官方 MCP 服务规则原文快照
└── skills/mcd-route/              # ← Skill 本体
    ├── SKILL.md                   # 技能指令（Agent 加载）
    ├── scripts/
    │   ├── mcp_client.py          # 纯标准库 MCP 客户端（握手/工具列表/调用/合规护栏）
    │   ├── decider.py             # 决策引擎：渠道计价、对比、券体检、单位归一化
    │   ├── selftest.py            # 127 项自测
    │   ├── parity_check.py        # 前后端对拍（页面 vs CLI）
    │   ├── parity_check.mjs       # 前端计算引擎抽取器
    │   ├── setup_token.py         # 交互式配置 Token（不回显，不进对话）
    │   ├── setup_mcp.ps1          # Windows 一键写入 WorkBuddy 连接器配置（无 BOM）
    │   ├── mcp_probe.py           # MCP 连通性自检（四层）
    │   └── sample_data/
    │       └── scenario.json      # 离线样例，无需 Token 即可跑通
    └── references/
        └── mcp-tools.md           # Tool 清单、字段映射、金额单位契约、实测记录
```

---

## 技术亮点

- **纯标准库 MCP 客户端** —— 不装 `mcp` 包，零依赖，clone 即可跑。
- **确定性算术** —— 所有金额由代码计算或 MCP 返回，大模型不口算价格。
- **时间成本参数化** —— 结论随用户的时间价值观变化，而非固定答案。
- **券的场景建模** —— 建模 `channel` 字段，解决「券用不了」这个真实痛点。
- **保守计价** —— 不叠加券、不猜价格，宁可少报优惠也不给假低价。
- **诚实降级** —— 起送价未达标、距离不可得、字段缺失，都有明确的降级说明。
- **119 项自测** —— 覆盖券可用性、选券策略、计价、决策分支、字段归一化、金额单位契约、合规护栏七类。
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
