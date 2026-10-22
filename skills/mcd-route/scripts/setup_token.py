#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门渠道官 · 凭据配置助手。

【为什么有这个脚本】
MCP Token 等同于你的麦当劳会员账号操作权限。它不应该：
  · 出现在与 AI 的对话里（对话会经过第三方模型服务商处理）
  · 出现在任何 git 仓库里（哪怕是 .gitignore 也不够保险）
  · 出现在截图、录屏、日志里

本脚本让你在**本地终端**里输入 Token，直接写入凭据文件，
全程不经过对话、不经过剪贴板以外的任何中间环节。

用法（推荐，交互式输入，Token 不回显、不进 shell 历史）：

    python setup_token.py

或从文件读取（如果你已经有保存的 token 文件）：

    python setup_token.py --from-file /path/to/token.txt

写入位置：~/.workbuddy/.mcd_token（用户主目录，不在任何仓库内）
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".workbuddy", ".mcd_token")


def write_token(token: str) -> str:
    """把 token 写入凭据文件，权限设为仅当前用户可读写。"""
    token = token.strip()
    if not token:
        raise ValueError("Token 为空，未写入")

    directory = os.path.dirname(TOKEN_FILE)
    os.makedirs(directory, exist_ok=True)

    with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
        fh.write(token)
    try:
        # POSIX 下限制为 600；Windows 上 os.chmod 语义有限，尽力而为
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    return TOKEN_FILE


def main() -> int:
    parser = argparse.ArgumentParser(description="配置麦当劳 MCP Token 到本地凭据文件")
    parser.add_argument("--from-file", help="从指定文件读取 Token（不会打印内容）")
    args = parser.parse_args()

    print("麦当劳 MCP Token 配置")
    print("-" * 52)
    print("Token 申请地址：https://open.mcd.cn/mcp")
    print("  手机号登录 → 右上角「控制台」→「激活」→ 复制 Token")
    print()

    if args.from_file:
        try:
            with open(args.from_file, encoding="utf-8") as fh:
                token = fh.read().strip()
        except OSError as exc:
            print(f"❌ 读取失败：{exc}", file=sys.stderr)
            return 1
        source = f"文件 {args.from_file}"
    else:
        print("请粘贴你的 Token（输入不回显，属正常现象）：")
        try:
            token = getpass.getpass("Token: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。", file=sys.stderr)
            return 1
        source = "交互输入"

    if not token:
        print("❌ 未获取到 Token，未做任何修改。", file=sys.stderr)
        return 1

    try:
        path = write_token(token)
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"❌ 写入失败：{exc}", file=sys.stderr)
        return 1

    print()
    print(f"✅ 已写入（来源：{source}）")
    print(f"   路径：{path}")
    print(f"   长度：{len(token)} 字符")
    print()
    print("接下来运行连通性自检：")
    print("   python mcp_probe.py")
    print()
    print("提示：这个文件在你的用户主目录下，不在任何 git 仓库内。")
    print("     如需撤销，删除该文件即可（并去 open.mcd.cn 重新申请 Token）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
