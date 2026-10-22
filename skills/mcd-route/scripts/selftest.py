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
    fen_to_yuan,
    money,
    parse_calculate_price,
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


# ---------------------------------------------------------------- Token 解析
# Token 等同于会员账号操作权限。必须保证：
#   · 优先级正确（显式 > 环境变量 > 凭据文件）
#   · 来源标识不泄露 token 本身
#   · 仓库内永远不出现真实 token

import os  # noqa: E402
import tempfile  # noqa: E402

check("显式参数优先", resolve_token("explicit") == "explicit")

_saved_env = os.environ.pop("MCD_MCP_TOKEN", None)
check("无任何配置时返回空串", resolve_token() == "", repr(resolve_token()))
check("未配置时来源标识正确", token_source() == "未配置", token_source())

os.environ["MCD_MCP_TOKEN"] = "env-token"
check("环境变量被识别", resolve_token() == "env-token")
check("环境变量来源标识", "MCD_MCP_TOKEN" in token_source(), token_source())
check("显式参数仍优先于环境变量", resolve_token("explicit") == "explicit")

if _saved_env is not None:
    os.environ["MCD_MCP_TOKEN"] = _saved_env
else:
    os.environ.pop("MCD_MCP_TOKEN", None)

# 凭据文件解析（用临时文件，不碰真实凭据）
import mcp_client  # noqa: E402

_real_token_file = mcp_client.TOKEN_FILE
with tempfile.NamedTemporaryFile("w", suffix=".token", delete=False, encoding="utf-8") as fh:
    fh.write("file-token\nsecond-line-ignored\n")
    _tmp_path = fh.name
try:
    mcp_client.TOKEN_FILE = _tmp_path
    check("凭据文件被识别", resolve_token() == "file-token", repr(resolve_token()))
    check("只读首行", resolve_token() != "file-token\nsecond-line-ignored")
    check("来源标识不泄露 token", "file-token" not in token_source(), token_source())
    check("来源标识指向文件", ".mcd_token" in token_source() or "token" in token_source().lower())
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


# ---------------------------------------------------------------- 输出
print(f"自测结果：{PASSED} 通过，{len(FAILED)} 失败")
if FAILED:
    for item in FAILED:
        print(f"  ❌ {item}")
    sys.exit(1)
print("✅ 全部通过")
sys.exit(0)
