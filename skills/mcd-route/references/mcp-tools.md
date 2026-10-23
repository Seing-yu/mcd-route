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

> 以下全部为 **2026-10-22 使用真实 Token 实测**得到的结果，
> 原始返回快照见 `scripts/sample_data/real_snapshot.json`。
> 这批数据同时被 `selftest.py` 的 24 项「真实数据回归」断言锁定。

### 7.1 真实调用能跑通什么

| 环节 | 状态 | 说明 |
|---|---|---|
| `initialize` 握手 | ✅ | 协商出协议版本 **2025-06-18**（服务器 `mcd-mcp` v1.0.0） |
| `tools/list` | ✅ | 服务器提供 **35 个 Tool**（官方 README 只列了 34 个，多出 `query-survey-coupon`） |
| 本项目依赖的 11 个 Tool | ✅ | 全部在线 |
| `query-nearby-stores` | ✅ | 返回 5 家门店，**含 distance 距离字段** |
| `delivery-query-stores` | ✅ | 返回可配送门店，**多一个 beCode 字段** |
| `query-meals` | ✅ | 到店 118 款 / 外送 115 款 |
| `calculate-price` | ✅ | 到店与外送均能核价，**返回配送费与打包费** |
| `query-my-coupons` | ✅ | 返回 Markdown 格式券列表 |
| `query-store-coupons` | ✅ | 返回 JSON 格式券列表 |
| `available-coupons` | ✅ | 返回 Markdown 格式可领券列表 |

### 7.1.1 原生 MCP 通道实采（2026-10-23）

以上是**脚本**采集（10-22）。10-23 装好 WorkBuddy 自定义连接器后，
**通过原生通道 `mcp__mcd-mcp__*` 再采一次**，两个独立途径互相印证。
快照见 `scripts/sample_data/live_20261023.json`。

| Tool | 实参 | 实测返回 |
|---|---|---|
| `now-time-info` | — | 服务器时间 2026-10-23 09:14:29，GMT+08:00 |
| `query-nearby-stores` | `beType=1, searchType=2, city=北京, keyword=望京` | 5 家门店，**distance 字段**（312/611/847/943/1215 米），含 `businessStatus`、`reservationTimeOptions` |
| `query-meals` | `storeCode=1950980, orderType=1, beType=1` | 11 个分类、118 款；`currentPrice`/`originalPrice`/`discountType` 齐全 |
| `query-store-coupons` | `storeCode=1950980` 与 `1950980` | 均返回 `data:[]` |
| `calculate-price` | 3 件商品, `orderType=1, beType=1` | `price=4350`（分）→ ¥43.50；`takeWayList` = 堂食/外带 |

**这次实采确认的三件事**

1. **到店核价返回不含 `deliveryPrice` / `packingPrice`**
   —— 这两个字段**只有外送才有**。`parse_calculate_price()` 遇缺失字段
   会写入 `notes` 并给 0，**不猜不估**。这正是"保守计价"原则的落点。
2. **`query-store-coupons` 返回 `data:[]` 是真实业务状态，不是接口异常**
   —— 换第二家门店交叉验证同样为空。说明该会员在这两家门店的
   到店渠道下确实无可用券。**不能把空数组当成"查询失败"来重试。**
3. **两次独立采集的到店核价返回字段集完全一致**
   （10-22 脚本 vs 10-23 原生通道），已写成自测断言锁定。

**外送侧本次未采集**：`delivery-query-stores` 需要
`delivery-query-address` 返回的 `addressId`，属用户个人地址，
须用户主动提供，不代为猜测或预置。

### 7.2 金额单位契约（最容易踩的坑）

**麦当劳 MCP 的金额单位按工具区分，不能一概处理：**

| Tool | 金额单位 | 实测证据 |
|---|---|---|
| `calculate-price` | **分**（无引号整数） | 菜单现价 `'33.5'` → 核价 `productOriginalPrice: 3350` |
| `query-meals` | **元**（字符串） | `currentPrice: '33.5'` / `originalPrice: '47'` |
| `query-meal-detail` | 元 | 同上 |
| `create-order` / `query-order` | 元 | 官方 README 说明 |
| 麦麦商城订单 | 元 | 官方 README 说明 |
| 积分字段（`points` 等） | 非金额 | **不做任何换算** |

**混用会导致每个金额差 100 倍。**
本项目内部统一用「元」，`parse_calculate_price()` 专责转换，
`fen_to_yuan()` / `to_yuan()` 是底层函数。

### 7.3 外送的三个隐藏费用项

实测外送核价返回：

```
productOriginalPrice: 11600        ← 商品 116.00 元
deliveryOriginalPrice:  600        ← 配送费  6.00 元
packingOriginalPrice:   280        ← 打包费  2.80 元   ← 独立费用项，别漏
originalPrice:         12480        ← 合计 124.80 元
price:                 12480
```

⚠️ **打包费是独立字段**，早期版本遗漏了它，会让外送总价少算 2~3 元。

### 7.4 券是「商品券」，不是满减券

真实门店券返回：

```json
{
  "title": "11.9元麦辣鸡腿堡",
  "couponId": "A255280326E3328D179C362B7B8DDA65",
  "couponCode": "MCD601Q0610849Z410760",
  "tradeDateTime": "2026-10-19 10:30:00-2026-10-23 23:59:59",
  "products": [{ "productCode": "1440", "productName": "麦辣鸡腿汉堡" }],
  "promotionId": "112479003"
}
```

**关键含义**（与最初假设完全不同，已按实测重写）：

| 字段 | 实际含义 | 最初假设（错） |
|---|---|---|
| `title` 里的「11.9元」 | **用券价**（11.9 元买这个汉堡） | 当成抵扣额 |
| `products[].productCode` | 券**绑定具体商品** | 以为是全场满减 |
| `tradeDateTime` | **有效期区间** | 以为是消费门槛 |
| 抵扣额 | 需用**菜单原价 − 用券价**反推 | 直接取 `discount` |

**必须检查购物篮是否含该券绑定的商品**，否则会报出一张根本用不上的券。
实测案例：卡包有「11.9元麦辣鸡腿堡」券（绑定 1440），
但购物篮里是「麦辣鸡腿汉堡三件套」（9900005456）→ 券用不上，抵扣为 0。

### 7.5 两个券接口格式不同

| 接口 | 格式 | 渠道信息 |
|---|---|---|
| `query-store-coupons`（门店券） | **纯 JSON 数组** | JSON 里**没有**渠道字段 |
| `query-my-coupons`（卡包券） | **Markdown** | 有「标签」字段 |
| `available-coupons`（麦麦省） | **Markdown** | 有「状态」字段（可领取/已领取） |

卡包券的标签实测值：`到店专用、外送专用` —— **多标签表示两个渠道都能用**。
解析时必须**先判多标签**，否则会先匹配到「外送」而误判成仅外送可用。

### 7.6 距离字段确实存在

早期文档假设「门店接口不返回距离」——**这是错的**。
`query-nearby-stores` 实测返回：

```json
{
  "storeCode": "<门店编码>",
  "storeName": "麦当劳（示例门店 A）",
  "distance": 312,          ← 米
  "latitude": 39.98, "longitude": 116.47,
  "businessStatus": "营业中",
  "reservation": true
}
```

因此往返时间可以按真实距离推算，不必再用粗略分档估算。

### 7.7 参数名与必填约束（实测踩坑）

| 接口 | 必填参数 | 踩坑 |
|---|---|---|
| `query-nearby-stores` | `beType` + `searchType` | **不接受 `address`**（传了报 400「缺少参数」）；`searchType=2` 时 `city` 与 `keyword` 必须成对 |
| `delivery-query-stores` | `addressId` + `beType` | `addressId` 来自 `delivery-query-addresses` |
| `query-meals` | `storeCode` + `beType` + `orderType` | 外送时须带 `beCode` |
| `calculate-price` | `storeCode` + `beType` + `orderType` | 外送时须带 `beCode`，否则报 **600048** |
| `query-store-coupons` | `storeCode` + `beType` + `orderType` | `storeCode` 必须全数字 |

### 7.8 业务错误不在 HTTP 层

失败时 `HTTP 200` 但 body 里是：

```json
{"success": false, "code": 600048, "message": "外送场景下，beType=2/5/6时必传beCode",
 "datetime": "...", "traceId": "..."}
```

**必须检查 `success` 字段**，不能只看 HTTP 状态码。

### 7.9 响应是「散文 + 内嵌 JSON」的混合文本

多个接口的返回不是纯 JSON，而是「说明文字 + JSON + 补充说明」拼起来的文本：

```
# API Response Information
Below is the response from an API call...
## Response Structure
- **data**: ...
{"success":true,"data":{...}}
```

解析必须用**括号配平**从文本中提取 JSON（找第一个 `{` 到配平的 `}`），
**不能用正则贪婪匹配**（会抓到说明文字里的花括号导致解析失败）。

### 7.10 其他实测观察

1. **可领券不先领就不在卡包里**：`available-coupons` 的券要先
   `auto-bind-coupons` 领取，才会出现在 `query-my-coupons`。
2. **`takeWayList` 给出就餐方式**：核价返回 `eat-in`（堂食）/
   `take-in-store`（外带），下单时要用对应 code。
3. **图片 URL 带时效签名**：`q-ak=` / `q-signature=` 参数是 COS 签名，
   有有效期，不应长期硬编码或当作静态资源引用。
4. **历史订单可能为空**：新账号 `order-list` 返回空列表，依赖它的功能需空态兜底。

---

*本项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，非麦当劳官方产品。*
*使用麦当劳 MCP 服务须遵守其《使用条款》与《麦当劳 MCP 服务规则》。*
