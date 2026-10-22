#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门渠道官 · 自测套件。

用 24 个断言覆盖决策引擎的关键分支。改完逻辑必须跑这个。
    python selftest.py
全部通过会打印 "✅ 全部通过" 并以 0 退出；任一失败退出码为 1。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decider import (  # noqa: E402
    BasketItem,
    Channel,
    Coupon,
    best_coupon,
    build_basket,
    channel_total,
    collect_channel_coupons,
    compare,
    coupon_audit,
    money,
)

PASSED = 0
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if condition:
        PASSED += 1
    else:
        FAILED.append(f"{name}  {detail}")


def approx(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


def mk_channel(key: str, **kw) -> Channel:
    defaults = dict(
        label=key,
        stores=[{"storeCode": "S1"}],
        coupons=[],
        delivery_fee=0.0,
        min_order=0.0,
        prep_minutes=0,
        travel_minutes=0,
        min_order_met=True,
    )
    defaults.update(kw)
    return Channel(key=key, **defaults)


BASKET = [BasketItem("101", "巨无霸套餐", 47.0, 1)]
CHEAP = [BasketItem("102", "麦辣鸡腿堡", 22.0, 1)]


# ---------------------------------------------------------------- 金额格式化
check("money 整数不带小数点", money(47.0) == "47", money(47.0))
check("money 两位小数", money(46.5) == "46.50", money(46.5))
check("money 负数", money(-3.0) == "-3", money(-3.0))


# ---------------------------------------------------------------- 券可用性
c_any = Coupon("A", "通用券", 6.0, 0.0, "any")
c_pick = Coupon("P", "门店券", 15.0, 40.0, "pickup")
c_del = Coupon("D", "配送券", 9.0, 30.0, "delivery")
c_high = Coupon("H", "大额券", 20.0, 100.0, "any")

ok, why = c_any.usable_for("pickup", 10.0)
check("通用券两个渠道都能用", ok and why == "")
ok, why = c_pick.usable_for("delivery", 50.0)
check("到店券在外送被拒", not ok and "仅限" in why)
ok, why = c_del.usable_for("pickup", 50.0)
check("外送券在到店被拒", not ok and "仅限" in why)
ok, why = c_high.usable_for("pickup", 50.0)
check("未达门槛被拒", not ok and "门槛" in why)
ok, _ = c_high.usable_for("pickup", 120.0)
check("达门槛可用", ok)


# ---------------------------------------------------------------- 选券
amt, name, ids = best_coupon([c_any, c_pick, c_del, c_high], "pickup", 47.0)
check("到店选最大抵扣券", approx(amt, 15.0) and name == "门店券", f"{amt} {name}")
amt, name, ids = best_coupon([c_any, c_pick, c_del, c_high], "delivery", 47.0)
check("外送选最大抵扣券", approx(amt, 9.0) and name == "配送券", f"{amt} {name}")
amt, _, _ = best_coupon([c_any, c_pick, c_del], "pickup", 20.0)
check("金额不达门槛时退回通用券", approx(amt, 6.0), f"{amt}")
amt, _, _ = best_coupon([], "pickup", 100.0)
check("无券时抵扣为0", approx(amt, 0.0))
amt, _, _ = best_coupon([c_pick], "delivery", 100.0)
check("跨渠道券不被选用", approx(amt, 0.0))


# ---------------------------------------------------------------- 渠道计价
ch = mk_channel("pickup", coupons=[c_pick], prep_minutes=8, travel_minutes=20)
t = channel_total(ch, BASKET, minute_cost=0.5)
check("到店无配送费", approx(t["total"], 32.0), f"{t['total']}")
check("到店时间分钟=往返+出餐", t["minutes"] == 28, f"{t['minutes']}")
check("到店时间成本", approx(t["time_cost"], 14.0), f"{t['time_cost']}")
check("到店总成本", approx(t["grand_total"], 46.0), f"{t['grand_total']}")

ch = mk_channel("delivery", coupons=[c_del], delivery_fee=9.0, prep_minutes=25)
t = channel_total(ch, BASKET, minute_cost=0.5)
check("外送券抵配送费后总价=原价", approx(t["total"], 47.0), f"{t['total']}")
check("外送时间只算等餐", t["minutes"] == 25, f"{t['minutes']}")


# ---------------------------------------------------------------- 归一化
raw = [
    {"id": "x1", "name": "券A", "discount": 10, "threshold": 30, "channel": "delivery"},
    {"couponId": "x2", "couponName": "券B", "amount": 5, "scene": "到店"},
    {"name": "券C", "value": 3},
]
out = collect_channel_coupons(raw, "pickup", source="test")
check("归一化条数正确", len(out) == 3, f"{len(out)}")
check("字段名兼容 discount", approx(out[0].discount, 10.0))
check("字段名兼容 amount", approx(out[1].discount, 5.0))
check("字段名兼容 value", approx(out[2].discount, 3.0))
check("中文场景映射到 pickup", out[1].channel == "pickup", out[1].channel)
check("缺省场景为 any", out[2].channel == "any", out[2].channel)
check("缺 id 时补全", bool(out[2].id))


# ---------------------------------------------------------------- 决策分支
d = mk_channel("delivery", coupons=[c_del], delivery_fee=9.0, prep_minutes=25)
p = mk_channel("pickup", coupons=[c_pick], prep_minutes=8, travel_minutes=20)
v = compare(d, p, BASKET)
check("双渠道可用时给出建议", v.recommended in ("到店自取", "点外送"), v.recommended)
check("推荐到店（门店券更强）", v.recommended == "到店自取", v.recommended)
check("详情含两渠道", "delivery" in v.detail and "pickup" in v.detail)

d2 = mk_channel("delivery", delivery_fee=9.0, prep_minutes=25)
p2 = mk_channel("pickup", prep_minutes=8, travel_minutes=20)
v = compare(d2, p2, BASKET)
check("无券时外送更贵选到店", v.recommended == "到店自取", v.recommended)

d3 = mk_channel("delivery", delivery_fee=9.0, prep_minutes=25)
p3 = mk_channel("pickup", prep_minutes=8, travel_minutes=0)
v = compare(d3, p3, BASKET)
check("时间成本为零时按到手价判", v.recommended == "到店自取", v.recommended)

d4 = mk_channel("delivery", delivery_fee=60.0, prep_minutes=25)
p4 = mk_channel("pickup", prep_minutes=8, travel_minutes=20)
v = compare(d4, p4, BASKET)
check("高配送费选到店", v.recommended == "到店自取", v.recommended)

# 时间成本足够高时，外送可能反超
d5 = mk_channel("delivery", delivery_fee=9.0, prep_minutes=25)
p5 = mk_channel("pickup", prep_minutes=8, travel_minutes=200)
v = compare(d5, p5, BASKET, minute_cost=0.5)
check("往返超长时可能翻转为外送", v.recommended in ("到店自取", "点外送"), v.recommended)

# 起送价未达标
d6 = mk_channel("delivery", min_order=100.0, min_order_met=False, notes=["未达起送价 100 元"])
p6 = mk_channel("pickup")
v = compare(d6, p6, BASKET)
check("外送起送价未达标时推荐到店", v.recommended == "到店自取", v.recommended)
check("理由引用了起送价信息", "起送价" in v.reason, v.reason)

d7 = mk_channel("delivery", min_order=100.0, min_order_met=False, notes=["未达起送价"])
p7 = mk_channel("pickup", stores=[])
v = compare(d7, p7, BASKET)
check("两边都不可用", v.recommended == "都不行", v.recommended)

d8 = mk_channel("delivery")
p8 = mk_channel("pickup", stores=[])
v = compare(d8, p8, BASKET)
check("只有外送可用", v.recommended == "点外送", v.recommended)

d9 = mk_channel("delivery", stores=[])
p9 = mk_channel("pickup")
v = compare(d9, p9, BASKET)
check("只有到店可用", v.recommended == "到店自取", v.recommended)


# ---------------------------------------------------------------- 券体检
rows = coupon_audit([c_pick, c_del, c_any], 47.0)
check("券体检条数", len(rows) == 3)
check("券体检按抵扣降序", rows[0]["discount"] >= rows[1]["discount"])
verdicts = {r["name"]: r["verdict"] for r in rows}
check("到店券标注仅到店可用", verdicts["门店券"] == "仅到店可用", verdicts["门店券"])
check("通用券标注两渠道可用", verdicts["通用券"] == "两个渠道都能用", verdicts["通用券"])


# ---------------------------------------------------------------- 购物篮
basket = build_basket([
    {"code": "1", "name": "汉堡", "price": 20, "qty": 2},
    {"itemCode": "2", "itemName": "可乐", "price": 9},
    {"bad": True},
])
check("购物篮过滤脏数据", len(basket) == 2, f"{len(basket)}")
check("qty 生效", basket[0].total == 40.0, f"{basket[0].total}")
check("字段名兼容 itemCode", basket[1].code == "2")
check("缺 qty 默认为1", basket[1].qty == 1)


# ---------------------------------------------------------------- 输出
print(f"自测结果：{PASSED} 通过，{len(FAILED)} 失败")
if FAILED:
    for item in FAILED:
        print(f"  ❌ {item}")
    sys.exit(1)
print("✅ 全部通过")
sys.exit(0)
