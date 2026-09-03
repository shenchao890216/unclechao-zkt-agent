"""inbox.py —— zkt inbox:待审卡片流。签字前的最后一站。"""

from __future__ import annotations

import sys

from card import load_all


def cmd_inbox(argv: list[str]) -> int:
    """zkt inbox [--all] —— 列出待审卡;--all 逐张过目,当场 promote/跳过。"""
    drafts = [
        c for c in load_all()
        if c.path is not None and c.path.parent.name == "inbox"
    ]
    if not drafts:
        print("inbox 是空的,没有待审卡片。")
        return 0

    review = "--all" in argv
    print(f"待审卡片 {len(drafts)} 张(草稿区)")
    print("-" * 60)

    if not review:
        # 只列清单:状态行 + 标题 + 警告
        for i, c in enumerate(drafts, 1):
            tag = "[auto] " if c.auto else ""
            warns = c.warnings()
            print(f"{i:3}. {tag}{c.title}")
            print(f"      {c.id} · {len(c.body)} 字")
            for w in warns:
                print(f"      ⚠ {w}")
        print()
        print("逐张过目: zkt inbox --all")
        return 0

    # 交互审核:逐张显示全文,y=转正 n=跳过 q=退出
    import cli  # 延迟导入避免环
    reviewed = promoted = skipped = 0
    for c in drafts:
        reviewed += 1
        print(f"\n[{reviewed}/{len(drafts)}]")
        print(f"标题: {c.title}")
        print(f"id:   {c.id} · {'auto' if c.auto else '人写'} · {len(c.body)} 字")
        for w in c.warnings():
            print(f"⚠ {w}")
        print("-" * 60)
        print(c.body)
        print("-" * 60)
        while True:
            answer = input("转正? [y=转正 n=跳过 q=退出] ").strip().lower()
            if answer in ("y", "n", "q"):
                break
            print("请输入 y / n / q")
        if answer == "q":
            print("已退出审核。")
            break
        if answer == "y":
            code = cli.cmd_promote([c.id])
            promoted += 1 if code == 0 else 0
        else:
            skipped += 1

    print()
    print(f"本轮过目 {reviewed} 张:转正 {promoted},跳过 {skipped}。")
    return 0
