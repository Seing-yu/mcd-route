---
name: mcd-route
display_name: 麦门渠道官
display_name_en: McRoute
description: 麦当劳中国 MCP 渠道决策助手。回答「这一顿，点外送还是到店自取更划算」。当用户说「点外卖还是去店里」「外送贵不贵」「自取省多少钱」「帮我比一下外送和到店」「今天适合点外卖吗」时使用。基于真实麦当劳 MCP 数据计算到手价与时间成本，输出可执行建议。
description_zh: 回答「这一顿该点外送还是到店自取」的渠道决策助手，基于真实麦当劳 MCP 数据比较到手价与时间成本。
description_en: A channel decision assistant for McDonald's China MCP. Compares delivery vs in-store pickup using real price, coupon and time-cost data.
allowed-tools: mcp__mcd-mcp__now-time-info, mcp__mcd-mcp__query-nearby-stores, mcp__mcd-mcp__delivery-query-addresses, mcp__mcd-mcp__delivery-query-stores, mcp__mcd-mcp__query-meals, mcp__mcd-mcp__query-meal-detail, mcp__mcd-mcp__query-store-coupons, mcp__mcd-mcp__query-my-coupons, mcp__mcd-mcp__available-coupons, mcp__mcd-mcp__calculate-price, mcp__mcd-mcp__create-order, mcp__mcd-mcp__query-order, mcp__mcd-mcp__order-list
version: 1.0.0
author: mcd-route contributors
---

# 麦门渠道官 · McRoute

**一句话**：回答「这一顿，点外送还是到店自取更划算」。

## 何时使用

用户表达的是**渠道选择**意图时使用：
- 「点外卖还是去店里？」「外送贵不贵？」「自取能省多少？」
- 「帮我比一下外送和到店」「今天适合点外卖吗」
- 「我附近有麦当劳吗」「能送到我这吗」

**不要**用于这些问题（它们有专门的 Skill，或不属于本 Skill 范围）：
- 「怎么用券最省钱」「凑单」→ 属于券组合优化，不是渠道决策
- 「帮我下单」「点一份巨无霸」→ 直接调 `create-order`，不必跑渠道对比
- 「热量多少」「减肥能吃吗」→ 属于营养计算

## 核心原则：取数交给 MCP，算术交给代码

**绝不用大模型口算金额。** 所有价格、优惠、配送费必须来自 MCP 返回；
所有求和、比较、折算必须由 `scripts/decider.py` 计算。原因：金额算错一次，
用户就再也不信这个 Skill 了。

## 执行流程

### 第 1 步 · 摸清渠道（必做）

并行调用两个接口，拿全两个渠道的门店：

```
now-time-info                    # 拿当前时间，判断是否在营业/配送时段
query-nearby-stores   {address}  # 到店自取候选门店
delivery-query-stores {address}  # 外送候选门店（按收货地址）
```

如果用户没给地址，先问，不要瞎猜。

**如果用户要外送但没有地址**：
```
delivery-query-addresses         # 列出已有地址让用户选
```

### 第 2 步 · 拿券（关键，最容易漏）

**券必须三路查全**，只查一路会漏掉最优解：

| 来源 | 接口 | 说明 |
|---|---|---|
| 门店券 | `query-store-coupons` | **绑门店**，换店就变；实测部分仅到店可用 |
| 账户券 | `query-my-coupons` | 已入卡包的券 |
| 可领券 | `available-coupons` | 麦麦省里还没领的，**需先 `auto-bind-coupons` 领取**才会出现在卡包 |

拿 `available-coupons` 后，如果用户想用券，调 `auto-bind-coupons` 全部领取，
再查一次 `query-my-coupons`——否则这些券在计算里是看不见的。

### 第 3 步 · 拿菜单与配送费

```
query-meals {storeCode}          # 该门店在售餐品
query-meal-detail {itemCode}     # 需要套餐明细时
```

配送费与起送价来自 `calculate-price` 的返回（它会给出商品金额、配送费、优惠金额、应付总价）。
**不要自己猜配送费。**

### 第 4 步 · 交给脚本算

把第 1-3 步拿到的原始数据整理成 JSON，调用决策引擎：

```bash
python scripts/decider.py --scenario <scenario.json> --minute-cost 0.5
```

`--minute-cost` 是**每分钟时间成本折算成多少钱**（默认 0.5 元/分钟，即 30 元/小时）。
用户明确说过「我不在乎时间」就传 0；用户说「我hour很贵」就调高。

脚本会输出：推荐渠道、理由、两渠道的完整计价拆解、券体检结果。

### 第 5 步 · 讲人话

按这个顺序讲：

1. **先给结论**：「建议到店自取，能省 13.5 元」
2. **再给拆解**：到店 ¥32（用了门店券满40减15）／外送 ¥47（配送费 9 元被免配送费券抵掉）
3. **说明时间成本怎么算的**：往返 28 分钟按 0.5 元/分钟折算
4. **提醒券的场景限制**：「你那张 15 元门店券只能到店用，外送用不了」

### 第 6 步 · 要下单才下单

只有用户明确说「就这个，下单」时才调 `create-order`。
下单前用 `calculate-price` 核一次价，把最终金额和支付链接给用户确认。

**支付永远由用户自己完成。** Agent 只建单，不碰钱。

## 诚实降级原则

拿不到的数据就说拿不到，**不要编**：

| 情况 | 正确做法 |
|---|---|
| `calculate-price` 没返回配送费 | 明说「接口没给配送费，本次未计入」，不要估一个 |
| `order-list` 返回空 | 说明账号无历史订单，不要编一条出来 |
| 某接口 401 | 提示 Token 无效，让用户去 open.mcd.cn 重新申请 |
| 某接口 429 | 降频重试，不要并发打接口 |
| 券渠道字段缺失 | 按 `any` 处理，但要在输出里说明「该券渠道未标注，按通用计算」 |

## 关键实测经验

以下是通过真实 MCP 联调得到的认知，直接影响正确性：

1. **券有场景属性**：实测部分门店券仅到店可用。外送场景必须剔除这些券，
   否则会报出实际用不了的低价。
2. **券要四路查全**：`available-coupons` 里的券要先 `auto-bind-coupons` 领，
   不领就不在 `query-my-coupons` 里。
3. **门店券绑门店**：换一家门店取到的券完全不同，所以**两个渠道要分别查券**。
4. **起送价是硬约束**：外送未达起送价就不可用，到店没有这个限制。
5. **历史订单可能为空**：新账号 `order-list` 返回空列表，依赖它的功能要有空态兜底。
6. **只取最优单张券，不叠券**：本 Skill 刻意不做券组合叠加，保守计价，
   保证报出的价格一定能真实成交。

## 文件说明

```
scripts/mcp_client.py   纯标准库 MCP 客户端（握手 / tools/list / tools/call）
scripts/decider.py      决策引擎：渠道计价、对比、券体检
scripts/selftest.py     46 项自测，改逻辑后必跑
scripts/mcp_probe.py    连通性自检：证明数据链路是真的
scripts/sample_data/    离线样例，无需 Token 即可跑通全流程
references/mcp-tools.md Tool 清单与字段映射
```

## 隐私

MCP Token 只从环境变量 `MCD_MCP_TOKEN` 读取，**绝不写进任何文件、绝不回显给用户**。
用户地址、订单信息属于个人数据，不要在输出里完整复述。
