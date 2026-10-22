# 麦当劳 MCP Tool 清单与字段映射

本 Skill 实际调用的 Tool 及其在决策流程中的位置。所有 Tool 均来自
`M-China/mcd-mcp-server`（麦当劳中国官方 MCP Server，远程托管，Streamable HTTP）。

接入地址：`https://mcp.mcd.cn`　鉴权：请求头 `Authorization: Bearer <TOKEN>`　限流：600 次/分钟

---

## 一、渠道探测（拿到两个渠道的候选门店）

### `now-time-info` — 获取当前时间信息

| 用途 | 说明 |
|---|---|
| 判断当前是否在营业/配送时段 | 外送有营业时间限制，到店也有 |

无必填参数。

### `query-nearby-stores` — 查询附近可用门店

| 用途 | 说明 |
|---|---|
| **到店自取**的候选门店 | 需用户地址或位置 |

关键返回字段：`storeCode` / `storeName` / `address` / 营业时间。
**注意**：返回通常不含距离，需要按地址或门店名自行判断远近。

### `delivery-query-stores` — 查询可配送的门店列表

| 用途 | 说明 |
|---|---|
| **外送**的候选门店 | 需收货地址 |

关键返回字段：`storeCode` / `storeName` / 配送相关信息。
与 `query-nearby-stores` 的关键差别：**这是「能送到你家」的门店，
不一定是「离你最近」的门店**——两者常常不是同一家。

### `delivery-query-addresses` — 获取用户可配送地址列表

| 用途 | 说明 |
|---|---|
| 用户没给地址时，列出已有地址让用户选 | 避免瞎猜地址 |

### `delivery-create-address` — 新增配送地址

仅在用户明确要求新增地址时使用。涉及个人住址，慎用。

---

## 二、券（必须三路查全）

| Tool | 来源 | 关键特性 |
|---|---|---|
| `query-store-coupons` | 门店券 | **绑门店**，换店即变；实测部分仅到店可用 |
| `query-my-coupons` | 账户券 | 已入卡包的券 |
| `available-coupons` | 可领券 | 麦麦省里还没领的 |
| `auto-bind-coupons` | 一键领券 | **必须先领**，`available-coupons` 的券才会进卡包 |

### 渠道字段

券的渠道限制字段名不统一，代码里做宽松映射：

| 原始值 | 归一化 |
|---|---|
| `delivery` / `外送` / `麦乐送` / `takeout_delivery` | `delivery` |
| `pickup` / `到店` / `自取` / `堂食` / `store` | `pickup` |
| 缺失或无法识别 | `any`（并在输出中声明「该券渠道未标注，按通用计算」） |

---

## 三、菜单与算价

### `query-meals` — 查询当前可售卖的餐品列表

需 `storeCode`。返回分类、餐品编码、标签、价格。

### `query-meal-detail` — 查询餐品详情

需餐品编码。返回套餐组成与可替换选项。

### `calculate-price` — 商品价格计算

**这是唯一可信的金额来源。** 返回：商品金额、配送费、优惠金额、应付总价。

配送费与起送价都从这里取，**不要估算**。

---

## 四、下单与订单

| Tool | 用途 | 注意 |
|---|---|---|
| `create-order` | 创建订单，返回订单详情与支付链接 | **只建单，付款由用户完成** |
| `query-order` | 查询订单状态、内容、配送信息 | |
| `cancel-order` | 取消订单 | 需用户明确要求 |
| `order-list` | 近期到店/外送历史订单 | **新账号可能返回空列表**，需空态兜底 |

---

## 五、本 Skill 未使用但相关的 Tool

列出以说明选型取舍——**这些方向已有大量同类项目扎堆**：

| 方向 | 相关 Tool | 为何不做 |
|---|---|---|
| 券组合优化 | `query-my-coupons` + `available-coupons` + `auto-bind-coupons` | 榜单前三都在做 |
| 营养计算 | `list-nutrition-foods` | 已有多个卡路里项目 |
| 活动日历 | `campaign-calendar` | 已有多个活动推荐项目 |
| 积分抽奖 | `query-lottery-info` / `draw-lottery` / `query-my-prizes` | 已有多个扭蛋项目 |
| 麦麦商城 | `mall-points-products` / `mall-create-order` 等 | 已有多个积分兑换项目 |
| 团餐 | `query-meal-assistance` | 场景较窄 |

**本 Skill 的定位是「渠道决策」**——即「同一顿饭，外送还是到店自取」，
这是当前榜单上尚未被充分覆盖的角度。

---

## 六、错误码

| code | 原因 | 处理 |
|---|---|---|
| 401 | Token 无效/过期/未提供 | 提示去 open.mcd.cn 重新申请 |
| 429 | 超过 600 次/分钟 | 退避重试，降低并发 |

---

## 七、实测记录

开发过程中用真实 MCP 联调得到的观察：

1. **券有场景属性**：实测部分门店券仅到店可用。外送场景必须剔除这些券，
   否则会报出实际用不了的低价。
2. **券要四路查全**：`available-coupons` 的券需先 `auto-bind-coupons` 领取，
   不领就不在 `query-my-coupons` 中返回。
3. **门店券绑门店**：换一家门店取到的券完全不同，因此两个渠道必须分别查券。
4. **起送价是硬约束**：外送未达起送价即不可用，到店无此限制。
5. **历史订单可能为空**：`order-list` 在无历史订单时返回空列表。
6. **营养数据可直接用**：`list-nutrition-foods` 一次返回约 160 款餐品的多维营养数据。

> 上述记录将在获得真实 Token 后于 `workbuddy.md` 中补充逐条验证结果。
