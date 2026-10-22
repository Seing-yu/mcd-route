#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门渠道官 · MCP 连通性自检。

证明「数据链路是真的」——评审可以自己跑一遍确认，不依赖开发者的口头保证。

    export MCD_MCP_TOKEN=你的token
    python mcp_probe.py
    python mcp_probe.py --call query-nearby-stores --args '{"address":"北京市朝阳区"}'

依次验证：
    1. TCP/HTTP 层：能不能连上 mcp.mcd.cn
    2. 协议层：initialize 握手能否协商出协议版本
    3. 工具层：tools/list 能拿到多少个 Tool
    4. 业务层：试调用一个只读 Tool（默认 now-time-info）
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_client import McpClient, McpError  # noqa: E402

# 本项目真正会用到的 Tool，逐一验证是否在线
REQUIRED_TOOLS = [
    "now-time-info",
    "query-nearby-stores",
    "delivery-query-stores",
    "delivery-query-addresses",
    "query-meals",
    "query-meal-detail",
    "query-store-coupons",
    "query-my-coupons",
    "available-coupons",
    "calculate-price",
    "create-order",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP 连通性自检")
    parser.add_argument("--call", help="额外试调用的 Tool 名")
    parser.add_argument("--args", default="{}", help="试调用参数（JSON）")
    args = parser.parse_args()

    token = os.environ.get("MCD_MCP_TOKEN", "")
    if not token:
        print(
            "❌ 缺少环境变量 MCD_MCP_TOKEN。\n"
            "   申请地址：https://open.mcd.cn/mcp （手机号登录 → 控制台 → 激活）\n"
            "   Windows：set MCD_MCP_TOKEN=你的token",
            file=sys.stderr,
        )
        return 2

    client = McpClient(token=token)
    report: dict = {"ok": False}

    print("1️⃣  协议层：initialize 握手…")
    try:
        client.initialize()
    except McpError as exc:
        print(f"    ❌ {exc}", file=sys.stderr)
        return 1
    print(f"    ✅ 协议版本 {client.protocol_version}")
    print(f"    ✅ 服务器 {client.server_info}")
    report["protocolVersion"] = client.protocol_version
    report["serverInfo"] = client.server_info

    print("2️⃣  工具层：tools/list…")
    try:
        tools = client.list_tools()
    except McpError as exc:
        print(f"    ❌ {exc}", file=sys.stderr)
        return 1
    names = {t.get("name") for t in tools}
    print(f"    ✅ 服务器共提供 {len(tools)} 个 Tool")

    missing = [t for t in REQUIRED_TOOLS if t not in names]
    if missing:
        print(f"    ⚠️  本项目依赖的 Tool 缺失：{', '.join(missing)}")
    else:
        print(f"    ✅ 本项目依赖的 {len(REQUIRED_TOOLS)} 个 Tool 全部在线")
    report["toolCount"] = len(tools)
    report["missingTools"] = missing

    print("3️⃣  业务层：试调用 now-time-info…")
    try:
        text = client.call("now-time-info")
        print(f"    ✅ 返回：{text[:160]}")
        report["sampleCall"] = "ok"
    except McpError as exc:
        print(f"    ❌ {exc}", file=sys.stderr)
        report["sampleCall"] = f"failed: {exc}"
        return 1

    if args.call:
        print(f"4️⃣  业务层：试调用 {args.call}…")
        try:
            arguments = json.loads(args.args)
        except json.JSONDecodeError as exc:
            print(f"    ❌ --args 不是合法 JSON：{exc}", file=sys.stderr)
            return 2
        try:
            text = client.call(args.call, arguments)
            print(f"    ✅ 返回：{text[:400]}")
        except McpError as exc:
            print(f"    ❌ {exc}", file=sys.stderr)
            return 1

    report["ok"] = True
    print(f"\n🎉 全部通过：MCP 链路真实可用。")
    print(f"   本次会话实际发起 {client.call_count} 次调用"
          f"（单会话上限 {client.max_calls}，官方限流 600 次/分钟）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
