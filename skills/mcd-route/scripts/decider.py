#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门渠道官 · 核心决策引擎。

一句话：**回答「这一顿，点外送还是到店自取？」**

为什么需要它
------------
麦当劳的外送和到店不是简单的「加了配送费」：
  - 外送起送价通常高于到店，凑不够单会被拒；
  - 配送费随门店距离和时段浮动；
  - **券有场景限制**——实测部分门店券仅到店可用，外送场景要换成别的券；
  - 门店券是绑门店的，换一家店取到的券就不同；
  - 到店自取要付出「出门往返」的时间成本，外送要付出「等餐」的时间成本。

所以真正的决策是四元的：
    到手总价 = 商品原价 - 可用券抵扣 + 配送费
    总成本   = 到手总价 + 时间成本（按用户给的时间单价折算）

本模块只做**确定性算术**，不猜、不编。算不出就诚实说算不出。

纯标准库，无第三方依赖。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

# 时间成本的默认折算基准：等餐 1 分钟按 0.5 元算（可被用户覆盖）
DEFAULT_MINUTE_COST = 0.5
# 门店距离分档 -> 往返分钟数。门店 Tool 一般不给距离，用常见档位估算
DISTANCE_MINUTES = {
    "very_close": 10,   # 步行 5 分钟内
    "close": 20,        # 步行 10 分钟左右
    "medium": 35,       # 骑车 15 分钟左右
    "far": 50,          # 需要开车/地铁
}


@dataclass
class Channel:
    """一个渠道（外送 / 到店）的可选项。"""

    key: str                      # "delivery" | "pickup"
    label: str                    # 展示名
    stores: list[dict] = field(default_factory=list)   # 可选的门店
    coupons: list[Coupon] = field(default_factory=list)  # 该渠道可用的券
    delivery_fee: float = 0.0     # 配送费（到店为 0）
    packing_fee: float = 0.0      # 打包费（到店为 0）—— 实测外送必收，独立费用项
    min_order: float = 0.0        # 起送价门槛
    prep_minutes: int = 0         # 出餐等待
    travel_minutes: int = 0       # 往返门店耗时（到店才有意义）
    min_order_met: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        """渠道是否可下单（起送价没达标就不行）。"""
        return bool(self.stores) and self.min_order_met


@dataclass
class BasketItem:
    """购物篮中的一件商品。"""

    code: str
    name: str
    price: float
    qty: int = 1

    @property
    def total(self) -> float:
        return round(self.price * self.qty, 2)


@dataclass
class Coupon:
    """一张券。

    【实测修正 · 2026-10-22】真实接口返回的券**不是**「抵扣额 + 满减门槛」模型，
    而是**商品券**模型：

        {
          "title": "11.9元麦辣鸡腿堡",
          "couponId": "A255280326E3328D179C362B7B8DDA65",
          "couponCode": "MCD601Q0610849Z410760",
          "tradeDateTime": "2026-10-19 10:30:00-2026-10-23 23:59:59",
          "products": [{"productCode": "1440", "productName": "麦辣鸡腿汉堡"}],
          "promotionId": "112479003"
        }

    关键含义：
      · 券**绑定具体商品**（products[].productCode），不是全场满减
      · 券名里的「11.9元」是**用券价**（11.9 元买这个汉堡），
        实际抵扣额 = 商品原价 − 用券价，需要用菜单价反推
      · `tradeDateTime` 是**有效期区间**，不是消费门槛
      · 渠道限制在 query-my-coupons 的「标签」字段里（到店专用/外送专用），
        门店券接口（query-store-coupons）返回的 JSON 里**没有渠道字段**

    因此本类同时保留两种表达：
      · `use_price`  —— 用券价（分或元已归一化到元）
      · `product_codes` —— 绑定的商品编码集合
    """

    id: str
    name: str
    discount: float = 0.0          # 抵扣额（元），由用券价与原价反推
    threshold: float = 0.0         # 兼容旧模型：满减门槛（元）
    channel: str = "any"           # any / delivery / pickup
    source: str = ""               # 从哪个 Tool 取到的
    stackable: bool = True
    note: str = ""
    use_price: float = 0.0         # 用券价（元）
    product_codes: list[str] = field(default_factory=list)
    valid_from: str = ""           # 有效期起
    valid_to: str = ""             # 有效期止
    coupon_code: str = ""          # couponCode，算价时可能需要

    def binds_product(self, product_code: str) -> bool:
        """这张券是否绑定指定商品。空集合表示不限定。"""
        if not self.product_codes:
            return True
        return product_code in self.product_codes

    def usable_for(self, channel_key: str, amount: float) -> tuple[bool, str]:
        """判断这张券在给定渠道、给定金额下能不能用。"""
        if self.channel not in ("any", channel_key):
            return False, f"仅限{'外送' if self.channel == 'delivery' else '到店'}使用"
        if amount < self.threshold:
            return False, f"未达 {self.threshold:.0f} 元门槛"
        return True, ""


@dataclass
class Verdict:
    """决策结论。"""

    recommended: str = ""
    reason: str = ""
    best_total: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------- 工具

def money(value: float) -> str:
    """金额格式化：整数不带小数点，负数保留负号在数字前。"""
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    body = f"{magnitude:.0f}" if abs(magnitude - round(magnitude)) < 0.005 else f"{magnitude:.2f}"
    return f"{sign}{body}"


# ------------------------------------------------------------------ 单位归一化
#
# 【实测坑 · 必读】麦当劳 MCP 的金额单位**按工具区分**，不能一概处理。
# 以下均为 2026-10-22 用真实 Token 实测确认（见 references/mcp-tools.md）：
#
#   · calculate-price  → 价格字段是「分」（无引号整数）
#       实测：菜单现价 '33.5'（元），核价 productOriginalPrice = 3350（分）
#       外送核价：deliveryPrice=600 → ¥6.00 配送费
#                 packingPrice=280  → ¥2.80 打包费
#   · query-meals / query-meal-detail → 已是「元」（字符串）
#       实测：currentPrice = '33.5' / originalPrice = '47'
#   · create-order / query-order / 商城订单 → 已是「元」
#   · 积分字段（points / totalPoints 等）→ 非金额，不换算
#
# 本项目内部统一使用「元」。
# 混用会导致每个金额差 100 倍——这是最容易发生也最难发现的错误。

FEN_PER_YUAN = 100


def fen_to_yuan(value) -> float:
    """把「分」转换成「元」。仅用于 calculate-price 返回的价格字段。"""
    try:
        return round(float(value) / FEN_PER_YUAN, 2)
    except (TypeError, ValueError):
        return 0.0


def to_yuan(value, unit: str = "yuan") -> float:
    """按指定单位归一化成「元」。

    unit="fen"  -> 除以 100（calculate-price 的价格字段）
    unit="yuan" -> 原值（query-meals 等已是元的字段）
    """
    if unit == "fen":
        return fen_to_yuan(value)
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def best_coupon(coupons: Iterable[Coupon], channel_key: str, amount: float, basket: list[BasketItem] | None = None) -> tuple[float, str, list[str]]:
    """在给定渠道和金额下，选出抵扣最多的那一张券。

    【实测修正】真实券是**商品券**——绑定具体商品（products[].productCode），
    只能用于购买那个商品。所以必须检查购物篮里是否包含该券绑定的商品，
    否则会报出一张根本用不上的券。

    实测案例：券「11.9元麦辣鸡腿堡」绑定 productCode=1440，
    购物篮里是「麦辣鸡腿汉堡三件套」(9900005456) → 这张券用不上。

    返回 (抵扣金额, 券名, 参与计算的券 id 列表)。
    保守策略：只选单张最优券，不做叠加以免报出实际用不了的低价。
    """
    basket_codes = {item.code for item in (basket or [])}

    best_amount = 0.0
    best_name = "无可用券"
    best_ids: list[str] = []
    for coupon in coupons:
        ok, _ = coupon.usable_for(channel_key, amount)
        if not ok:
            continue
        # 商品券必须命中购物篮里的商品
        if coupon.product_codes and not (set(coupon.product_codes) & basket_codes):
            continue
        discount = coupon.discount
        if discount <= 0 and coupon.use_price > 0:
            # 抵扣额 = 商品原价 − 用券价（用券价从券名解析得到）
            original = _original_price_of(coupon, basket)
            if original > 0:
                discount = round(original - coupon.use_price, 2)
        if discount <= 0:
            continue
        if discount > best_amount:
            best_amount = discount
            best_name = coupon.name
            best_ids = [coupon.id]
    return best_amount, best_name, best_ids


def _original_price_of(coupon: Coupon, basket: list[BasketItem] | None) -> float:
    """取券绑定商品在购物篮中的价格，作为抵扣基数的上限参考。

    券的用券价（use_price）对应的是**单品原价**，
    而购物篮里的商品可能是套餐（原价更高）。
    这里取绑定商品在购物篮中的价格，抵扣额不会超过它。
    """
    if not basket:
        return 0.0
    for item in basket:
        if item.code in coupon.product_codes:
            return item.price
    return 0.0


def collect_channel_coupons(
    raw_coupons: Iterable[dict],
    channel_key: str,
    source: str = "",
) -> list[Coupon]:
    """把 MCP 返回的券列表归一化成 Coupon 对象。

    【实测】两个券接口返回的格式不同：

    1) query-store-coupons（门店券）→ **纯 JSON 数组**
       [{"title","couponId","couponCode","tradeDateTime",
         "products":[{"productCode","productName"}],"promotionId"}]

    2) query-my-coupons（卡包券）→ **Markdown**
       ## 券名
       - **优惠**: ¥11.9 (用券价格)
       - **有效期**: 2026-10-19 10:30-2026-10-23 23:59 周一、二...
       - **标签**: 到店专用、外送专用

    两者的渠道信息位置不同：Markdown 有「标签」字段，JSON 没有。
    本函数做一次宽松映射，两种格式都能吃。
    """
    out: list[Coupon] = []
    for index, raw in enumerate(raw_coupons or []):
        if not isinstance(raw, dict):
            continue

        cid = str(raw.get("id") or raw.get("couponId") or raw.get("code") or f"{source}-{index}")
        name = str(raw.get("name") or raw.get("title") or raw.get("couponName") or cid)

        # --- 用券价：从「11.9元麦辣鸡腿堡」这类券名里解析，或直接取优惠字段 ---
        use_price = _extract_use_price(name, raw)

        # --- 抵扣额：优先取显式字段，否则用「原价 − 用券价」由调用方补算 ---
        discount = raw.get("discount")
        if discount is None:
            discount = raw.get("amount") or raw.get("value") or raw.get("discountAmount") or 0
        try:
            discount = float(discount)
        except (TypeError, ValueError):
            discount = 0.0

        threshold = raw.get("threshold") or raw.get("minAmount") or raw.get("fullAmount") or 0
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            threshold = 0.0

        # --- 渠道限制 ---
        channel = _extract_channel(raw)

        # --- 绑定的商品 ---
        product_codes: list[str] = []
        for product in raw.get("products") or []:
            if isinstance(product, dict):
                code = product.get("productCode") or product.get("code")
                if code:
                    product_codes.append(str(code))

        # --- 有效期区间 ---
        valid_from, valid_to = _extract_validity(raw.get("tradeDateTime") or raw.get("validTime"))

        out.append(
            Coupon(
                id=cid,
                name=name,
                discount=discount,
                threshold=threshold,
                channel=channel,
                source=source,
                stackable=bool(raw.get("stackable", True)),
                note=str(raw.get("note") or raw.get("description") or ""),
                use_price=use_price,
                product_codes=product_codes,
                valid_from=valid_from,
                valid_to=valid_to,
                coupon_code=str(raw.get("couponCode") or ""),
            )
        )
    return out


def _extract_use_price(name: str, raw: dict) -> float:
    """从券名或字段中解析「用券价」。

    实测券名形如「11.9元麦辣鸡腿堡」，前面的数字是用券价（元）。
    """
    for key in ("usePrice", "use_price", "couponPrice", "preferPrice"):
        if raw.get(key) is not None:
            try:
                return round(float(raw[key]), 2)
            except (TypeError, ValueError):
                pass
    import re

    match = re.search(r"(\d+(?:\.\d+)?)\s*元", name)
    if match:
        try:
            return round(float(match.group(1)), 2)
        except ValueError:
            return 0.0
    return 0.0


def _extract_channel(raw: dict) -> str:
    """提取渠道限制。兼容 scene/channel/useChannel/标签/labels 等字段。

    【实测】卡包券的「标签」字段值形如「到店专用、外送专用」，
    这是**多标签**——两个渠道都能用。必须先判多标签，
    否则会先匹配到「外送」而误判成仅外送可用。
    """
    candidates = []
    for key in ("channel", "scene", "useChannel", "标签", "labels", "label", "tags"):
        value = raw.get(key)
        if value:
            candidates.append(value)

    joined = " ".join(str(v) for v in candidates)
    has_pickup = any(k in joined for k in ("到店", "pickup", "自取", "堂食"))
    has_delivery = any(k in joined for k in ("外送", "delivery", "麦乐送"))

    # 多标签优先：两个渠道都标注 → 通用
    if has_pickup and has_delivery:
        return "any"

    for value in candidates:
        text = str(value).lower()
        if any(k in text for k in ("delivery", "外送", "麦乐送", "takeout_delivery")):
            return "delivery"
        if any(k in text for k in ("pickup", "到店", "自取", "堂食", "store")):
            return "pickup"

    return "any"


def _extract_validity(trade_datetime: str | None) -> tuple[str, str]:
    """解析有效期区间。实测格式：'2026-10-19 10:30:00-2026-10-23 23:59:59'。"""
    if not trade_datetime:
        return "", ""
    import re

    match = re.search(
        r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)\s*[-~]\s*(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)",
        str(trade_datetime),
    )
    if match:
        return match.group(1), match.group(2)
    return "", ""


def channel_total(
    channel: Channel,
    basket: list[BasketItem],
    minute_cost: float = DEFAULT_MINUTE_COST,
) -> dict:
    """算某个渠道下的到手价与总成本。"""
    goods = round(sum(item.total for item in basket), 2)
    discount, coupon_name, coupon_ids = best_coupon(channel.coupons, channel.key, goods, basket)
    after_discount = round(max(goods - discount, 0.0), 2)
    total = round(after_discount + channel.delivery_fee + channel.packing_fee, 2)

    # 时间成本：到店算往返，外送只算等餐
    minutes = channel.travel_minutes + channel.prep_minutes if channel.key == "pickup" else channel.prep_minutes
    time_cost = round(minutes * minute_cost, 2)

    return {
        "channel": channel.key,
        "label": channel.label,
        "goods": goods,
        "discount": discount,
        "coupon": coupon_name,
        "coupon_ids": coupon_ids,
        "delivery_fee": channel.delivery_fee,
        "packing_fee": channel.packing_fee,
        "total": total,
        "minutes": minutes,
        "time_cost": time_cost,
        "grand_total": round(total + time_cost, 2),
        "available": channel.available,
        "min_order": channel.min_order,
        "min_order_met": channel.min_order_met,
        "notes": list(channel.notes),
    }


def compare(
    delivery: Channel,
    pickup: Channel,
    basket: list[BasketItem],
    minute_cost: float = DEFAULT_MINUTE_COST,
) -> Verdict:
    """核心对比：外送 vs 到店，给出建议和理由。

    判定顺序（诚实降级，不硬凑结论）：
      1. 两边都不可用 -> 明确说不行
      2. 只有一边可用 -> 推荐那一边
      3. 两边都可用 -> 比总成本（到手价 + 时间成本）
         差距小于 1 元 -> 建议按「到手价」选，并说明时间成本
    """
    d = channel_total(delivery, basket, minute_cost)
    p = channel_total(pickup, basket, minute_cost)

    if not d["available"] and not p["available"]:
        return Verdict(
            recommended="都不行",
            reason="两个渠道当前都不可用：没有可选门店，或起送价没达到。",
            detail={"delivery": d, "pickup": p},
        )

    if p["available"] and not d["available"]:
        return Verdict(
            recommended="到店自取",
            reason=f"外送不可用（{d['notes'][0] if d['notes'] else '起送价未达标'}），到店可行。",
            best_total=p["total"],
            detail={"delivery": d, "pickup": p},
        )

    if d["available"] and not p["available"]:
        return Verdict(
            recommended="点外送",
            reason=f"到店不可用（{p['notes'][0] if p['notes'] else '无可选门店'}），外送可行。",
            best_total=d["total"],
            detail={"delivery": d, "pickup": p},
        )

    gap = round(d["grand_total"] - p["grand_total"], 2)
    detail = {"delivery": d, "pickup": p, "gap": gap}

    # 券在两个渠道都能用时，到手价可能完全相同——此时不该说「少 ¥0」
    if abs(d["total"] - p["total"]) < 0.01:
        if abs(gap) < 1.0:
            return Verdict(
                recommended="价格相同，看你更在意什么",
                reason=(
                    f"两个渠道到手价相同（都是 ¥{money(d['total'])}）——"
                    f"因为这张券两个渠道都能用。"
                    f"外送等 {d['minutes']} 分钟，到店来回 {p['minutes']} 分钟。"
                    f"时间成本相差不多时，选你更方便的那个。"
                ),
                best_total=d["total"],
                detail=detail,
            )
        if gap > 0:
            return Verdict(
                recommended="到店自取",
                reason=(
                    f"两个渠道到手价相同（¥{money(d['total'])}），但到店要来回 {p['minutes']} 分钟，"
                    f"外送只要等 {d['minutes']} 分钟，算上时间成本外送更划算。"
                ),
                best_total=d["total"],
                detail=detail,
            )
        return Verdict(
            recommended="点外送",
            reason=(
                f"两个渠道到手价相同（¥{money(d['total'])}），到店要来回 {p['minutes']} 分钟，"
                f"算上时间成本到店更划算。"
            ),
            best_total=d["total"],
            detail=detail,
        )

    if abs(gap) < 1.0:
        cheaper = "外送" if d["total"] < p["total"] else ("到店" if p["total"] < d["total"] else "两者")
        return Verdict(
            recommended=f"{cheaper}（到手价几乎持平）",
            reason=(
                f"两渠道到手价基本相同（外送 ¥{money(d['total'])} / 到店 ¥{money(p['total'])}），"
                f"但总成本差 ¥{money(abs(gap))}（含时间成本折算）。按你的时间单价算，"
                f"{'到店更划算' if gap > 0 else '外送更划算'}。"
            ),
            best_total=min(d["total"], p["total"]),
            detail=detail,
        )

    if gap > 0:
        return Verdict(
            recommended="到店自取",
            reason=(
                f"到店到手价 ¥{money(p['total'])}，比外送 ¥{money(d['total'])} 少 ¥{money(d['total'] - p['total'])}；"
                f"算上往返 {p['minutes']} 分钟的时间成本后，仍净省 ¥{money(gap)}。"
            ),
            best_total=p["total"],
            detail=detail,
        )

    return Verdict(
        recommended="点外送",
        reason=(
            f"外送到手价 ¥{money(d['total'])}，比到店 ¥{money(p['total'])} 少 ¥{money(p['total'] - d['total'])}；"
            f"算上等餐 {d['minutes']} 分钟的时间成本后，仍净省 ¥{money(abs(gap))}。"
        ),
        best_total=d["total"],
        detail=detail,
    )


def coupon_audit(coupons: list[Coupon], basket_total: float, basket: list[BasketItem] | None = None) -> list[dict]:
    """券体检：逐张券算出名义面额、实际能不能用、值不值得用。

    【实测修正】真实券绑定具体商品，所以「用得上」还取决于购物篮里有没有那个商品。
    实测案例：卡包里有一张「11.9元麦辣鸡腿堡」券，
    但购物篮里买的是「麦辣鸡腿汉堡三件套」→ 券用不上，抵扣为 0。
    这正是「有券但没省到钱」最常见的原因。
    """
    basket_codes = {item.code for item in (basket or [])}
    rows: list[dict] = []
    for coupon in coupons:
        ok_pickup, why_pickup = coupon.usable_for("pickup", basket_total)
        ok_delivery, why_delivery = coupon.usable_for("delivery", basket_total)

        # 商品匹配检查
        if coupon.product_codes:
            matched = bool(set(coupon.product_codes) & basket_codes)
            product_note = (
                "购物篮含该券绑定商品" if matched
                else f"购物篮无该券绑定商品（{', '.join(coupon.product_codes)}）"
            )
        else:
            matched = True
            product_note = "不限定商品"

        if not ok_pickup and not ok_delivery:
            verdict = "用不了"
        elif ok_pickup and ok_delivery:
            verdict = "两个渠道都能用"
        elif ok_pickup:
            verdict = "仅到店可用"
        else:
            verdict = "仅外送可用"

        # 实际抵扣
        if not matched:
            actual = 0.0
        elif coupon.discount > 0:
            actual = coupon.discount
        elif coupon.use_price > 0:
            original = _original_price_of(coupon, basket)
            actual = round(max(original - coupon.use_price, 0.0), 2)
        else:
            actual = 0.0

        rows.append(
            {
                "name": coupon.name,
                "discount": coupon.discount,
                "use_price": coupon.use_price,
                "actual_discount": actual,
                "threshold": coupon.threshold,
                "verdict": verdict,
                "product_match": matched,
                "product_note": product_note,
                "reason": why_pickup or why_delivery or "",
                "source": coupon.source,
            }
        )
    rows.sort(key=lambda r: -r["actual_discount"])
    return rows


def build_basket(items: Iterable[dict]) -> list[BasketItem]:
    """从 MCP 菜单数据构造购物篮。

    菜单来自 `query-meals`，其金额字段已是「元」，直接使用，不做单位换算。
    """
    basket: list[BasketItem] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or raw.get("itemCode") or raw.get("id") or "")
        if not code:
            # 没有编码的条目无法参与后续核价，直接丢弃
            continue
        name = str(raw.get("name") or raw.get("itemName") or code)
        price = raw.get("price")
        if price is None:
            price = raw.get("currentPrice") or raw.get("salePrice") or raw.get("originalPrice")
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = 0.0
        qty = int(raw.get("qty") or raw.get("count") or 1)
        basket.append(BasketItem(code=code, name=name, price=price, qty=qty))
    return basket


def parse_calculate_price(raw: dict) -> dict:
    """解析 `calculate-price` 的返回，**统一换算成「元」**。

    【实测】2026-10-22 真实返回（到店）：

        productOriginalPrice: 3350        ← 商品原价 33.50 元
        productPrice:         3350
        originalPrice:        3350
        discount:             0
        price:                3350

    外送真实返回：

        productOriginalPrice: 11600       ← 商品 116.00 元
        deliveryOriginalPrice: 600       ← 配送费 6.00 元
        packingOriginalPrice:  280       ← 打包费 2.80 元
        originalPrice:        12480       ← 合计 124.80 元
        price:                12480

    ⚠️ **打包费是独立的费用项**，早期版本遗漏了它，会让外送总价少算 2~3 元。
    ⚠️ 全部价格字段单位是「分」，与 query-meals 的「元」相反。

    返回统一结构（元）：
        {goods, delivery_fee, packing_fee, discount, total, min_order, notes}
    解析不到的字段一律给 0 并在 notes 中说明，**不猜、不估算**。
    """
    notes: list[str] = []
    if not isinstance(raw, dict):
        return {
            "goods": 0.0, "delivery_fee": 0.0, "packing_fee": 0.0,
            "discount": 0.0, "total": 0.0, "min_order": 0.0,
            "notes": ["calculate-price 未返回可解析的结构"],
        }

    def pick(*names):
        for name in names:
            if name in raw and raw[name] is not None:
                return raw[name]
        return None

    def as_fen(value, label):
        """把分转成元。字段缺失时记 notes 并返回 0。"""
        if value is None:
            notes.append(f"{label} 未返回，本次不计入")
            return 0.0
        return fen_to_yuan(value)

    goods = as_fen(pick("productOriginalPrice", "productPrice", "goodsPrice", "totalPrice"),
                   "商品金额")
    # 真实字段名是 deliveryPrice / deliveryOriginalPrice；
    # deliveryFee 是早期假设，保留兼容以免旧数据解析不到。
    delivery_fee = as_fen(pick("deliveryPrice", "deliveryOriginalPrice", "deliveryFee", "shippingFee"),
                          "配送费")
    packing_fee = as_fen(pick("packingPrice", "packingOriginalPrice"), "打包费")
    discount = as_fen(pick("discount", "discountAmount", "preferAmount"), "优惠金额")
    total = as_fen(pick("price", "payAmount", "totalAmount", "shouldPay"), "应付总价")
    min_order = as_fen(pick("minOrderAmount", "minDeliveryAmount", "minOrder"), "起送价")

    return {
        "goods": goods,
        "delivery_fee": delivery_fee,
        "packing_fee": packing_fee,
        "discount": discount,
        "total": total,
        "min_order": min_order,
        "notes": notes,
    }


def run_scenario(scenario: dict, minute_cost: float = DEFAULT_MINUTE_COST) -> dict:
    """按场景 JSON 跑一次完整决策，返回结构化结果。"""
    basket = build_basket(scenario.get("basket", []))
    goods_total = sum(item.total for item in basket)

    delivery_raw = scenario.get("delivery", {}) or {}
    pickup_raw = scenario.get("pickup", {}) or {}

    def make_channel(key: str, label: str, raw: dict, is_delivery: bool) -> Channel:
        coupons = collect_channel_coupons(
            raw.get("coupons", []), key, raw.get("coupon_source", "query-store-coupons")
        )
        min_order = float(raw.get("min_order", 0) or 0)
        return Channel(
            key=key,
            label=label,
            stores=raw.get("stores", []) or [],
            coupons=coupons,
            delivery_fee=float(raw.get("fee", 0) or 0) if is_delivery else 0.0,
            packing_fee=float(raw.get("packing_fee", 0) or 0) if is_delivery else 0.0,
            min_order=min_order,
            prep_minutes=int(raw.get("prep_minutes", 0) or 0),
            travel_minutes=int(raw.get("travel_minutes", 0) or 0),
            min_order_met=goods_total >= min_order,
            notes=list(raw.get("notes", []) or []),
        )

    delivery = make_channel("delivery", "外送", delivery_raw, True)
    pickup = make_channel("pickup", "到店自取", pickup_raw, False)

    verdict = compare(delivery, pickup, basket, minute_cost=minute_cost)
    return {
        "verdict": verdict.to_dict(),
        "coupon_audit": coupon_audit(delivery.coupons + pickup.coupons, goods_total, basket),
        "basket_total": round(goods_total, 2),
        "minute_cost": minute_cost,
    }


def main() -> None:
    """命令行入口：读场景 JSON，输出决策结果 JSON。"""
    import argparse
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description="麦门渠道官 · 决策引擎")
    parser.add_argument(
        "--scenario",
        default=os.path.join(here, "sample_data", "scenario.json"),
        help="场景 JSON 路径（默认用内置样例）",
    )
    parser.add_argument(
        "--minute-cost",
        type=float,
        default=DEFAULT_MINUTE_COST,
        help="每分钟时间成本折算金额（元/分钟，默认 0.5）",
    )
    parser.add_argument("--pretty", action="store_true", help="缩进输出")
    args = parser.parse_args()

    if not os.path.exists(args.scenario):
        print(f"场景文件不存在：{args.scenario}", file=sys.stderr)
        raise SystemExit(2)

    with open(args.scenario, encoding="utf-8") as fh:
        scenario = json.load(fh)

    result = run_scenario(scenario, minute_cost=args.minute_cost)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
