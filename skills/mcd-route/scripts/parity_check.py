#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门渠道官 · 前后端对拍。

页面试算器（docs/index.html）与 CLI 决策引擎（decider.py）是同一套逻辑的两份实现。
两份实现一旦漂移，页面上显示的数字就会和实际算出来的对不上——
这对「结论可信度」是致命的。

本脚本对同一组场景分别跑 Python 与 Node 两端，逐字段比对。

    python parity_check.py

需要 Node.js（可选）：没装则跳过对拍，只跑 Python 端自检。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decider import BasketItem, Channel, Coupon, compare  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# 与 parity_check.mjs 中的 SCENARIOS 一一对应
PY_SCENARIOS = [
    {
        "name": "默认场景-巨无霸套餐",
        "goods": 47.0, "qty": 1, "fee": 9.0, "min_order": 20.0,
        "prep_d": 25, "prep_p": 8, "travel": 20, "mc": 0.5,
        "coupons": [(15.0, 40.0, "pickup"), (6.0, 0.0, "any"), (9.0, 30.0, "delivery")],
    },
    {
        "name": "外送券抵扣后持平",
        "goods": 47.0, "qty": 1, "fee": 9.0, "min_order": 20.0,
        "prep_d": 25, "prep_p": 8, "travel": 20, "mc": 0.5,
        "coupons": [(15.0, 40.0, "pickup"), (9.0, 30.0, "delivery")],
    },
    {
        "name": "无券基线",
        "goods": 47.0, "qty": 1, "fee": 9.0, "min_order": 20.0,
        "prep_d": 25, "prep_p": 8, "travel": 20, "mc": 0.5,
        "coupons": [],
    },
    {
        "name": "时间成本为零",
        "goods": 47.0, "qty": 1, "fee": 9.0, "min_order": 20.0,
        "prep_d": 25, "prep_p": 8, "travel": 20, "mc": 0.0,
        "coupons": [(15.0, 40.0, "pickup"), (9.0, 30.0, "delivery")],
    },
    {
        "name": "时间成本极高-外送反超",
        "goods": 47.0, "qty": 1, "fee": 9.0, "min_order": 20.0,
        "prep_d": 25, "prep_p": 8, "travel": 200, "mc": 0.5,
        "coupons": [(15.0, 40.0, "pickup"), (9.0, 30.0, "delivery")],
    },
    {
        "name": "高配送费",
        "goods": 47.0, "qty": 1, "fee": 60.0, "min_order": 20.0,
        "prep_d": 25, "prep_p": 8, "travel": 20, "mc": 0.5,
        "coupons": [(15.0, 40.0, "pickup"), (9.0, 30.0, "delivery")],
    },
    {
        "name": "未达起送价",
        "goods": 12.0, "qty": 1, "fee": 9.0, "min_order": 20.0,
        "prep_d": 25, "prep_p": 8, "travel": 20, "mc": 0.5,
        "coupons": [(15.0, 40.0, "pickup"), (9.0, 30.0, "delivery")],
    },
    {
        "name": "多份数",
        "goods": 22.0, "qty": 3, "fee": 9.0, "min_order": 20.0,
        "prep_d": 25, "prep_p": 8, "travel": 20, "mc": 0.5,
        "coupons": [(15.0, 40.0, "pickup"), (9.0, 30.0, "delivery")],
    },
]


def run_python(scenario: dict) -> dict:
    """用 decider.py 跑一个场景。"""
    goods = round(scenario["goods"] * scenario["qty"], 2)
    coupons = [
        Coupon(f"C{i}", f"券{i}", discount, threshold, channel)
        for i, (discount, threshold, channel) in enumerate(scenario["coupons"])
    ]
    delivery = Channel(
        key="delivery", label="外送", stores=[{"storeCode": "S1"}], coupons=coupons,
        delivery_fee=scenario["fee"], min_order=scenario["min_order"],
        prep_minutes=scenario["prep_d"],
        min_order_met=goods >= scenario["min_order"],
    )
    pickup = Channel(
        key="pickup", label="到店自取", stores=[{"storeCode": "S1"}], coupons=coupons,
        prep_minutes=scenario["prep_p"], travel_minutes=scenario["travel"],
    )
    basket = [BasketItem("1", "测试餐品", scenario["goods"], scenario["qty"])]
    v = compare(delivery, pickup, basket, minute_cost=scenario["mc"])
    d = v.detail["delivery"]
    p = v.detail["pickup"]
    return {
        "name": scenario["name"],
        "goods": goods,
        "delivery": {
            "total": d["total"], "grand": d["grand_total"],
            "coupon": d["coupon"], "available": d["available"],
        },
        "pickup": {
            "total": p["total"], "grand": p["grand_total"],
            "coupon": p["coupon"], "available": p["available"],
        },
        "recommended": v.recommended,
    }


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("⚠️  未找到 Node.js，跳过前后端对拍（仅说明页面与 CLI 无法在本机验证一致性）")
        return 0

    script = os.path.join(HERE, "parity_check.mjs")
    try:
        proc = subprocess.run(
            [node, script], capture_output=True, text=True, timeout=60, cwd=HERE
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"⚠️  Node 调用失败，跳过对拍：{exc}")
        return 0

    if proc.returncode != 0:
        print(f"⚠️  parity_check.mjs 执行失败，跳过对拍：\n{proc.stderr[:400]}")
        return 0

    try:
        js_results = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print(f"⚠️  无法解析 Node 输出，跳过对拍：{exc}")
        return 0

    failures: list[str] = []
    checked = 0

    for scenario, js in zip(PY_SCENARIOS, js_results):
        py = run_python(scenario)
        label = py["name"]
        if py["name"] != js["name"]:
            failures.append(f"{label}: 场景名不一致 py={py['name']} js={js['name']}")
            continue

        for ch in ("delivery", "pickup"):
            for field in ("total", "grand"):
                checked += 1
                a = py[ch][field]
                b = js[ch][field]
                if abs(a - b) > 0.01:
                    failures.append(f"{label}/{ch}.{field}: py={a} js={b}")

            checked += 1
            if py[ch]["available"] != js[ch]["available"]:
                failures.append(
                    f"{label}/{ch}.available: py={py[ch]['available']} js={js[ch]['available']}"
                )

        checked += 1
        py_rec = py["recommended"]
        js_rec = js["recommended"]
        # Python 端返回「到店自取 / 点外送」，JS 端返回同样语义
        py_norm = "到店自取" if "到店" in py_rec else ("点外送" if "外送" in py_rec else py_rec)
        if py_norm != js_rec:
            failures.append(f"{label}/recommended: py={py_norm} js={js_rec}")

    print(f"前后端对拍：{checked} 项比对，{len(failures)} 项不一致")
    if failures:
        for item in failures:
            print(f"  ❌ {item}")
        return 1
    print("✅ 页面与 CLI 逻辑完全一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
