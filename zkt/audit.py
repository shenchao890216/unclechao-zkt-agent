"""audit.py —— 审计日志:每次 agent 工具调用落一行 JSONL。

铁律:
- append-only:只追加,永不改写历史。想知道发生了什么,看日志。
- 记录在写入之前:操作哪怕一半崩了,日志里也有它的痕迹。
"""

from __future__ import annotations

import datetime
import json

from card import zk_home


def log_path():
    return zk_home() / "audit.jsonl"


def log_action(
    actor: str,          # "model" | "human"
    action: str,         # "create_card" | "link_cards" | "search_cards" | "promote" | ...
    detail: dict,        # 动作参数与结果
) -> None:
    """追加一行审计记录。目录不存在则建。"""
    entry = {
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "actor": actor,
        "action": action,
        **detail,
    }
    log_path().parent.mkdir(parents=True, exist_ok=True)
    with log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_log() -> list[dict]:
    """读全量日志,供审计命令展示。"""
    if not log_path().exists():
        return []
    entries = []
    for line in log_path().read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries
