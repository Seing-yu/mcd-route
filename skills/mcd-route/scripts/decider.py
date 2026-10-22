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
    coupons: list[dict] = field(default_factory=list)  # 该渠道可用的券
    delivery_fee: float = 0.0     # 配送费（到店为 0）
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
    """一张券。channel 决定它能在哪用：any / delivery / pickup。"""

    id: str
    name: str
    discount: float = 0.0
    threshold: float = 0.0       # 满多少可用
    channel: str = "any"
    source: str = ""             # 从哪个 Tool 取到的
    stackable: bool = True
    note: str = ""

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


def best_coupon(coupons: Iterable[Coupon], channel_key: str, amount: float) -> tuple[float, str, list[str]]:
    """在给定渠道和金额下，选出抵扣最多的那一张券。

    返回 (抵扣金额, 券名, 参与计算的券 id 列表)。
    保守策略：只选单张最优券，不做叠加以免报出实际用不了的低价。
    """
    best_amount = 0.0
    best_name = "无可用券"
    best_ids: list[str] = []
    for coupon in coupons:
        ok, _ = coupon.usable_for(channel_key, amount)
        if not ok:
            continue
        if coupon.discount > best_amount:
            best_amount = coupon.discount
            best_name = coupon.name
            best_ids = [coupon.id]
    return best_amount, best_name, best_ids


def collect_channel_coupons(
    raw_coupons: Iterable[dict],
    channel_key: str,
    source: str = "",
) -> list[Coupon]:
    """把 MCP 返回的券列表归一化成 Coupon 对象。

    MCP 各券接口的字段名不完全一致，这里做一次宽松映射。
    """
    out: list[Coupon] = []
    for index, raw in enumerate(raw_coupons or []):
        if not isinstance(raw, dict):
            continue
        cid = str(raw.get("id") or raw.get("couponId") or raw.get("code") or f"{source}-{index}")
        name = str(raw.get("name") or raw.get("couponName") or raw.get("title") or cid)
        # 抵扣额：兼容多种字段名
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
        # 渠道限制：兼容 scene / channel / useChannel 等等
        channel = str(raw.get("channel") or raw.get("scene") or raw.get("useChannel") or "any").lower()
        if channel in ("delivery", "外送", "麦乐送", "takeout_delivery"):
            channel = "delivery"
        elif channel in ("pickup", "到店", "自取", "堂食", "store"):
            channel = "pickup"
        else:
            channel = "any"
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
            )
        )
    return out


def channel_total(
    channel: Channel,
    basket: list[BasketItem],
    minute_cost: float = DEFAULT_MINUTE_COST,
) -> dict:
    """算某个渠道下的到手价与总成本。"""
    goods = round(sum(item.total for item in basket), 2)
    discount, coupon_name, coupon_ids = best_coupon(channel.coupons, channel.key, goods)
    after_discount = round(max(goods - discount, 0.0), 2)
    total = round(after_discount + channel.delivery_fee, 2)

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


def coupon_audit(coupons: list[Coupon], basket_total: float) -> list[dict]:
    """券体检：逐张券算出名义面额、实际能不能用、值不值得用。

    这是「券越多越容易亏」的关键——一张小额券可能挤掉大组合。
    """
    rows: list[dict] = []
    for coupon in coupons:
        ok_pickup, why_pickup = coupon.usable_for("pickup", basket_total)
        ok_delivery, why_delivery = coupon.usable_for("delivery", basket_total)
        if not ok_pickup and not ok_delivery:
            verdict = "用不了"
        elif ok_pickup and ok_delivery:
            verdict = "两个渠道都能用"
        elif ok_pickup:
            verdict = "仅到店可用"
        else:
            verdict = "仅外送可用"
        rows.append(
            {
                "name": coupon.name,
                "discount": coupon.discount,
                "threshold": coupon.threshold,
                "verdict": verdict,
                "reason": why_pickup or why_delivery or "",
                "source": coupon.source,
            }
        )
    rows.sort(key=lambda r: -r["discount"])
    return rows


def build_basket(items: Iterable[dict]) -> list[BasketItem]:
    """从 MCP 菜单数据构造购物篮。"""
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
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = 0.0
        qty = int(raw.get("qty") or raw.get("count") or 1)
        basket.append(BasketItem(code=code, name=name, price=price, qty=qty))
    return basket


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
        "coupon_audit": coupon_audit(delivery.coupons + pickup.coupons, goods_total),
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
