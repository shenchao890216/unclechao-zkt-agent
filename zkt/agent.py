"""agent.py —— agent 循环:M1 的灵魂文件。

结构:
    系统提示词(岗位说明书)
      ↓
    ┌─→ 调模型 ──→ 模型要工具? ─是→ 执行工具 ─┐
    │                ↓否                       │
    │              结束,返回最终回答            │
    └──────────── 工具结果喂回模型 ←────────────┘

模型的全部权力 = 在注册的工具清单里挑一个名字。
执行永远发生在这里的 Python 代码里。
"""

from __future__ import annotations

import json
import os
import threading

from dotenv import load_dotenv
from openai import OpenAI

from card import Card, all_ids, load_all, search_cards, inbox_dir
from audit import log_action

load_dotenv()  # 从 .env 读 DEEPSEEK_API_KEY

# ---------------------------------------------------------------------------
# provider 配置:默认 DeepSeek,换 OpenAI 兼容服务商只需设环境变量
#   ZKT_BASE_URL / ZKT_API_KEY / ZKT_MODEL(密钥名跟随服务商,如 ANTHROPIC 兼容网关)
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("ZKT_BASE_URL", "https://api.deepseek.com")
API_KEY = os.environ.get("ZKT_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
MODEL = os.environ.get("ZKT_MODEL", "deepseek-chat")


def make_client() -> OpenAI:
    return OpenAI(api_key=API_KEY, base_url=BASE_URL)


class AgentInterrupted(Exception):
    """用户按了打断(如 Ctrl+C),agent 应立即停止本轮。"""


INTERRUPT = threading.Event()  # 置位后,循环与流式读块处尽快抛 AgentInterrupted

# 签字钩子:由 REPL 注入。agent 只能提议,执行前必须经这个钩子得到人的 y。
# 非交互环境(ingest、write_agent)没有钩子,签字类工具自动拒绝。
CONFIRM_HOOK = None


# ---------------------------------------------------------------------------
# 系统提示词:模型的岗位说明书(宪法在 card.py,这里只写工作手册)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一个卢曼卡片盒(Zettelkasten)助手。

你的任务:把用户给你的内容消化成原子卡片草稿,存进卡片盒的草稿区(inbox)。

写卡纪律:
- 一张卡片只装一个观点。如果内容里有多个观点,拆成多张卡。
- 用自己的话写,不要抄原文。每张卡的正文回答:这个观点是什么、为什么值得记。
- 卡片标题是观点的陈述句,不是话题词(写"链接需要理由才能成立",不写"链接")。
- 写完卡就停,把卡片列表报告给用户。转正(promote)由人决定,不归你管。

链接纪律:
- 每存一张新卡,主动用 search_cards 在盒里找相关旧卡。
- 链接必须有理由:两条卡片在观点层面如何相关,一句话说清。
- 关系不成立的宁可不链。10 张孤卡好过 1 条牵强的链接。
- 链接方向:新卡链向旧卡(新卡说"我和谁相关"),不要反过来。

工具使用:
- create_card: 存一张卡片草稿。title 和 body 必填。每张卡写完立即保存。
- search_cards: 按关键词搜盒中已有卡片(标题+正文)。先用它了解盒里有什么。
- link_cards: 给卡片加一条链接。from_card 和 to_card 都是卡片 id,why 必填。
- list_inbox: 列出待审草稿清单。用户问"待审的卡/草稿"时用它。
- read_card: 读单卡全文。要先看卡片内容或回答关于某张卡的问题时用它。
- update_card: 改 inbox 草稿正文。用户说"改一下那张卡"时用它。已转正的卡不可改。
- list_clusters: 列出成熟卡片簇。用户问"哪块熟了/能写什么文章"时用它。

权限边界:转正(promote)和删除(delete)的签字权在人手里。你只能通过 propose_promote /
propose_delete 提议,由用户按 y 确认后才执行。
"不要反复请求"指同一轮对话里别刷屏追问。用户新开一轮明确要求(如"转正"、"批准"、"删掉"),
就应该立即发起提议弹窗——每次明确指令都是新的授权,过去的拒绝不影响现在。

表达纪律:回答永远用自然语言。工具返回的是 JSON 数据,是你看到的原料,不是给你转述的;
把其中的信息组织成人话再说出来,原样贴 JSON 是失败的回答。
"""


# ---------------------------------------------------------------------------
# 工具层:模型能用的"手脚"。执行在这里,不在模型那边。
# ---------------------------------------------------------------------------

def run_create_card(title: str, body: str) -> str:
    """执行 create_card:校验 + 存盘 + 审计。返回给模型看的结果。"""
    card = Card(id=Card.new_id(), title=title, body=body, auto=True)
    errors = card.validate(known_ids=all_ids())
    if errors:
        # 宪法拒收也要留痕——拒收同样是历史的一部分
        log_action("model", "create_card", {
            "title": title, "ok": False, "errors": errors,
        })
        return json.dumps({"ok": False, "errors": errors}, ensure_ascii=False)
    card.save(inbox=True)
    log_action("model", "create_card", {
        "card_id": card.id, "title": title, "ok": True,
    })
    return json.dumps(
        {"ok": True, "id": card.id, "path": str(card.path)},
        ensure_ascii=False,
    )


def run_search_cards(keyword: str) -> str:
    """执行 search_cards:按关键词找卡,返回摘要列表(不给全文,省 token)。"""
    results = search_cards(keyword)
    log_action("model", "search_cards", {"keyword": keyword, "hits": len(results)})
    if not results:
        return json.dumps({"ok": True, "results": [], "note": "没找到相关卡片"}, ensure_ascii=False)
    return json.dumps(
        {
            "ok": True,
            "results": [
                {"id": c.id, "title": c.title, "summary": c.body[:100]}
                for c in results
            ],
        },
        ensure_ascii=False,
    )


def run_link_cards(from_card: str, to_card: str, why: str) -> str:
    """执行 link_cards:给 from_card 加一条指向 to_card 的链接,宪法校验 + 审计。"""
    target_found = None
    for card in load_all():
        if card.id == from_card:
            target_found = card
            break
    if target_found is None:
        log_action("model", "link_cards", {
            "from_card": from_card, "to_card": to_card, "ok": False,
            "errors": [f"卡片 {from_card} 不存在"],
        })
        return json.dumps(
            {"ok": False, "errors": [f"卡片 {from_card} 不存在"]},
            ensure_ascii=False,
        )
    errors = target_found.add_link(to=to_card, why=why)
    log_action("model", "link_cards", {
        "from_card": from_card, "to_card": to_card, "why": why,
        "ok": not errors, "errors": errors,
    })
    if errors:
        return json.dumps({"ok": False, "errors": errors}, ensure_ascii=False)
    return json.dumps(
        {"ok": True, "linked": f"{from_card} -> {to_card}", "why": why},
        ensure_ascii=False,
    )


# 告诉模型的工具清单(OpenAI function calling 格式)
TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "list_inbox",
            "description": "列出卡片盒 inbox 里所有待审草稿(id、标题、正文字数)。不占 token,想看某张详情再 read_card。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_card",
            "description": "读一张卡片的完整内容:标题、正文、已有链接。",
            "parameters": {
                "type": "object",
                "properties": {
                    "card_id": {"type": "string", "description": "卡片 id,如 20260826-a1b2c3"},
                },
                "required": ["card_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_card",
            "description": "修改 inbox 里一张待审草稿的正文(整篇替换)。已转正的正式卡片不可改。用户让改卡时用它。",
            "parameters": {
                "type": "object",
                "properties": {
                    "card_id": {"type": "string", "description": "待审草稿的卡片 id"},
                    "body": {"type": "string", "description": "新的完整正文"},
                },
                "required": ["card_id", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_clusters",
            "description": "找出卡片盒里已成熟的卡片簇(≥3 张互链)。回答'盒里哪块熟了/能写什么'时用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_promote",
            "description": "提议把一张 inbox 草稿转正。执行前会请用户签字(按 y),被拒绝就接受结果。",
            "parameters": {
                "type": "object",
                "properties": {
                    "card_id": {"type": "string", "description": "要转正的卡片 id"},
                    "reason": {"type": "string", "description": "为什么值得转正,一句话"},
                },
                "required": ["card_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_delete",
            "description": "提议删除一张卡片。执行前会请用户签字(按 y),被拒绝就接受结果。删除是永久的,提议前要慎重。",
            "parameters": {
                "type": "object",
                "properties": {
                    "card_id": {"type": "string", "description": "要删除的卡片 id"},
                    "reason": {"type": "string", "description": "为什么要删,一句话"},
                },
                "required": ["card_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_card",
            "description": "存一张卡片草稿到卡片盒 inbox。title 是观点陈述句,body 用自己的话解释这个观点。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "卡片标题:观点的陈述句",
                    },
                    "body": {
                        "type": "string",
                        "description": "卡片正文:这个观点是什么、为什么值得记",
                    },
                },
                "required": ["title", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_cards",
            "description": "按关键词搜索卡片盒中已有的卡片(标题+正文)。存新卡前后都可用它找相关旧卡。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词,中文或英文",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "link_cards",
            "description": "给一张卡片加一条指向另一张卡的链接。链接方向:新卡链向旧卡。why 必填,说清两条卡在观点层面如何相关。",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_card": {
                        "type": "string",
                        "description": "发起链接的卡片 id(通常是新卡)",
                    },
                    "to_card": {
                        "type": "string",
                        "description": "被链接的卡片 id(通常是旧卡)",
                    },
                    "why": {
                        "type": "string",
                        "description": "链接理由:两条卡片在观点层面如何相关,一句话",
                    },
                },
                "required": ["from_card", "to_card", "why"],
            },
        },
    }
]


def run_list_inbox() -> str:
    """执行 list_inbox:待审草稿清单(轻量,不含正文)。"""
    drafts = [c for c in load_all() if c.path and c.path.parent == inbox_dir()]
    log_action("model", "list_inbox", {"count": len(drafts)})
    if not drafts:
        return json.dumps({"ok": True, "cards": [], "note": "inbox 是空的"}, ensure_ascii=False)
    return json.dumps(
        {
            "ok": True,
            "cards": [
                {"id": c.id, "title": c.title, "body_chars": len(c.body)}
                for c in drafts
            ],
        },
        ensure_ascii=False,
    )


def run_read_card(card_id: str) -> str:
    """执行 read_card:单卡全文。"""
    for card in load_all():
        if card.id == card_id:
            log_action("model", "read_card", {"card_id": card_id})
            return json.dumps(
                {
                    "ok": True,
                    "id": card.id,
                    "title": card.title,
                    "body": card.body,
                    "links": [{"to": l.to, "why": l.why} for l in card.links],
                    "location": "inbox" if card.path and card.path.parent == inbox_dir() else "cards",
                },
                ensure_ascii=False,
            )
    log_action("model", "read_card", {"card_id": card_id, "ok": False})
    return json.dumps({"ok": False, "errors": [f"卡片 {card_id} 不存在"]}, ensure_ascii=False)


def run_update_card(card_id: str, body: str) -> str:
    """执行 update_card:改 inbox 草稿正文。正式卡片拒改——那是人的地盘。"""
    for card in load_all():
        if card.id == card_id:
            if card.path is None or card.path.parent != inbox_dir():
                log_action("model", "update_card", {"card_id": card_id, "ok": False,
                                                    "errors": ["已转正的卡片不可由 agent 修改"]})
                return json.dumps(
                    {"ok": False, "errors": ["这张卡已转正,不可修改。转正后的卡片归人管。"]},
                    ensure_ascii=False,
                )
            old_len = len(card.body)
            card.body = body
            card.save()
            log_action("model", "update_card", {"card_id": card_id, "ok": True,
                                                "old_chars": old_len, "new_chars": len(body)})
            return json.dumps({"ok": True, "id": card_id, "new_chars": len(body)}, ensure_ascii=False)
    log_action("model", "update_card", {"card_id": card_id, "ok": False, "errors": ["卡片不存在"]})
    return json.dumps({"ok": False, "errors": [f"卡片 {card_id} 不存在"]}, ensure_ascii=False)


def run_list_clusters() -> str:
    """执行 list_clusters:成熟簇清单。"""
    import cluster

    found = cluster.find_clusters()
    log_action("model", "list_clusters", {"count": len(found)})
    if not found:
        return json.dumps({"ok": True, "clusters": [], "note": "还没有够格的簇(≥3 张互链)"}, ensure_ascii=False)
    return json.dumps(
        {
            "ok": True,
            "clusters": [
                {
                    "size": len(c),
                    "summary": cluster.describe_cluster(c),
                    "cards": [{"id": card.id, "title": card.title} for card in c],
                }
                for c in found
            ],
        },
        ensure_ascii=False,
    )


def run_propose_promote(card_id: str, reason: str) -> str:
    """执行 propose_promote:agent 提议转正,人按 y 才执行。"""
    target = next((c for c in load_all() if c.id == card_id), None)
    if target is None:
        return json.dumps({"ok": False, "errors": [f"卡片 {card_id} 不存在"]}, ensure_ascii=False)
    if target.path is None or target.path.parent != inbox_dir():
        return json.dumps({"ok": False, "errors": ["这张卡已转正,无需再转"]}, ensure_ascii=False)
    if CONFIRM_HOOK is None or not CONFIRM_HOOK("promote", {
        "id": target.id, "title": target.title, "body": target.body, "reason": reason,
    }):
        log_action("human", "propose_promote", {"card_id": card_id, "ok": False, "declined": True})
        return json.dumps(
            {"ok": False, "declined": True, "note": "用户这次没有签字。不要在同一轮里追问;之后用户明确提出时再提议即可。"},
            ensure_ascii=False,
        )
    import cli
    cli.cmd_promote([card_id])  # 打印 + 审计(actor=human,签字权在人)
    return json.dumps({"ok": True, "promoted": card_id, "note": "用户已签字转正"}, ensure_ascii=False)


def run_propose_delete(card_id: str, reason: str) -> str:
    """执行 propose_delete:agent 提议删除,人按 y 才执行。"""
    target = next((c for c in load_all() if c.id == card_id), None)
    if target is None:
        return json.dumps({"ok": False, "errors": [f"卡片 {card_id} 不存在"]}, ensure_ascii=False)
    backlinks = [
        c.id for c in load_all() for l in c.links if l.to == card_id and c.id != card_id
    ]
    if CONFIRM_HOOK is None or not CONFIRM_HOOK("delete", {
        "id": target.id, "title": target.title, "reason": reason,
        "backlinks": backlinks,
    }):
        log_action("human", "propose_delete", {"card_id": card_id, "ok": False, "declined": True})
        return json.dumps(
            {"ok": False, "declined": True, "note": "用户这次没有签字。不要在同一轮里追问;之后用户明确提出时再提议即可。"},
            ensure_ascii=False,
        )
    import cli
    cli.cmd_delete([card_id, "--confirm"])  # 打印 + 审计(actor=human)
    return json.dumps({"ok": True, "deleted": card_id, "note": "用户已签字删除"}, ensure_ascii=False)


def run_tool(name: str, arguments: dict) -> str:
    """工具分发:按名字找执行函数。模型只能用这里注册的。"""
    if name == "create_card":
        return run_create_card(**arguments)
    if name == "search_cards":
        return run_search_cards(**arguments)
    if name == "link_cards":
        return run_link_cards(**arguments)
    if name == "list_inbox":
        return run_list_inbox()
    if name == "read_card":
        return run_read_card(**arguments)
    if name == "update_card":
        return run_update_card(**arguments)
    if name == "list_clusters":
        return run_list_clusters()
    if name == "propose_promote":
        return run_propose_promote(**arguments)
    if name == "propose_delete":
        return run_propose_delete(**arguments)
    raise ValueError(f"未注册的工具: {name}")


# ---------------------------------------------------------------------------
# agent 循环
# ---------------------------------------------------------------------------

def box_state() -> str:
    """盒子实时状态:注入 system prompt,让 agent 开口就知道现状。"""
    cards = load_all()
    in_inbox = [c for c in cards if c.path and c.path.parent == inbox_dir()]
    official = len(cards) - len(in_inbox)
    lines = [f"- 正式卡片 {official} 张,待审草稿 {len(in_inbox)} 张"]
    if in_inbox:
        previews = ", ".join(f"{c.id}({c.title[:20]})" for c in in_inbox[:10])
        lines.append(f"- 待审清单: {previews}")
    try:
        import cluster
        found = cluster.find_clusters()
        lines.append(f"- 成熟簇 {len(found)} 个")
    except Exception:
        pass
    return "\n".join(lines)


def compact_history(history: list, keep_last: int = 4) -> list:
    """压缩多轮历史:旧消息 → 摘要,保留最近几轮原样。返回新列表。"""
    if len(history) <= keep_last + 1:
        return history  # 不够长,压了没意义
    old, recent = history[:-keep_last], history[-keep_last:]
    transcript = "\n".join(
        f"[{m['role']}] {str(m.get('content', ''))[:500]}" for m in old
    )
    client = make_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{
            "role": "user",
            "content": "把这段和卡片盒 agent 的对话历史压缩成要点摘要,必须保留:完成的任务、涉及的卡片 id、用户的意图和偏好。直接输出摘要:\n\n" + transcript,
        }],
    )
    summary = response.choices[0].message.content or ""
    return [{"role": "assistant", "content": f"(早前对话的摘要)\n{summary}"}, *recent]


def _call_model(client, messages: list, tools: list, stream: bool = True, retries: int = 2, on_delta=None):
    """调一次模型。stream=True 时文字逐字输出:有 on_delta 走回调(TUI),否则 print。

    网络抖动、限流等瞬时错误自动重试 retries 次(指数退避)。
    只重试 API 传输层错误;回调/UI 层的异常直接抛出,不重试。
    返回统一的 dict 形式:{"content": str, "tool_calls": list|None}
    """
    import time

    import openai as _openai

    transient = (_openai.APIConnectionError, _openai.RateLimitError, _openai.APIStatusError)
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        if attempt:
            wait = 2 ** attempt
            print(f"  API 调用失败({type(last_err).__name__}),{wait}s 后重试…")
            time.sleep(wait)
        try:
            return _call_model_once(client, messages, tools, stream, on_delta=on_delta)
        except transient as e:
            last_err = e
    raise last_err


def _call_model_once(client, messages: list, tools: list, stream: bool = True, on_delta=None):
    if not stream:
        msg = client.chat.completions.create(
            model=MODEL, messages=messages, tools=tools,
        ).choices[0].message
        tool_calls = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in (msg.tool_calls or [])
        ]
        return {"content": msg.content, "tool_calls": tool_calls or None}

    text_parts: list[str] = []
    tool_acc: dict[int, dict] = {}  # index -> {"id","name","arguments"}
    response = client.chat.completions.create(
        model=MODEL, messages=messages, tools=tools, stream=True,
    )
    for chunk in response:
        if INTERRUPT.is_set():
            response.close()
            raise AgentInterrupted()
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            if on_delta:
                on_delta(delta.content)
            else:
                print(delta.content, end="", flush=True)
            text_parts.append(delta.content)
        for tc in (delta.tool_calls or []):
            slot = tool_acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
            if tc.id:
                slot["id"] = tc.id
            if tc.function and tc.function.name:
                slot["name"] = tc.function.name
            if tc.function and tc.function.arguments:
                slot["arguments"] += tc.function.arguments

    tool_calls = None
    if tool_acc:
        tool_calls = [
            {
                "id": slot["id"],
                "type": "function",
                "function": {"name": slot["name"], "arguments": slot["arguments"]},
            }
            for _, slot in sorted(tool_acc.items())
        ]
    return {"content": "".join(text_parts), "tool_calls": tool_calls}


def run_agent(
    user_input: str,
    max_turns: int = 10,
    system_prompt: str = SYSTEM_PROMPT,
    tools: list = TOOLS_SPEC,
    tool_runner=run_tool,
    history: list | None = None,
    stream: bool = True,
    on_delta=None,
    on_event=None,
) -> str:
    """跑一轮 agent:从用户输入到最终回答。

    max_turns 是保险丝:防止模型陷入循环刷爆 API 账单。
    system_prompt / tools / tool_runner 是插槽——M4 的写作岗位插自己的。
    history:多轮对话历史(user/assistant/tool 消息),原地追加,调用方持有它。
    stream:文字回复逐字输出(on_delta 回调或 print)。
    on_event:工具事件回调(TUI 用),None 时退回 print。
      {"type": "tool", "name", "args"} | {"type": "tool_error", "name", "error"} | {"type": "turn", "n"}
    """
    client = make_client()

    if history is None:
        history = []
    history.append({"role": "user", "content": user_input})
    sys_prompt = system_prompt
    if system_prompt is SYSTEM_PROMPT:
        # 只有默认岗位注入盒子状态;write_agent 等自定义岗位不受影响
        sys_prompt = system_prompt + "\n\n# 盒子当前状态\n" + box_state()
    messages = [{"role": "system", "content": sys_prompt}, *history]

    def emit(evt: dict) -> None:
        """工具事件:TUI 走回调,终端模式退回 print。"""
        if on_event:
            on_event(evt)
        elif evt["type"] == "tool":
            print(f"⚙ {evt['name']}({json.dumps(evt['args'], ensure_ascii=False)[:120]})")
        elif evt["type"] == "tool_error":
            print(f"  工具出错: {evt['error']}")

    for turn in range(max_turns):
        if INTERRUPT.is_set():
            raise AgentInterrupted()
        if on_event:
            on_event({"type": "turn", "n": turn + 1})
        result = _call_model(client, messages, tools, stream=stream, on_delta=on_delta)
        content, tool_calls = result["content"], result["tool_calls"]

        # 情况 A:模型想调工具
        if tool_calls:
            assistant_msg = {"role": "assistant", "content": content or "", "tool_calls": tool_calls}
            messages.append(assistant_msg)
            history.append(assistant_msg)
            for tool_call in tool_calls:
                name = tool_call["function"]["name"]
                try:
                    arguments = json.loads(tool_call["function"]["arguments"])
                except json.JSONDecodeError as e:
                    emit({"type": "tool_error", "name": name, "error": f"参数不是合法 JSON: {e}"})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": f"ERROR: tool arguments 不是合法 JSON ({e})。请修正后重新调用同一个工具。",
                    })
                    history.append(messages[-1])
                    continue
                # 常见畸形:模型把参数包成 {"arguments": "{...json...}"},解开它
                if isinstance(arguments, dict) and set(arguments.keys()) == {"arguments"}:
                    inner = arguments["arguments"]
                    if isinstance(inner, str):
                        try:
                            arguments = json.loads(inner)
                        except json.JSONDecodeError:
                            pass
                emit({"type": "tool", "name": name, "args": arguments})
                try:
                    executed = tool_runner(name, arguments)
                except TypeError as e:
                    emit({"type": "tool_error", "name": name, "error": f"参数不匹配工具签名: {e}"})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": f"ERROR: 参数与工具签名不匹配 ({e})。请直接输出扁平的参数对象,不要嵌套在 arguments 键里。",
                    })
                    history.append(messages[-1])
                    continue
                except Exception as e:
                    # 未知工具名、文件系统故障等一切意外:回喂模型让它自我修正,
                    # 而不是整个会话崩掉
                    emit({"type": "tool_error", "name": name, "error": f"{type(e).__name__}: {e}"})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": f"ERROR: 工具执行失败 ({type(e).__name__}: {e})。请换一种方式完成任务,或向用户说明。",
                    })
                    history.append(messages[-1])
                    continue
                # 工具结果喂回对话历史,模型下一轮看到它
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": executed,
                })
                history.append(messages[-1])
            continue  # 回到循环顶部,再问模型下一步

        # 情况 B:模型没要工具,说明它认为做完了
        if content is None:
            content = ""
        history.append({"role": "assistant", "content": content})
        return content

    return f"达到最大轮数 {max_turns},强制停止。"


if __name__ == "__main__":
    import sys
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("给 agent 一段话: ")
    answer = run_agent(text)
    print()
    print("== 最终回答 ==")
    print(answer)
