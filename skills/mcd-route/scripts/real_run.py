#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门渠道官 · 真实链路走查。

用真实 Token 跑一遍完整决策链路，输出可复核的中间结果。
**这是「真实使用麦当劳 MCP」的直接证据**——评审可自行复现。

    python real_run.py                      # 走默认流程（需先选门店）
    python real_run.py --city 北京 --keyword 望京
    python real_run.py --json               # 机器可读输出

⚠️ 本脚本**只调用只读接口**，不下单、不领券、不改账户状态。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decider import (  # noqa: E402
    BasketItem,
    Channel,
    build_basket,
    collect_channel_coupons,
    compare,
    coupon_audit,
    parse_calculate_price,
)
from mcp_client import McpClient, McpError, resolve_token, token_source  # noqa: E402


def extract_json(text: str):
    """从「散文说明 + 内嵌 JSON」的混合文本中提取 JSON。

    【实测坑】不能用正则贪婪匹配——说明文字里也有花括号，
    必须**括号配平**地找第一个完整的 JSON 对象。
    """
    depth = 0
    start = None
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    start = None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="真实链路走查（只读）")
    parser.add_argument("--city", default="北京", help="城市名")
    parser.add_argument("--keyword", default="望京", help="位置关键词")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    token = resolve_token()
    if not token:
        print("❌ 未配置 MCP Token。先运行：python setup_token.py", file=sys.stderr)
        return 2

    client = McpClient(token=token)
    report: dict = {"token_source": token_source()}

    print(f"凭据来源：{token_source()}")
    client.initialize()
    print(f"协议版本：{client.protocol_version}  服务器：{client.server_info.get('name')}")

    tools = client.list_tools()
    report["tool_count"] = len(tools)
    print(f"服务器提供 {len(tools)} 个 Tool")

    # ---- 1. 到店门店 ----
    print("\n1) query-nearby-stores（到店门店）")
    raw = client.call("query-nearby-stores", {
        "beType": 1, "searchType": 2, "city": args.city, "keyword": args.keyword,
    })
    data = (extract_json(raw) or {}).get("data") or []
    if not data:
        print("   未取到门店", file=sys.stderr)
        return 1
    for store in data[:3]:
        print(f"   {store.get('storeName')}  距离 {store.get('distance')}m  "
              f"storeCode={store.get('storeCode')}")
    pickup_store = data[0]
    report["pickup_store"] = pickup_store

    # ---- 2. 到店菜单 ----
    print("\n2) query-meals（到店菜单）")
    raw = client.call("query-meals", {
        "storeCode": pickup_store["storeCode"], "beType": 1, "orderType": 1,
    })
    meals = ((extract_json(raw) or {}).get("data") or {}).get("meals") or {}
    print(f"   在售 {len(meals)} 款")
    report["pickup_meal_count"] = len(meals)

    # ---- 3. 门店券 ----
    print("\n3) query-store-coupons（门店券）")
    raw = client.call("query-store-coupons", {
        "storeCode": pickup_store["storeCode"], "beType": 1, "orderType": 1,
    })
    store_coupons = extract_json(raw) or []
    if isinstance(store_coupons, dict):
        store_coupons = store_coupons.get("data") or []
    print(f"   {len(store_coupons)} 张")
    for coupon in store_coupons[:3]:
        names = ", ".join(p.get("productName", "") for p in coupon.get("products", []))
        print(f"   · {coupon.get('title')}  绑定商品: {names}")
    report["store_coupon_count"] = len(store_coupons)

    # ---- 4. 卡包券 ----
    print("\n4) query-my-coupons（卡包券）")
    raw = client.call("query-my-coupons", {})
    card_coupons = parse_markdown_coupons(raw)
    print(f"   {len(card_coupons)} 张")
    for coupon in card_coupons[:3]:
        print(f"   · {coupon.get('title')}  优惠 {coupon.get('优惠')}  标签 {coupon.get('标签')}")
    report["card_coupon_count"] = len(card_coupons)

    # ---- 5. 选一件商品做核价 ----
    target = pick_target_meal(meals, store_coupons)
    if not target:
        print("\n未找到可用于演示的商品", file=sys.stderr)
        return 1
    print(f"\n5) 选取商品：{target['name']}  现价 ¥{target['currentPrice']}  code={target['code']}")

    print("\n6) calculate-price（到店核价）")
    raw = client.call("calculate-price", {
        "storeCode": pickup_store["storeCode"], "beType": 1, "orderType": 1,
        "items": [{"productCode": target["code"], "quantity": 1}],
    })
    cp_pickup = parse_calculate_price((extract_json(raw) or {}).get("data") or {})
    print(f"   商品 ¥{cp_pickup['goods']}  配送费 ¥{cp_pickup['delivery_fee']}  "
          f"打包费 ¥{cp_pickup['packing_fee']}  应付 ¥{cp_pickup['total']}")
    report["calculate_price_pickup"] = cp_pickup

    # ---- 7. 配送地址与配送门店（用于外送侧真实数据）----
    delivery_store = None
    delivery_fee = 0.0
    packing_fee = 0.0
    print("\n7) 外送侧（配送地址 → 可配送门店 → 配送费）")
    try:
        raw = client.call("delivery-query-addresses", {})
        # 实测结构：{success, code, message, data:{addresses:[...]}}
        addresses = ((extract_json(raw) or {}).get("data") or {}).get("addresses") or []
        if addresses:
            address = addresses[0]
            print(f"   配送地址：{address.get('fullAddress', '')[:28]}…（手机号已脱敏）")
            report["delivery_address_count"] = len(addresses)

            raw = client.call("delivery-query-stores", {
                "addressId": address["addressId"], "beType": 2,
            })
            delivery_data = (extract_json(raw) or {}).get("data") or []
            if delivery_data:
                delivery_store = delivery_data[0]
                print(f"   可配送：{delivery_store.get('storeName')}  beCode={delivery_store.get('beCode')}")
                report["delivery_store"] = delivery_store

                # 取配送门店的菜单并核价，拿到真实配送费与打包费
                raw = client.call("query-meals", {
                    "storeCode": delivery_store["storeCode"],
                    "beCode": delivery_store.get("beCode"),
                    "beType": 2, "orderType": 2,
                })
                d_meals = ((extract_json(raw) or {}).get("data") or {}).get("meals") or {}
                d_target = pick_target_meal(d_meals, store_coupons)
                if d_target:
                    raw = client.call("calculate-price", {
                        "storeCode": delivery_store["storeCode"],
                        "beCode": delivery_store.get("beCode"),
                        "beType": 2, "orderType": 2,
                        "items": [{"productCode": d_target["code"], "quantity": 1}],
                    })
                    cp_delivery = parse_calculate_price((extract_json(raw) or {}).get("data") or {})
                    delivery_fee = cp_delivery["delivery_fee"]
                    packing_fee = cp_delivery["packing_fee"]
                    print(f"   外送核价：商品 ¥{cp_delivery['goods']}  "
                          f"配送费 ¥{delivery_fee}  打包费 ¥{packing_fee}  "
                          f"应付 ¥{cp_delivery['total']}")
                    report["calculate_price_delivery"] = cp_delivery
        else:
            print("   （无配送地址，跳过外送侧取数）")
    except McpError as exc:
        print(f"   外送侧取数失败：{exc}")

    # ---- 8. 决策 ----
    print("\n8) 渠道决策")
    basket = [BasketItem(target["code"], target["name"], float(target["currentPrice"]), 1)]
    pickup = Channel(
        key="pickup", label="到店自取", stores=[pickup_store],
        coupons=collect_channel_coupons(store_coupons, "pickup", "query-store-coupons"),
        prep_minutes=8, travel_minutes=20,
    )
    delivery = Channel(
        key="delivery", label="外送",
        stores=[delivery_store] if delivery_store else [],
        coupons=collect_channel_coupons(store_coupons, "delivery", "query-store-coupons"),
        delivery_fee=delivery_fee, packing_fee=packing_fee, prep_minutes=25,
    )
    verdict = compare(delivery, pickup, basket, minute_cost=0.5)
    print(f"   {verdict.recommended}")
    print(f"   {verdict.reason}")
    report["verdict"] = verdict.to_dict()

    print("\n9) 券体检")
    for row in coupon_audit(pickup.coupons, basket[0].total, basket):
        print(f"   · {row['name']}  实际抵扣 ¥{row['actual_discount']}  {row['product_note']}")
    report["coupon_audit"] = coupon_audit(pickup.coupons, basket[0].total, basket)

    if args.json:
        print("\n" + json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"\n本会话共发起 {client.call_count} 次调用（限速与配额由 mcp_client.py 强制）")
        print("🎉 真实链路走查完成。全程只读，未下单、未领券、未修改账户状态。")
    return 0


def parse_markdown_coupons(text: str) -> list[dict]:
    """解析 query-my-coupons 的 Markdown 返回。

    【实测格式】
        ## 11.9元麦辣鸡腿堡
        - **优惠**: ¥11.9 (用券价格)
        - **有效期**: 2026-10-19 10:30-2026-10-23 23:59 ...
        - **标签**: 到店专用、外送专用
    """
    coupons: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current = {"title": stripped[3:].strip()}
            coupons.append(current)
        elif current is not None and stripped.startswith("- "):
            match = re.match(r"-\s*\*\*(.+?)\*\*:\s*(.+)", stripped)
            if match:
                current[match.group(1).strip()] = match.group(2).strip()
    return coupons


def pick_target_meal(meals: dict, store_coupons: list) -> dict | None:
    """优先挑一张券绑定的商品，这样能演示「券真的用上了」。"""
    bound_codes: set[str] = set()
    for coupon in store_coupons:
        for product in coupon.get("products", []):
            if product.get("productCode"):
                bound_codes.add(str(product["productCode"]))

    for code in bound_codes:
        meal = meals.get(code)
        if meal and meal.get("currentPrice"):
            return {
                "code": code,
                "name": meal.get("name", code),
                "currentPrice": meal.get("currentPrice"),
            }

    for code, meal in meals.items():
        if isinstance(meal, dict) and meal.get("currentPrice"):
            return {"code": code, "name": meal.get("name", code), "currentPrice": meal["currentPrice"]}
    return None


if __name__ == "__main__":
    raise SystemExit(main())
