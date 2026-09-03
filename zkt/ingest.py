"""ingest.py —— CLI 的 ingest 子命令:URL 或纯文本 → agent 消化 → 卡片草稿。"""
from __future__ import annotations

import fetch
from agent import run_agent


def cmd_ingest(argv: list[str]) -> int:
    if not argv:
        print("用法: zkt ingest <url 或 一段话>")
        return 1
    source = argv[0]

    if source.startswith("http://") or source.startswith("https://"):
        print(f"抓取中: {source}")
        try:
            text = fetch.fetch_url(source)
        except Exception as e:
            print(f"抓取失败: {e}")
            return 1
        print(f"抓到 {len(text)} 字,交给 agent 消化")
        user_input = f"请消化这篇文章,来源 URL: {source}\n\n{text}"
    else:
        user_input = " ".join(argv)

    answer = run_agent(user_input)
    print()
    print("== 最终回答 ==")
    print(answer)
    return 0
