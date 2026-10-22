#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦当劳中国 MCP Server 最小客户端（纯 Python 标准库，零第三方依赖）。

为什么不用 `pip install mcp`
----------------------------
1. 参赛作品强调「零依赖、clone 下来就能跑」，不装包才做得到；
2. MCP 的 Streamable HTTP 传输层本质就是「POST 一个 JSON-RPC 请求，
   然后解析 JSON 或 SSE 响应」，标准库已经完全够用；
3. 少一个安装环节，别人评审时少一道坎。

只实现本项目真正用到的三个方法：
    initialize  ->  握手，协商协议版本，拿 Mcp-Session-Id
    tools/list  ->  列出服务器提供的全部 Tool
    tools/call  ->  调用具体 Tool

用法
----
    export MCD_MCP_TOKEN=你的token        # Windows: set MCD_MCP_TOKEN=你的token
    python mcp_client.py --list-tools
    python mcp_client.py --call now-time-info
    python mcp_client.py --call query-nearby-stores --args '{"address":"北京市朝阳区"}'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

DEFAULT_URL = "https://mcp.mcd.cn"
# 按新到旧排列：服务器会挑一个它支持的版本回给我们，以它返回的为准
PROTOCOL_CANDIDATES = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

CLIENT_INFO = {"name": "mcd-route", "version": "1.0.0"}

# ---------------------------------------------------------------- 合规约束
#
# 《麦当劳 MCP 服务规则》第六条禁止行为第 2 项明确禁止
# 「利用脚本、爬虫或任何自动化工具调用本服务」；
# 第三条第 2 项要求「仅面向个人正常使用场景，不支持任何形式的批量、高频或自动化调用」。
#
# 本项目的立场：MCP 调用是**人在对话中发起、Agent 按需少量取数**的交互式调用，
# 不是无人值守的批量爬取。为让这一立场可被验证而非口头承诺，代码层面强制：
#   1. 限速：两次调用之间至少间隔 MIN_INTERVAL_SECONDS；
#   2. 配额：单次会话的调用总数不超过 MAX_CALLS_PER_SESSION；
#   3. 拒绝批量：不提供循环批量取数的接口，只支持按名单逐个调用且受上述配额约束。
#
# 详见 README「合规说明」与 MCP_INTEGRATION.md「使用规范与禁止行为」。

MIN_INTERVAL_SECONDS = 0.35   # 两次调用最小间隔
MAX_CALLS_PER_SESSION = 120   # 单次会话调用总数上限（远低于 600/分钟 的官方限流）


class McpError(RuntimeError):
    """MCP 调用过程中的可预期错误。"""


class ComplianceError(RuntimeError):
    """触犯《麦当劳 MCP 服务规则》的调用方式时抛出。"""


class RateLimiter:
    """最小间隔限速器，保证调用是交互式节奏而非高频压测。"""

    def __init__(self, min_interval: float = MIN_INTERVAL_SECONDS) -> None:
        self.min_interval = min_interval
        self._last = 0.0
        self._count = 0
        self._lock = threading.Lock()

    def tick(self) -> int:
        """计一次调用并返回累计次数，随后执行限速等待。"""
        with self._lock:
            self._count += 1
            count = self._count
            now = time.monotonic()
            gap = now - self._last
            if gap < self.min_interval:
                time.sleep(self.min_interval - gap)
            self._last = time.monotonic()
        return count

    @property
    def count(self) -> int:
        """已计数的调用次数。"""
        return self._count


class McpClient:
    """麦当劳中国 MCP Server 的最小可用客户端。"""

    def __init__(
        self,
        token: str | None = None,
        url: str | None = None,
        timeout: int = 30,
        max_retries: int = 3,
        max_calls: int = MAX_CALLS_PER_SESSION,
    ) -> None:
        self.token = token or os.environ.get("MCD_MCP_TOKEN", "")
        self.url = url or os.environ.get("MCD_MCP_URL", DEFAULT_URL)
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_calls = max_calls
        self._init_result: dict | None = None
        self._limiter = RateLimiter()
        self.session_id: str | None = None
        self.protocol_version: str | None = None
        self.server_info: dict = {}

    # ------------------------------------------------------------------ 配额

    def _account_call(self) -> None:
        """计入一次调用并强制限速。超过配额直接拒绝，不静默截断。"""
        count = self._limiter.tick()
        if count > self.max_calls:
            raise ComplianceError(
                f"单次会话调用次数已达上限 {self.max_calls}。"
                "《麦当劳 MCP 服务规则》不支持批量/自动化调用，"
                "请拆分为多次人工发起的查询。"
            )

    @property
    def call_count(self) -> int:
        """本会话已发起的调用次数。"""
        return self._limiter.count

    # ------------------------------------------------------------------ 底层

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            # Streamable HTTP 规范要求客户端同时接受两种响应类型
            "Accept": "application/json, text/event-stream",
            "User-Agent": "mcd-route/1.0 (WorkBuddy Skill)",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        return headers

    def _post(self, payload: dict) -> dict | None:
        """发一个 JSON-RPC 请求，返回解析后的 result（通知类返回 None）。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=body, headers=self._headers(), method="POST"
        )

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                # 每次真实发请求前都要过配额与限速，重试同样计数
                self._account_call()
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    # 会话 ID 只在 initialize 的响应头里出现，之后要带上
                    sid = resp.headers.get("Mcp-Session-Id")
                    if sid:
                        self.session_id = sid
                    ctype = resp.headers.get("Content-Type", "")
                    raw = resp.read().decode("utf-8", errors="replace")
                return self._parse(raw, ctype)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                if exc.code == 401:
                    raise McpError(
                        "401 未授权：MCP Token 无效、已过期或未提供。"
                        "请到 https://open.mcd.cn/mcp 重新申请并检查配置。"
                    ) from exc
                if exc.code == 429:
                    # 官方限流：每分钟 600 次。退避后重试
                    wait = 3 * attempt
                    print(f"[warn] 触发限流(429)，{wait}s 后重试", file=sys.stderr)
                    time.sleep(wait)
                    last_error = exc
                    continue
                raise McpError(f"HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                last_error = exc
                time.sleep(2 * attempt)
            except TimeoutError as exc:
                last_error = exc
                time.sleep(2 * attempt)
        raise McpError(f"请求失败（重试 {self.max_retries} 次）：{last_error}")

    @staticmethod
    def _parse(raw: str, content_type: str) -> dict | None:
        """把 JSON 或 SSE 响应统一解析成 JSON-RPC 响应对象。"""
        raw = raw.strip()
        if not raw:
            return None

        if "text/event-stream" in content_type or raw.startswith("event:"):
            # SSE：一行行取 data: 后面的 JSON
            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload and payload != "[DONE]":
                        try:
                            return json.loads(payload)
                        except json.JSONDecodeError:
                            continue
            return None

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise McpError(f"响应不是合法 JSON：{raw[:200]}") from exc

    @staticmethod
    def _unwrap(response: dict | None) -> dict | None:
        """剥掉 JSON-RPC 外壳，错误则抛 McpError。"""
        if response is None:
            return None
        if "error" in response:
            err = response["error"]
            code = err.get("code", "?")
            msg = err.get("message", "")
            raise McpError(f"MCP 返回错误 [{code}]：{msg}")
        return response.get("result")

    # ------------------------------------------------------------------ 协议

    def initialize(self) -> dict:
        """握手。必须在任何 tools/call 之前完成。

        幂等：已握手过就直接返回缓存结果，不重复发请求。
        （否则每次 tools/call 都会多出 2 次握手请求。）
        """
        if self._init_result is not None:
            return self._init_result
        for version in PROTOCOL_CANDIDATES:
            result = self._unwrap(
                self._post(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": version,
                            "capabilities": {},
                            "clientInfo": CLIENT_INFO,
                        },
                    }
                )
            )
            if result is None:
                continue
            # 以服务器选定的版本为准，后续请求带上它
            self.protocol_version = result.get("protocolVersion", version)
            self.server_info = result.get("serverInfo", {}) or {}
            self._post(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }
            )
            self._init_result = result
            return result
        raise McpError("initialize 失败：服务器不接受任何候选协议版本")

    def list_tools(self) -> list[dict]:
        """列出服务器提供的全部 Tool（含入参 schema）。"""
        self.initialize()
        result = self._unwrap(self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}))
        return (result or {}).get("tools", [])

    def call(self, tool_name: str, arguments: dict | None = None) -> str:
        """调用一个 Tool，返回其 text 内容（多段则用换行拼接）。"""
        self.initialize()
        result = self._unwrap(
            self._post(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments or {}},
                }
            )
        )
        return self._flatten(result)

    @staticmethod
    def _flatten(result: dict | None) -> str:
        """把 tools/call 的返回压成纯文本。"""
        if not result:
            return ""
        if result.get("isError"):
            raise McpError(f"Tool 执行失败：{result.get('content')}")
        chunks: list[str] = []
        for item in result.get("content", []) or []:
            if item.get("type") == "text":
                chunks.append(item.get("text", ""))
        text = "\n".join(c for c in chunks if c).strip()
        # 有些 Tool 直接返回结构化对象
        if not text and result.get("structuredContent"):
            text = json.dumps(result["structuredContent"], ensure_ascii=False, indent=2)
        return text

    def call_json(self, tool_name: str, arguments: dict | None = None) -> dict | list:
        """调用 Tool 并把返回文本当 JSON 解析（解析失败则包一层）。"""
        text = self.call(tool_name, arguments)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"_raw": text}


# --------------------------------------------------------------------- CLI

def main() -> int:
    parser = argparse.ArgumentParser(description="麦当劳 MCP 最小客户端")
    parser.add_argument("--list-tools", action="store_true", help="列出全部 Tool")
    parser.add_argument("--call", metavar="TOOL", help="调用指定 Tool")
    parser.add_argument("--args", default="{}", help="Tool 参数（JSON 字符串）")
    parser.add_argument("--url", default=DEFAULT_URL, help="MCP 接入地址")
    parser.add_argument("--probe", action="store_true", help="只做连通性自检")
    args = parser.parse_args()

    token = os.environ.get("MCD_MCP_TOKEN", "")
    if not token:
        print(
            "缺少 MCP Token。请先到 https://open.mcd.cn/mcp 用手机号登录申请，\n"
            "然后设置环境变量 MCD_MCP_TOKEN。",
            file=sys.stderr,
        )
        return 2

    try:
        client = McpClient(token=token, url=args.url)
        if args.probe:
            info = client.initialize()
            print("✅ 握手成功")
            print(f"   协议版本 : {client.protocol_version}")
            print(f"   服务器   : {client.server_info}")
            tools = client.list_tools()
            print(f"   Tool 数量: {len(tools)}")
            return 0
        if args.list_tools:
            for tool in client.list_tools():
                print(f"- {tool.get('name')}: {tool.get('description', '')[:70]}")
            return 0
        if args.call:
            try:
                arguments = json.loads(args.args)
            except json.JSONDecodeError as exc:
                print(f"--args 不是合法 JSON：{exc}", file=sys.stderr)
                return 2
            print(client.call(args.call, arguments))
            return 0
    except McpError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
