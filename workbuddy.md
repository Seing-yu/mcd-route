# WorkBuddy 开发对话上下文

本文件记录本项目**在腾讯 WorkBuddy 中从零开发**的完整上下文，
用于《麦当劳程序员节创意开发大赛活动规则》中
「如参与 WorkBuddy 专项奖励的，参赛项目须真实使用腾讯 WorkBuddy 智能体」
与「`workbuddy.md`：WorkBuddy 对话上下文，用于核验是否符合联动活动奖励条件」的核验要求。

---

## 一、开发环境

| 项 | 值 |
|---|---|
| 智能体 | 腾讯 WorkBuddy（官方合作伙伴身份） |
| 开发方式 | 对话式协作开发，AI 负责调研、设计、编码、测试、文档产出 |
| 运行环境 | Windows / PowerShell + Git Bash |
| 语言与运行时 | Python 3.13（**仅标准库，零第三方依赖**） |
| MCP Server | 麦当劳中国官方 MCP Server（`https://mcp.mcd.cn`，Streamable HTTP） |
| 产物形态 | WorkBuddy Agent Skill（`SKILL.md` + `scripts/` + `references/`） |
| MCP 客户端 | 自研 `scripts/mcp_client.py`，纯标准库实现 initialize / tools/list / tools/call |
| 交付物 | GitHub 公开仓库（Public），含 6 份必交文件 |

---

## 二、开发时间线

### 阶段 1 · 活动解读与赛道摸底

**任务**：确认比赛规则、奖励结构、报名路径，判断做什么方向有胜算。

**关键发现**（均以官方仓库与实时榜单为依据）：

1. 规则原文（`activityGuidelines.md`）明确：**排名完全按 GitHub 公开 Star 数**，
   代码质量只决定「别人值不值得 star」。
2. 奖励分层：
   - 前 3 名：巨无霸兑换券 + 10240 WorkBuddy 积分
   - 排行榜前 100 名：汉堡回车键 + 程序员节徽章
   - 前 100 名且真实使用 WorkBuddy（提交 `workbuddy.md`）：额外 3000 积分
3. 必交文件共 5 份（`README.md` / `CONTEST_DECLARATION.md` / `MCP_INTEGRATION.md` /
   `mcp-config.example.json` / 源代码），参加 WorkBuddy 专项奖励还需 `workbuddy.md`。
4. 官方仓库只有 5 个文件，**`mcp-config.example.json` 无官方模板，需自建**。
5. 报名 Issue 有格式校验：标题与正文之间、正文各字段之间**不得换行**，
   项目地址**不得使用 Markdown 链接格式**。
6. 实时榜单（2026-10-22 14:00 快照）已有 101 个项目进榜，
   第 1 名 893 star，第 100 名 32 star——**进前 100 的门槛约 32+ star**。

**赛道分析**：以实时榜单 101 个项目为样本做归类，发现已高度拥挤的方向：

| 已扎堆方向 | 头部项目举例 |
|---|---|
| 省钱 / 券组合优化 | `mcd-saver-strategist`(893)、`mcd-coupon-strategist`(810)、`mcd-budget-meal`(808) |
| 卡路里 / 营养配餐 | `mcd-calorie-butler`(149)、`walk-kcal`(154)、`mcd-fit-coach` |
| MBTI / 人格标签 | `mcd-persona-card`、`mcd-receipt-persona`、`mcd-mood-palette` |
| 塔罗 / 玄学 | `mcd-tarot`、`mcd-fortune`、`mcd-mbti` |
| 派对 / 活动策划 | `mcd-party-planner`(791)、`mcd-party-officer` |
| 积分抽奖 / 扭蛋 | `mcd-gacha-collector`、`McLottery-Alchemist` |
| 碳足迹 | `mccarbon`(710) |

**结论与选题**：全部 MCP Tool 的使用频次统计显示，
`delivery-*`（配送地址 / 可配送门店）与 `query-nearby-stores`（附近门店）
这一组**几乎没被任何头部项目使用**——榜单前列项目基本都在做「同一家店里怎么点最便宜」，
而**「这一顿该点外送还是到店自取」是一个被系统性忽略的真实决策**。

于是定题：**麦门渠道官 McRoute**——外送 vs 到店的渠道决策器。

### 阶段 2 · 技术选型

**决策：纯标准库实现 MCP 客户端，不 `pip install mcp`。**

理由：
1. 参赛作品强调「clone 下来就能跑」，零依赖是硬优势；
2. MCP 的 Streamable HTTP 传输层本质是「POST JSON-RPC + 解析 JSON/SSE 响应」，
   标准库已完全覆盖；
3. 少一个安装环节，评审时少一道坎。

**协议细节确认**：
- POST `https://mcp.mcd.cn`，头 `Authorization: Bearer <TOKEN>`，
  `Accept: application/json, text/event-stream`
- 握手顺序：`initialize` → 取响应头 `Mcp-Session-Id` → `notifications/initialized` → `tools/call`
- 后续请求带上协商出的 `MCP-Protocol-Version`
- 响应可能是 `application/json`，也可能是 SSE（`data:` 行），客户端两种都要能解

### 阶段 3 · 算法设计

这是本项目的核心，也是与「再做一个省钱助手」拉开差距的地方。

**问题建模**：外送与到店的差异远不止「配送费」这一项：

| 变量 | 外送 | 到店 |
|---|---|---|
| 配送费 | 有，随距离与时段浮动 | 无 |
| 起送价 | 有硬门槛，未达标不可下单 | 无 |
| 券可用性 | 部分门店券**不可用** | 部分券**仅到店可用** |
| 券绑定关系 | 绑**可配送门店** | 绑**附近门店** |
| 时间成本 | 等餐时间 | 往返路程 + 出餐时间 |

**决策式**：

```
到手总价 = 商品原价 − 可用券抵扣 + 配送费
总成本   = 到手总价 + 时间成本（时间分钟数 × 用户给的时间单价）
```

**关键设计取舍（保守计价）**：
- 只选**单张最优券**，不做券叠加——避免报出实际无法成交的虚假低价；
- 券的渠道限制严格生效，宁可少报优惠，不报假低价；
- 数据缺失时**诚实降级**：接口没返回配送费就明说「本次未计入」，不估算。

**时间成本参数化**：`--minute-cost` 默认 0.5 元/分钟（30 元/小时），
用户明确表示「不在乎时间」时传 0，「我时间很贵」时调高。
这一项让结论从「哪个便宜」升级为「哪个对我更划算」。

### 阶段 4 · 编码与自测

**产出**：
- `scripts/mcp_client.py` — MCP 客户端（握手 / 工具列表 / 调用 / SSE 与 JSON 双解析 / 401 与 429 处理）
- `scripts/decider.py` — 决策引擎（渠道计价、对比、券体检、购物篮构建）
- `scripts/selftest.py` — **46 项断言**的自测套件
- `scripts/mcp_probe.py` — 四层连通性自检（协议 / 工具 / 业务）
- `scripts/sample_data/scenario.json` — 离线样例，**无需 Token 即可跑通全流程**

**测试驱动的三次修正**（全部由自测套件暴露）：

1. **脏数据未被过滤** —— `build_basket` 把无编码的条目也收了进来。
   修正：跳过无 `code` 的条目（无法参与后续核价）。
2. **金额格式化负号位置错误** —— 输出出现 `少 ¥-15`。
   修正：`money()` 分离符号与数值，负号统一前置。
3. **决策理由文案有误导** —— 原文案「算上时间成本后，仍省 ¥13.50」
   在时间成本已计入的前提下表述含混。
   修正：拆成「到手价差 ¥15」+「计入时间成本后仍净省 ¥13.50」两句。

> 这三轮修正是本项目开发过程最有价值的部分：它们证明了
> **自测套件不是摆设，而是真的在约束行为**。

**自测覆盖的分支**（46 项）：
金额格式化 3 项 / 券可用性 5 项 / 选券策略 5 项 / 渠道计价 6 项 /
字段归一化 7 项 / 决策分支 11 项 / 券体检 4 项 / 购物篮 5 项。

**决策分支测试用例**：
两渠道均可用、仅外送可用、仅到店可用、两渠道均不可用、
起送价未达标、无券基线、高配送费、长往返导致结论翻转、
到手价几乎持平时的降级表述。

**验证结果**：
```
自测结果：46 通过，0 失败
✅ 全部通过
```

### 阶段 5 · 文档与合规

**对照活动规则逐条自查**（结果见 `README.md` 的「参赛合规自查」表）：
- `CONTEST_DECLARATION.md` **逐字节取用官方原文，未作任何改写**
  （第一次起草时曾将末段「如因此给麦当劳造成损失的」改写为
  「如因此给赛事组织者造成损失的」，自查时发现并已回改为官方原文）
- `mcp-config.example.json` 仅含 `Bearer ${MCD_MCP_TOKEN}` 环境变量占位符
- 全仓库无真实 Token / 密钥 / 个人住址
- 内容中性表述，不与其他品牌对比，不贬损麦当劳

---

## 三、与 WorkBuddy 的协作方式

本项目在 WorkBuddy 中完成以下工作，均由 AI 执行并可复现：

| 环节 | WorkBuddy 承担的工作 |
|---|---|
| 规则调研 | 抓取并交叉核对官方 README、`activityGuidelines.md`、`CONTEST_DECLARATION.md`、实时 `RANKING.md`，输出可执行的规则摘要 |
| 赛道分析 | 遍历 101 个进榜项目名与描述，统计 Tool 使用方向，定位空白赛道 |
| 协议调研 | 确认 MCP Streamable HTTP 的握手顺序、请求头、响应格式与错误码 |
| 编码 | 实现 MCP 客户端、决策引擎、自测套件、连通自检 |
| 测试 | 编写并运行 46 项断言，驱动 3 次修正 |
| 文档 | 产出 6 份必交文件中的 5 份（本文件除外为对话记录） |
| 排错 | 定位并修复 JSON 重复键、Python 沙箱网络限制、金额格式化与文案逻辑问题 |

**WorkBuddy 的角色是「完整实现 + 可验证」**：所有金额由确定性算法计算
（`decider.py`），所有 MCP 数据可由 `mcp_probe.py` 现场复现，
不存在「AI 编一个看起来合理的结果」的情况。

---

## 四、已知边界

诚实记录本项目的局限，不回避：

1. **距离为估算**：MCP 的门店接口不返回用户到门店的距离，
   时间成本中的往返分钟数按距离分档估算（`DISTANCE_MINUTES`）。
   这是接口能力的边界，已在 `SKILL.md` 的诚实降级表中说明。
2. **未做券叠加**：为避免虚假低价，只取单张最优券。
   真实最优解可能需要组合，本项目**刻意**不做。
3. **配送费依赖 `calculate-price`**：该接口的返回是唯一可信来源；
   若其返回中缺少配送费字段，本次计算不计入配送费并显式声明。
4. **真实 Token 联调待完成**：`mcp_probe.py` 的实测记录将在获得 Token 后补入
   `references/mcp-tools.md` 第七节。

---

## 五、复现方式

```bash
# 1. 装依赖（零依赖，仅需 Python 3.8+）
git clone <本仓库>
cd mcd-route/skills/mcd-route/scripts

# 2. 离线跑通完整决策（无需 Token）
python decider.py --pretty
python selftest.py

# 3. 配置 MCP Token 后验证真实数据链路
export MCD_MCP_TOKEN=你的token
python mcp_probe.py
python mcp_probe.py --call query-nearby-stores --args '{"address":"北京市朝阳区"}'
```

---

*本项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，非麦当劳官方产品。*
*项目输出仅供参考，不构成医疗、营养或其他专业建议；餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准。*
