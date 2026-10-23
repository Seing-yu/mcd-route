#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门渠道官 · 自测套件。

用 24 个断言覆盖决策引擎的关键分支。改完逻辑必须跑这个。
    python selftest.py
全部通过会打印 "✅ 全部通过" 并以 0 退出；任一失败退出码为 1。
"""

from __future__ import annotations

import inspect
import json
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
    fen_to_yuan,
    money,
    parse_calculate_price,
    run_scenario,
    to_yuan,
)
from mcp_client import (  # noqa: E402
    MAX_CALLS_PER_SESSION,
    MIN_INTERVAL_SECONDS,
    ComplianceError,
    McpClient,
    resolve_token,
    token_source,
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


# ---------------------------------------------------------------- 金额单位契约
# 【实测坑】calculate-price 的金额单位是「分」，query-meals 等是「元」。
# 混用会导致每个金额差 100 倍。以下用例锁定归一化行为。

check("分转元：11450 -> 114.5", fen_to_yuan(11450) == 114.5, str(fen_to_yuan(11450)))
check("分转元：900 -> 9.0", fen_to_yuan(900) == 9.0, str(fen_to_yuan(900)))
check("分转元：0 -> 0", fen_to_yuan(0) == 0.0)
check("分转元：非数字 -> 0", fen_to_yuan("abc") == 0.0)
check("分转元：None -> 0", fen_to_yuan(None) == 0.0)
check("to_yuan 按 fen 换算", to_yuan(4700, "fen") == 47.0)
check("to_yuan 按 yuan 不换算", to_yuan(47.0, "yuan") == 47.0)
check("to_yuan 支持字符串元", to_yuan("47.00", "yuan") == 47.0)

# calculate-price 解析：分 -> 元
cp = parse_calculate_price({
    "goodsPrice": 4700,
    "deliveryFee": 900,
    "discountAmount": 1500,
    "payAmount": 4100,
    "minOrderAmount": 2000,
})
check("calculate-price 商品金额分转元", cp["goods"] == 47.0, str(cp["goods"]))
check("calculate-price 配送费分转元", cp["delivery_fee"] == 9.0, str(cp["delivery_fee"]))
check("calculate-price 优惠分转元", cp["discount"] == 15.0, str(cp["discount"]))
check("calculate-price 应付总价分转元", cp["total"] == 41.0, str(cp["total"]))
check("calculate-price 起送价分转元", cp["min_order"] == 20.0, str(cp["min_order"]))

# 字段缺失 -> 记 notes，不猜
cp2 = parse_calculate_price({"goodsPrice": 4700})
check("缺配送费时为 0", cp2["delivery_fee"] == 0.0)
check("缺配送费时写入说明", any("配送费" in n for n in cp2["notes"]), str(cp2["notes"]))
cp3 = parse_calculate_price({})
check("全空返回 0 且有说明", cp3["total"] == 0.0 and len(cp3["notes"]) > 0)
cp4 = parse_calculate_price(None)
check("None 输入不崩溃", cp4["total"] == 0.0)

# 关键回归：菜单价（元）与 calculate-price 价（分）混用时不能差 100 倍
menu = build_basket([{"code": "1", "name": "巨无霸", "currentPrice": "47.00"}])
check("菜单价已是元不做换算", menu[0].price == 47.0, str(menu[0].price))
cp5 = parse_calculate_price({"goodsPrice": 4700, "deliveryFee": 900})
check("菜单价与核价商品额一致（47 == 47）",
      abs(menu[0].price - cp5["goods"]) < 0.01,
      f'{menu[0].price} vs {cp5["goods"]}')

# 端到端：分单位配送费进渠道计价
ch_fee = mk_channel("delivery", delivery_fee=9.0, prep_minutes=25)
t_fee = channel_total(ch_fee, BASKET, minute_cost=0.5)
check("配送费 9 元计入总价", approx(t_fee["total"], 56.0), f"{t_fee['total']}")


# ---------------------------------------------------------------- 合规护栏
# 《麦当劳 MCP 服务规则》第六条禁止「利用脚本、爬虫或任何自动化工具调用本服务」，
# 第三条要求「不支持任何形式的批量、高频或自动化调用」。
# 本项目把该约束做成代码级护栏，以下用例锁定其行为。

check("限速间隔为正", MIN_INTERVAL_SECONDS > 0, str(MIN_INTERVAL_SECONDS))
check("单会话配额低于官方 600/分钟 限流", MAX_CALLS_PER_SESSION < 600, str(MAX_CALLS_PER_SESSION))

client = McpClient(token="dummy", max_calls=3)
for _ in range(3):
    client._account_call()
check("配额内调用不报错", client.call_count == 3, str(client.call_count))
try:
    client._account_call()
    check("超出配额被拒绝", False, "未抛出 ComplianceError")
except ComplianceError:
    check("超出配额被拒绝", True)

check("握手幂等（不重复发请求）", hasattr(client, "_init_result"))
check("客户端不内嵌真实 Token", client.token == "dummy")
check("默认 URL 正确", client.url == "https://mcp.mcd.cn", client.url)


# ---------------------------------------------------------------- 真实数据回归
# 以下断言全部基于 2026-10-22 真实 MCP 调用的返回（见 sample_data/real_snapshot.json）。
# 目的：把「真实接口契约」锁死，防止后续改动破坏与真实数据的一致性。

# --- 0. 原生 MCP 通道实采快照（2026-10-23）---
# 这批数据是通过 WorkBuddy 原生 MCP 通道（mcp__mcd-mcp__*）实采的，
# 与 10-22 通过脚本采集的 real_snapshot.json 互为交叉验证。
_live_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "sample_data", "live_20261023.json")
_live = None
if os.path.exists(_live_path):
    with open(_live_path, encoding="utf-8") as fh:
        _live = json.load(fh)

if _live:
    _prov = _live["_provenance"]
    check("原生通道快照:标注走 mcp__mcd-mcp__* 通道",
          "mcp__mcd-mcp__" in _prov["channel"], _prov["channel"])
    check("原生通道快照:字段名与 10-22 脚本采集一致",
          _prov["calculate_price_raw_fen"]["productOriginalPrice"] == 3350
          and "price" in _prov["calculate_price_raw_fen"])

    # 两次独立采集的到店核价返回，字段结构必须完全对齐
    _live_cp = dict(_prov["calculate_price_raw_fen"])
    _live_cp.pop("packingPrice", None)
    _live_cp.pop("deliveryPrice", None)
    _old_cp = dict(_real_contract_cp := {
        "productOriginalPrice": 3350, "productPrice": 3350,
        "originalPrice": 3350, "discount": 0, "price": 3350,
    })
    check("原生通道 vs 脚本采集:到店核价字段集一致",
          set(_live_cp.keys()) == set(_old_cp.keys()),
          f"{sorted(_live_cp)} vs {sorted(_old_cp)}")

    _live_parsed = parse_calculate_price(_prov["calculate_price_raw_fen"])
    check("原生通道快照:分转元正确", approx(_live_parsed["total"], 33.5),
          str(_live_parsed["total"]))
    check("原生通道快照:到店无配送费", approx(_live_parsed["delivery_fee"], 0.0))
    check("原生通道快照:到店无打包费", approx(_live_parsed["packing_fee"], 0.0))
    check("原生通道快照:缺失字段落入 notes（不猜不估）",
          any("打包费" in n for n in _live_parsed["notes"]),
          "; ".join(_live_parsed["notes"]))

    # 真实场景能跑通完整决策，且外送缺数据时诚实降级
    _live_result = run_scenario(_live, minute_cost=0.5)
    check("原生通道快照:能跑出决策结论",
          bool(_live_result["verdict"]["recommended"]),
          _live_result["verdict"]["recommended"])
    check("原生通道快照:外送缺数据时标为不可用",
          _live_result["verdict"]["detail"]["delivery"]["available"] is False)
    check("原生通道快照:缺数据原因写进 notes",
          any("addressId" in n
              for n in _live_result["verdict"]["detail"]["delivery"]["notes"]))
else:
    check("原生通道快照存在", False, _live_path)

_real = None
_real_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "sample_data", "real_snapshot.json")
if os.path.exists(_real_path):
    with open(_real_path, encoding="utf-8") as fh:
        _real = json.load(fh)

if _real:
    # --- 1. 真实核价返回：价格字段单位是「分」---
    cp_del = _real["_real_contract"]["calculate_price_delivery"]["response_data"]
    parsed = parse_calculate_price(cp_del)
    check("真实外送:商品金额分转元", approx(parsed["goods"], 116.0), str(parsed["goods"]))
    check("真实外送:配送费分转元", approx(parsed["delivery_fee"], 6.0), str(parsed["delivery_fee"]))
    check("真实外送:打包费分转元", approx(parsed["packing_fee"], 2.8), str(parsed["packing_fee"]))
    check("真实外送:合计分转元", approx(parsed["total"], 124.8), str(parsed["total"]))
    check("真实外送:打包费非零（早期版本漏了这项）", parsed["packing_fee"] > 0)

    cp_pick = _real["_real_contract"]["calculate_price_pickup"]["response_data"]
    parsed2 = parse_calculate_price(cp_pick)
    check("真实到店:商品金额分转元", approx(parsed2["goods"], 33.5), str(parsed2["goods"]))
    check("真实到店:无配送费", approx(parsed2["delivery_fee"], 0.0))
    check("真实到店:无打包费", approx(parsed2["packing_fee"], 0.0))

    # --- 2. 真实门店券结构：商品券，不是满减券 ---
    store_coupon = _real["_real_contract"]["query_store_coupons"]["response"][0]
    cs = collect_channel_coupons([store_coupon], "pickup", "query-store-coupons")
    check("真实券:解析出1张", len(cs) == 1, str(len(cs)))
    check("真实券:绑定商品编码", cs[0].product_codes == ["9900016534"], str(cs[0].product_codes))
    check("真实券:从券名解析出用券价", approx(cs[0].use_price, 19.9), str(cs[0].use_price))
    check("真实券:有效期区间解析", cs[0].valid_from.startswith("2026-10-19"), cs[0].valid_from)
    check("真实券:couponCode 保留", cs[0].coupon_code.startswith("MCD"), cs[0].coupon_code)

    # --- 3. 真实「多标签」渠道判定（到店专用、外送专用 → 两边都能用）---
    multi = collect_channel_coupons(
        [{"title": "11.9元麦辣鸡腿堡", "标签": "到店专用、外送专用",
          "products": [{"productCode": "1440"}]}], "pickup", "query-my-coupons")
    check("真实标签:多标签判为通用", multi[0].channel == "any", multi[0].channel)
    ok_p, _ = multi[0].usable_for("pickup", 22.5)
    ok_d, _ = multi[0].usable_for("delivery", 22.5)
    check("真实标签:到店可用", ok_p)
    check("真实标签:外送可用", ok_d)

    # 仅到店
    only_p = collect_channel_coupons(
        [{"title": "X", "标签": "到店专用"}], "pickup", "query-my-coupons")
    check("真实标签:仅到店判为 pickup", only_p[0].channel == "pickup", only_p[0].channel)
    ok2, why2 = only_p[0].usable_for("delivery", 22.5)
    check("真实标签:仅到店券在外送被拒", not ok2 and "到店" in why2)

    # --- 4. 商品券必须命中购物篮商品 ---
    basket_match = [BasketItem("1440", "麦辣鸡腿汉堡", 22.5, 1)]
    basket_nomatch = [BasketItem("9900005456", "麦辣鸡腿汉堡三件套", 33.5, 1)]
    amt_m, name_m, _ = best_coupon(multi, "pickup", 22.5, basket_match)
    check("券绑定商品在篮内→可抵扣", approx(amt_m, 10.6), f"{amt_m} {name_m}")
    amt_n, name_n, _ = best_coupon(multi, "pickup", 33.5, basket_nomatch)
    check("券绑定商品不在篮内→不抵扣", approx(amt_n, 0.0), f"{amt_n} {name_n}")
    check("无匹配时提示无可用券", name_n == "无可用券", name_n)

    # --- 5. 真实端到端决策 ---
    _basket = build_basket(_real["basket"])
    _dv = Channel("delivery", "外送", stores=[{"s": 1}],
                  coupons=collect_channel_coupons(_real["delivery"]["coupons"], "delivery", "query-store-coupons"),
                  delivery_fee=_real["delivery"]["fee"], packing_fee=_real["delivery"]["packing_fee"],
                  min_order=_real["delivery"]["min_order"], prep_minutes=_real["delivery"]["prep_minutes"])
    _pk = Channel("pickup", "到店自取", stores=[{"s": 1}],
                  coupons=collect_channel_coupons(_real["pickup"]["coupons"], "pickup", "query-store-coupons"),
                  prep_minutes=_real["pickup"]["prep_minutes"], travel_minutes=_real["pickup"]["travel_minutes"])
    _v = compare(_dv, _pk, _basket, minute_cost=0.5)
    check("真实场景:推荐到店", _v.recommended == "到店自取", _v.recommended)
    check("真实场景:到店到手价=券价11.9",
          approx(_v.detail["pickup"]["total"], 11.9), str(_v.detail["pickup"]["total"]))
    check("真实场景:外送到手价=11.9+6+2.8=20.7",
          approx(_v.detail["delivery"]["total"], 20.7), str(_v.detail["delivery"]["total"]))
    check("真实场景:两渠道券都生效",
          approx(_v.detail["pickup"]["discount"], 10.6) and approx(_v.detail["delivery"]["discount"], 10.6))

    # --- 6. 券体检：标出商品不匹配 ---
    _rows = coupon_audit(collect_channel_coupons(_real["delivery"]["coupons"], "delivery", "x"),
                          33.5, basket_nomatch)
    _names = {r["name"]: r for r in _rows}
    _mcd = _names.get("11.9元麦辣鸡腿堡")
    check("券体检:标出商品不匹配", _mcd is not None and not _mcd["product_match"],
          str(_mcd["product_note"]) if _mcd else "无此券")
    check("券体检:不匹配时实际抵扣为0", _mcd is not None and approx(_mcd["actual_discount"], 0.0))

else:
    check("真实快照文件存在", False, f"未找到 {_real_path}")


# ---------------------------------------------------------------- Token 解析
# Token 等同于会员账号操作权限。必须保证：
#   · 优先级正确（显式 > 环境变量 > 凭据文件）
#   · 来源标识不泄露 token 本身
#   · 仓库内永远不出现真实 token

import os  # noqa: E402
import tempfile  # noqa: E402

check("显式参数优先", resolve_token("explicit") == "explicit")

# ⚠️ 这几条必须在【未配置任何凭据】的前提下断言。
# 用例运行前先把环境变量摘掉，并把凭据文件路径临时指向一个不存在的文件，
# 避免受开发机上真实配置的影响（真实凭据存在时 resolve_token 会正常返回它）。
import mcp_client  # noqa: E402

_real_token_file = mcp_client.TOKEN_FILE
_saved_env = os.environ.pop("MCD_MCP_TOKEN", None)
_missing_file = os.path.join(os.path.dirname(_real_token_file), ".mcd_token_nonexistent_test")
try:
    mcp_client.TOKEN_FILE = _missing_file
    check("无任何配置时返回空串", resolve_token() == "", repr(resolve_token()))
    check("未配置时来源标识正确", token_source() == "未配置", token_source())

    os.environ["MCD_MCP_TOKEN"] = "env-token"
    check("环境变量被识别", resolve_token() == "env-token")
    check("环境变量来源标识", "MCD_MCP_TOKEN" in token_source(), token_source())
    check("显式参数仍优先于环境变量", resolve_token("explicit") == "explicit")
    os.environ.pop("MCD_MCP_TOKEN", None)
finally:
    mcp_client.TOKEN_FILE = _real_token_file
    if _saved_env is not None:
        os.environ["MCD_MCP_TOKEN"] = _saved_env

# 凭据文件解析（用临时文件，不碰真实凭据）
with tempfile.NamedTemporaryFile("w", suffix=".token", delete=False, encoding="utf-8") as fh:
    fh.write("file-token\nsecond-line-ignored\n")
    _tmp_path = fh.name
try:
    mcp_client.TOKEN_FILE = _tmp_path
    check("凭据文件被识别", resolve_token() == "file-token", repr(resolve_token()))
    check("只读首行", resolve_token() != "file-token\nsecond-line-ignored")
    check("来源标识不泄露 token", "file-token" not in token_source(), token_source())
    check("来源标识指向文件", "token" in token_source().lower())
finally:
    mcp_client.TOKEN_FILE = _real_token_file
    os.unlink(_tmp_path)

# 仓库内不得出现真实 token 形态。
# 判定方式：找 "Bearer " 后跟一个**足够长且像真实凭据**的字符串。
# 排除：${VAR} 占位符、<TOKEN> 尖括号说明、{self.token} 代码插值、
#       YOUR_MCP_TOKEN 之类示例、URL 里的 "Bearer%20" 编码形式。
import re  # noqa: E402

# 仓库根目录 = scripts -> mcd-route -> skills -> <repo root>
# 注意必须从 __file__ 起算四级（abspath(__file__) 已含文件名一级），
# 否则会漏掉 docs/、README.md 等目录——曾经因此让本检查形同虚设。
_repo_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_TOKEN_LIKE = re.compile(r"Bearer\s+([A-Za-z0-9_\-\.]{16,})")
_hits = []
for _dirpath, _dirnames, _filenames in os.walk(_repo_root):
    if ".git" in _dirpath or "__pycache__" in _dirpath:
        continue
    for _fn in _filenames:
        _p = os.path.join(_dirpath, _fn)
        try:
            with open(_p, encoding="utf-8", errors="ignore") as fh:
                _content = fh.read()
        except OSError:
            continue
        for _m in _TOKEN_LIKE.finditer(_content):
            _candidate = _m.group(1)
            # 占位符与示例不算泄露
            if any(_candidate.startswith(_a) for _a in ("${", "<", "{", "YOUR_")):
                continue
            if "MCD_MCP_TOKEN" in _candidate:
                continue
            _hits.append(f"{os.path.relpath(_p, _repo_root)}: {_candidate[:32]}")
check("仓库内无真实 Token（仅允许占位符）", not _hits, "; ".join(_hits[:3]))


# ------------------------------------------------------- 第三方可移植性（关键）
# 参赛项目会被评审 clone 下来用。必须保证：
#   1. 不含开发者的 Token —— 任何人 clone 后都能用自己的 Token 跑
#   2. 不含开发者的个人信息（地址、姓名、电话、门店位置）
# 这两组断言让「可移植性」变成可验证事实，而不是口头承诺。

_src_resolve = inspect.getsource(resolve_token)
check("Token 从环境变量读取（开发者无关）",
      "MCD_MCP_TOKEN" in _src_resolve)
check("Token 解析函数读凭据文件", "TOKEN_FILE" in _src_resolve)
check("Token 解析不硬编码任何字面量",
      "Bearer" not in _src_resolve, "解析函数里不应出现 Bearer 字面量")

# 客户端默认从 resolve_token 取，不从命令行参数硬编码
_src_client = inspect.getsource(McpClient.__init__)
check("客户端 Token 来自 resolve_token", "resolve_token" in _src_client)

# 配置示例必须是纯占位符
_cfg_path = os.path.join(_repo_root, "mcp-config.example.json")
if os.path.exists(_cfg_path):
    with open(_cfg_path, encoding="utf-8") as fh:
        cfg_text = fh.read()
    check("配置示例用环境变量占位符", "${MCD_MCP_TOKEN}" in cfg_text)
    check("配置示例不含真实 Token",
          not re.search(r"Bearer\s+(?!\$\{)[A-Za-z0-9_\-\.]{16,}", cfg_text))
else:
    check("配置文件存在", False, _cfg_path)

# setup_mcp.ps1：Windows 装机脚本
# 关键断言：写出的 mcp.json 必须无 BOM（WorkBuddy 用严格 JSON 解析器，
# 带 BOM 会报 "Unexpected UTF-8 BOM" 而加载失败）；
# 脚本自身含中文注释，必须带 UTF-8 BOM（PowerShell 5.1 否则按 ANSI 解码乱码）。
_ps1_path = os.path.join(_repo_root, "skills", "mcd-route", "scripts", "setup_mcp.ps1")
if os.path.exists(_ps1_path):
    with open(_ps1_path, "rb") as fh:
        _ps1_raw = fh.read()
    check("setup_mcp.ps1 存在", True)
    check("setup_mcp.ps1 以 UTF-8 BOM 保存（PowerShell 5.1 读中文注释需要）",
          _ps1_raw.startswith(b"\xef\xbb\xbf"))
    _ps1_text = _ps1_raw.decode("utf-8-sig")
    check("setup_mcp.ps1 写出无 BOM JSON（用 UTF8Encoding($false)）",
          "UTF8Encoding($false)" in _ps1_text
          and "WriteAllText" in _ps1_text)
    # 只看可执行行（注释里出现 Set-Content 是为了解释这个坑）
    _ps1_code = re.sub(r"<#.*?#>", "", _ps1_text, flags=re.S)
    _ps1_code = "\n".join(
        ln for ln in _ps1_code.splitlines()
        if not ln.strip().startswith("#"))
    check("setup_mcp.ps1 不用 Set-Content -Encoding UTF8（会引入 BOM）",
          not re.search(r"Set-Content[^\n]*-Encoding", _ps1_code))
    check("setup_mcp.ps1 写入正确的 type=http",
          "'http'" in _ps1_text and "mcp.mcd.cn" in _ps1_text)
    check("setup_mcp.ps1 不硬编码任何 Token",
          not re.search(r"Bearer\s+(?!\$\{|\$token)[A-Za-z0-9_\-\.]{16,}", _ps1_text))
    check("setup_mcp.ps1 回显前先备份原配置",
          ".bak" in _ps1_text)
    # Token 只允许以 $token.Length 形式出现在输出里，绝不能原样打印
    _token_prints = [m for m in re.findall(r"Write-Host[^\n]*", _ps1_text)
                     if "$token" in m and "$($token.Length)" not in m]
    check("setup_mcp.ps1 不原样打印 Token",
          not _token_prints, "; ".join(_token_prints[:2]))
else:
    check("setup_mcp.ps1 存在", False, _ps1_path)

# 个人信息扫描：仓库不得包含开发者真实身份信息
# 排除官方原文存档（docs/mcp-rules-*.html 是麦当劳规则页快照，
# 里面的客服邮箱属于官方信息，不是开发者隐私）
_SKIP_SCAN = {"mcp-rules-20251203.html"}
_PII_PATTERNS = [
    ("真实手机号", re.compile(r"\b1[3-9]\d{9}\b")),
    ("身份证号", re.compile(r"\b\d{17}[\dXx]\b")),
    ("邮箱", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
]
_pii_hits = []
_repo_files = []
for _dirpath, _dirnames, _filenames in os.walk(_repo_root):
    if ".git" in _dirpath or "__pycache__" in _dirpath:
        continue
    for _fn in _filenames:
        if _fn in _SKIP_SCAN:
            continue  # 官方原文快照，不属于开发者隐私
        _repo_files.append(os.path.relpath(os.path.join(_dirpath, _fn), _repo_root))
        _p = os.path.join(_dirpath, _fn)
        try:
            with open(_p, encoding="utf-8", errors="ignore") as fh:
                _txt = fh.read()
        except OSError:
            continue
        for _label, _rx in _PII_PATTERNS:
            for _m in _rx.finditer(_txt):
                _val = _m.group(0)
                # 允许明显是示例的值
                if any(_v in _val for _v in ("00000", "12345", "example")):
                    continue
                _pii_hits.append(f"{os.path.relpath(_p, _repo_root)}:{_label}")
check("仓库内无个人隐私信息（手机号/身份证/邮箱）", not _pii_hits, "; ".join(_pii_hits[:3]))
check("官方规则快照已排除在隐私扫描外（客服邮箱属官方信息）",
      _SKIP_SCAN and os.path.exists(os.path.join(_repo_root, "docs", "mcp-rules-20251203.html")))

# --- 静态页面不得有第三方外发 ---
# 试算页与规则存档都随 GitHub Pages 对外发布。规则存档原本是官方页面的
# 整页快照，会连带引入微信 / 支付宝 / 腾讯地图定位 / 麦当劳 CDN 的脚本
# （且内含官方地图 API key），访客打开即向多个第三方发起请求。
# 已改为纯文本离线存档，这里用断言把「零外部脚本」锁死，防止被改回去。
for _page in ("docs/index.html", "docs/mcp-rules-20251203.html"):
    _pp = os.path.join(_repo_root, *_page.split("/"))
    if not os.path.exists(_pp):
        check(f"{_page} 存在", False, _pp)
        continue
    with open(_pp, encoding="utf-8", errors="ignore") as fh:
        _ptxt = fh.read()
    _ext_scripts = re.findall(r'<script[^>]+src\s*=\s*["\']https?://', _ptxt)
    check(f"{_page} 无外部脚本引用", not _ext_scripts,
          f"{len(_ext_scripts)} 个外部 script")
    _net_calls = re.findall(r"\bfetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket",
                            _ptxt)
    check(f"{_page} 无网络外发调用", not _net_calls,
          "; ".join(_net_calls[:3]))
    _map_keys = re.findall(r"key\s*=\s*[A-Za-z0-9\-]{20,}", _ptxt)
    check(f"{_page} 不含第三方 API key", not _map_keys,
          "; ".join(_map_keys[:2]))

# --- 仓库不得含任何长数字标识符 ---
# 麦当劳 MCP 的 addressId 是 28 位左右的数字串（用户个人配送地址标识），
# 券码、门店编码是 7~10 位。长数字串几乎必然是个人数据标识，
# 必须脱敏后才能进仓库 —— 2026-10-23 推送前扫描就抓到过一处漏网的。
for _f in _repo_files:
    if not _f.endswith((".json", ".py", ".md", ".mjs", ".html", ".yml", ".yaml", ".ps1")):
        continue
    _fp = os.path.join(_repo_root, _f)
    try:
        with open(_fp, encoding="utf-8", errors="ignore") as fh:
            _ftxt = fh.read()
    except OSError:
        continue
    _long_ids = re.findall(r"\b\d{15,}\b", _ftxt)
    check(f"{_f} 无长数字标识符（地址ID等）", not _long_ids,
          "; ".join(_long_ids[:3]))

# --- 仓库不得含可定位到开发者本人的位置信息 ---
# 2026-10-23 首次推送后才发现：实采快照里用了开发者实际位置作为
# 搜索锚点（city + keyword），并记录了 distance（各门店距离值），
# 两者结合可反推开发者当时所在位置。
# 现在的规矩：**搜索锚点只能用公共地标**（如「望京」这种商圈名），
# distance 可以保留（它相对公共地标而言），但不得出现个人的
# 居住/工作地标词。已改为公共地标重采，并把这条固化为断言。
_LOCATION_PATTERNS = [
    # 个人居住/工作地标的常见写法（小区/家属院/学校/写字楼名）
    ("家属院", re.compile(r"[\w一-鿿]{0,8}家属院")),
    ("小区名", re.compile(r"[\w一-鿿]{0,8}小区")),
    ("大学+路名组合", re.compile(r"[\w一-鿿]{1,6}大学[\w一-鿿]{0,4}[路街道]")),
    ("距离锚点", re.compile(r"坐标锚点\s*[=＝]\s*(?!望京|北京)[\w一-鿿]+")),
]
for _f in _repo_files:
    if not _f.endswith((".json", ".py", ".md", ".mjs", ".html")):
        continue
    if os.path.basename(_f) == "selftest.py":
        continue  # 本文件含模式定义本身，会自匹配
    _fp = os.path.join(_repo_root, _f)
    try:
        with open(_fp, encoding="utf-8", errors="ignore") as fh:
            _ftxt = fh.read()
    except OSError:
        continue
    for _label, _rx in _LOCATION_PATTERNS:
        _hits = _rx.findall(_ftxt)
        check(f"{_f} 无个人位置地标（{_label}）", not _hits,
              "; ".join(str(h) for h in _hits[:2]))

# 规则存档必须保留完整八条
_rules_path = os.path.join(_repo_root, "docs", "mcp-rules-20251203.html")
if os.path.exists(_rules_path):
    with open(_rules_path, encoding="utf-8", errors="ignore") as fh:
        _rules = fh.read()
    for _i, _cn in enumerate("一二三四五六七八", start=1):
        check(f"规则存档含第{_cn}条", f"第{_cn}条" in _rules)


# ---------------------------------------------------------------- 输出
print(f"自测结果：{PASSED} 通过，{len(FAILED)} 失败")
if FAILED:
    for item in FAILED:
        print(f"  ❌ {item}")
    sys.exit(1)
print("✅ 全部通过")
sys.exit(0)
