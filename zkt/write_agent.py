"""write_agent.py —— M4 写作回路:两个岗位,两种工具腰带。

outline 岗:卡片簇 → 文章大纲。工具只有 submit_outline(交活)。
write 岗:大纲 + 卡片全文 → 文章草稿。工具只有 submit_draft(交活)。

设计纪律:
- 写作 agent 不碰卡片盒:没有 create/link 权限。岗位不同,腰带不同。
- 装配纪律写进工具层:大纲每节必须挂卡片,挂不出卡的小节不许存在。
- 产物落 drafts/ 目录,不进卡片盒。文章不是卡片。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from agent import run_agent
from card import drafts_dir, load_all
from cluster import find_clusters, describe_cluster

DRAFTS_DIR = drafts_dir()


# ---------------------------------------------------------------------------
# 岗位一:outline —— 簇 → 大纲
# ---------------------------------------------------------------------------

OUTLINE_PROMPT = """你是一个写作大纲师。你的原料是用户提供的卡片簇(每张卡片是一个原子观点,链接说明观点之间的关系)。

你的任务:为这簇卡片设计一篇文章的大纲。

大纲纪律:
- 每一节的核心必须是某张卡片(或几张)承载的观点——大纲是装配图,不是创作。
- 每一节必须挂至少一张卡片 id。挂不出卡片的节,说明它是你想写但没有素材的,删掉。
- 节的顺序要讲清因果链:先让读者建立概念基础,再给应用与对照。
- 标题里给文章一个统一的论点,不是话题词。

工具:submit_outline 提交大纲。sections 里每节有 title、cards(卡片 id 列表)、angle(这一节讲什么、怎么和上下节衔接,一两句)。
"""


def run_submit_outline(title: str, thesis: str, sections: list) -> str:
    """执行 submit_outline:装配纪律校验后落盘。"""
    errors = []
    all_ids = {c.id for c in load_all()}
    for i, section in enumerate(sections):
        if not section.get("cards"):
            errors.append(f"第 {i+1} 节「{section.get('title', '?')}」没挂任何卡片——挂不出卡片的节不许存在")
        for card_id in section.get("cards", []):
            if card_id not in all_ids:
                errors.append(f"第 {i+1} 节挂了不存在的卡片: {card_id}")
    if not sections:
        errors.append("大纲没有任何节")
    if errors:
        return json.dumps({"ok": False, "errors": errors}, ensure_ascii=False)

    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    outline = {
        "title": title,
        "thesis": thesis,
        "sections": sections,
        "cluster_ids": sorted(all_ids),  # 备忘:交稿时验证用
    }
    path = DRAFTS_DIR / "outline.json"
    path.write_text(
        json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return json.dumps(
        {"ok": True, "saved": str(path), "sections": len(sections)},
        ensure_ascii=False,
    )


OUTLINE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "submit_outline",
            "description": "提交文章大纲。每节必须挂至少一张真实存在的卡片 id。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "文章标题"},
                    "thesis": {"type": "string", "description": "全文论点,一句话"},
                    "sections": {
                        "type": "array",
                        "description": "大纲各节,按行文顺序",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "cards": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "这一节装配的卡片 id 列表",
                                },
                                "angle": {
                                    "type": "string",
                                    "description": "这一节讲什么、怎么衔接上下节",
                                },
                            },
                            "required": ["title", "cards", "angle"],
                        },
                    },
                },
                "required": ["title", "thesis", "sections"],
            },
        },
    }
]


def outline_tool_runner(name: str, arguments: dict) -> str:
    if name == "submit_outline":
        return run_submit_outline(**arguments)
    raise ValueError(f"outline 岗未注册的工具: {name}")


def cmd_outline(argv: list[str]) -> int:
    """zkt outline —— 找最大的簇,让 outline 岗出大纲,人审后可手改。"""
    if "--view" in argv:
        from outline_view import cmd_outline_view
        return cmd_outline_view()
    clusters = find_clusters()
    if not clusters:
        print("没有够格的簇(至少 3 张卡互链)。先养盒。")
        return 1
    cluster = clusters[0]
    print("用最大的簇开写作:")
    print(describe_cluster(cluster))
    print()

    cards_text = "\n\n".join(
        f"[卡片 {c.id}]\n标题: {c.title}\n正文: {c.body}\n链接: "
        + "; ".join(f"→{l.to}({l.why[:40]}…)" for l in c.links)
        for c in cluster
    )
    user_input = f"卡片簇原料:\n\n{cards_text}"

    answer = run_agent(
        user_input,
        system_prompt=OUTLINE_PROMPT,
        tools=OUTLINE_TOOLS,
        tool_runner=outline_tool_runner,
    )
    print()
    print(answer)
    print()
    print("大纲已落 drafts/outline.json,人工审阅/手改后再 zkt write。")
    return 0


# ---------------------------------------------------------------------------
# 岗位二:write —— 大纲 + 卡片全文 → 草稿
# ---------------------------------------------------------------------------

WRITE_PROMPT = """你是一个装配写手。你的原料是:一份人审过的大纲(JSON)+ 每一节挂的卡片全文。

你的任务:按大纲逐节把文章写出来。

装配纪律:
- 文章观点必须来自卡片。卡片没说的事实不许编;需要过渡和衔接时,用你自己的话搭桥,但桥不承载新事实。
- 卡片的观点用自己的话重述,融入行文,不要整段照抄卡片,也不要在正文里出现卡片 id。
- 每节写完检查:这节的核心论点能不能追溯到卡片?追溯不到的句子,要么删,要么改写成纯过渡。
- 文体:技术博客,平实直接,不堆砌形容词。

工具:submit_draft 提交全文草稿。
"""


def run_submit_draft(content: str) -> str:
    """执行 submit_draft:校验非空后落盘。"""
    if not content or len(content.strip()) < 200:
        return json.dumps(
            {"ok": False, "errors": ["草稿太短(<200 字),不像一篇装配出来的文章"]},
            ensure_ascii=False,
        )
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    outline = json.loads((DRAFTS_DIR / "outline.json").read_text(encoding="utf-8"))
    path = DRAFTS_DIR / f"{outline['title']}.md"
    path.write_text(content, encoding="utf-8")
    return json.dumps({"ok": True, "saved": str(path)}, ensure_ascii=False)


WRITE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "submit_draft",
            "description": "提交文章全文草稿(markdown)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "文章全文,markdown 格式",
                    },
                },
                "required": ["content"],
            },
        },
    }
]


def write_tool_runner(name: str, arguments: dict) -> str:
    if name == "submit_draft":
        return run_submit_draft(**arguments)
    raise ValueError(f"write 岗未注册的工具: {name}")


def list_drafts() -> list[Path]:
    """drafts/ 下所有 markdown 草稿,新的在前。"""
    return sorted(DRAFTS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


def open_file(path: Path, app: str | None = None) -> None:
    cmd = ["open"]
    if app:
        cmd += ["-a", app]
    cmd.append(str(path))
    subprocess.run(cmd, check=False)


def cmd_write(argv: list[str]) -> int:
    """zkt write —— 按人审过的大纲装配全文。"""
    outline_path = DRAFTS_DIR / "outline.json"
    if not outline_path.exists():
        print("没有大纲。先 zkt outline。")
        return 1
    outline = json.loads(outline_path.read_text(encoding="utf-8"))

    by_id = {c.id: c for c in load_all()}
    sections_text = []
    for i, sec in enumerate(outline["sections"], 1):
        cards_md = "\n\n".join(
            f"[卡片 {cid}]\n{by_id[cid].title}\n\n{by_id[cid].body}"
            for cid in sec["cards"]
            if cid in by_id
        )
        sections_text.append(
            f"## 第 {i} 节: {sec['title']}\n角度: {sec['angle']}\n素材:\n{cards_md}"
        )

    user_input = (
        f"文章标题: {outline['title']}\n全文论点: {outline['thesis']}\n\n"
        + "\n\n".join(sections_text)
    )

    started = time.time()
    answer = run_agent(
        user_input,
        system_prompt=WRITE_PROMPT,
        tools=WRITE_TOOLS,
        tool_runner=write_tool_runner,
    )
    print()
    print(answer)
    print()
    fresh = [p for p in list_drafts() if p.stat().st_mtime > started]
    if fresh:
        print(f"草稿已落: {fresh[0]}")
        open_file(fresh[0], app=os.environ.get("ZKT_APP"))
        print("(已在默认编辑器中打开,人工修改后即成稿。)")
    else:
        print("本次没有新草稿落盘。")
    return 0
