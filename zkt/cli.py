"""CLI 入口:zkt new / zkt check。

目前两条命令,以后 M2 加 ingest、M3 加 promote。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from card import Card, all_ids, load_all
from audit import log_action, read_log


def cmd_ingest(argv: list[str]) -> int:
    """zkt ingest <url 或 一段话> —— 抓取 + agent 消化成卡片草稿。"""
    import ingest
    return ingest.cmd_ingest(argv)


def cmd_promote(argv: list[str]) -> int:
    """zkt promote <id> —— 人签字:草稿从 inbox 搬进 cards。签字权只在 CLI。"""
    if len(argv) != 1:
        print("用法: zkt promote <卡片id>")
        return 1
    card_id = argv[0]

    card = None
    for c in load_all():
        if c.id == card_id:
            card = c
            break
    if card is None:
        print(f"卡片 {card_id} 不存在")
        return 1
    if card.path is None or card.path.parent.name != "inbox":
        print(f"卡片 {card_id} 已在 cards 里,无需转正")
        return 1

    # 搬家:读原文件 -> 写到 cards/ -> 删 inbox 里的旧文件
    from card import cards_dir
    new_path = cards_dir() / card.path.name
    new_path.write_text(card.path.read_text(encoding="utf-8"), encoding="utf-8")
    card.path.unlink()
    card.path = new_path

    log_action("human", "promote", {"card_id": card_id, "title": card.title})
    print(f"已转正: {card_id} {card.title}")
    print(f"位置: {new_path}")
    return 0


def cmd_drafts(argv: list[str]) -> int:
    """zkt drafts [--open N] —— 列出草稿,可打开第 N 篇(新的在前,默认 1)。"""
    from write_agent import DRAFTS_DIR, list_drafts, open_file

    drafts = list_drafts()
    if not drafts:
        print("drafts/ 里还没有草稿。先 zkt outline → zkt write。")
        return 1

    if argv and argv[0] == "--open":
        rest = argv[1:]
        app = None
        if "--app" in rest:
            i = rest.index("--app")
            app = rest[i + 1] if i + 1 < len(rest) else None
            rest = rest[:i] + rest[i + 2:]
        n = int(rest[0]) if rest else 1
        if not 1 <= n <= len(drafts):
            print(f"序号超范围: 1~{len(drafts)}")
            return 1
        open_file(drafts[n - 1], app=app or os.environ.get("ZKT_APP"))
        print(f"已打开: {drafts[n - 1].name}")
        return 0

    print("草稿(新的在前):")
    for i, p in enumerate(drafts, 1):
        print(f"  {i}. {p.stem}")
    print("\n打开: zkt drafts --open [序号],默认打开第 1 篇")
    return 0


def cmd_home(argv: list[str]) -> int:
    """zkt home [路径|--reset] —— 查看/设置/重置盒子路径。只切指针,不动数据。"""
    from card import ZKTRC, zk_home

    if argv and argv[0] == "--reset":
        ZKTRC.unlink(missing_ok=True)
        print(f"已重置,回到默认: {zk_home()}")
        return 0

    if argv:
        target = Path(argv[0]).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        for sub in ("cards", "inbox", "drafts"):
            (target / sub).mkdir(exist_ok=True)
        tmp = ZKTRC.with_suffix(".tmp")
        tmp.write_text(json.dumps({"home": str(target)}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(ZKTRC)
        print(f"盒子路径已设为: {target}")
        print("(只改指向,原盒子数据未移动。临时换盒可用 ZK_HOME 环境变量。)")
        return 0

    if os.environ.get("ZK_HOME"):
        print(f"当前盒子: {zk_home()}")
        print(f"来源: ZK_HOME 环境变量(临时覆盖,优先级最高)")
    else:
        configured = None
        if ZKTRC.exists():
            try:
                configured = json.loads(ZKTRC.read_text(encoding="utf-8")).get("home")
            except json.JSONDecodeError:
                pass
        print(f"当前盒子: {zk_home()}")
        print(f"来源: {'~/.zktrc 配置' if configured else '默认(未配置)'}")
        if configured:
            print(f"临时换盒: ZK_HOME=<路径> zkt <命令>;回到默认: zkt home --reset")
    return 0


def cmd_audit(argv: list[str]) -> int:
    """zkt audit —— 看审计日志:谁(actor)在何时干了什么。"""
    entries = read_log()
    if not entries:
        print("(审计日志为空)")
        return 0
    for e in entries:
        icon = "🤖" if e["actor"] == "model" else "👤"
        print(f"{icon} {e['time']}  {e['action']}")
        if e.get("card_id"):
            print(f"      卡片: {e['card_id']} {e.get('title', '')}")
        if e.get("from_card"):
            print(f"      链接: {e['from_card']} -> {e['to_card']}")
            print(f"      理由: {e.get('why', '')[:70]}")
        if e.get("keyword"):
            print(f"      关键词: {e['keyword']} 命中 {e.get('hits', 0)} 张")
        if e["action"] == "delete":
            print(f"      断链: {e.get('backlinks_broken', 0)} 条")
        if not e.get("ok", True):
            print(f"      结果: 被拒收 {e.get('errors', [])}")
    return 0


def cmd_new(argv: list[str]) -> int:
    """zkt new "标题" —— 生成带 id 的空卡片到 inbox/。"""
    if not argv:
        print("用法: zkt new <标题>")
        return 1
    title = " ".join(argv)
    card = Card(id=Card.new_id(), title=title, body="")
    card.save(inbox=True)
    print(f"已创建: {card.path}")
    print("正文还是空的,用编辑器补上内容。")
    return 0


def cmd_check(argv: list[str]) -> int:
    """zkt check —— 全盒体检:逐卡校验 + 重复 id 检测。"""
    known = all_ids()

    # 重复 id 检测:文件名(=id)在两个目录里撞车
    seen: dict[str, str] = {}  # id -> 首次出现的位置
    duplicates: list[tuple[str, str, str]] = []  # (id, 位置1, 位置2)
    from card import inbox_dir, cards_dir
    for directory in (inbox_dir(), cards_dir()):
        for path in directory.glob("*.md"):
            if path.stem in seen:
                duplicates.append((path.stem, seen[path.stem], str(path)))
            else:
                seen[path.stem] = str(path)

    errors_total = 0
    print("== 全盒体检报告 ==")
    for card in load_all():
        errs = card.validate(known)
        warns = card.warnings()
        status = "✓ 合格" if not errs else "✗ 违规"
        # inbox 里的卡标个草稿记号,一眼看出哪些还没转正
        tag = " [草稿]" if card.path and card.path.parent.name == "inbox" else ""
        if card.auto:
            tag += " [auto]"
        print(f"{status}  {card.id}{tag}  {card.title}")
        for e in errs:
            print(f"         错误: {e}")
        for w in warns:
            print(f"         警告: {w}")
        errors_total += len(errs)

    if duplicates:
        print()
        print("== 重复 id ==")
        for card_id, p1, p2 in duplicates:
            print(f"  {card_id} 同时存在于:\n    {p1}\n    {p2}")
        errors_total += len(duplicates)

    print()
    if errors_total:
        print(f"共 {errors_total} 处问题。")
        return 1
    print("全盒合格。")
    return 0


def cmd_delete(argv: list[str]) -> int:
    """zkt delete <id> --confirm —— 人签字删除卡片。删前查反链,删后出审计。"""
    if not argv or argv[0] in ("--confirm",):
        print("用法: zkt delete <卡片id> --confirm")
        return 1
    card_id = argv[0]
    confirmed = "--confirm" in argv

    target = None
    for c in load_all():
        if c.id == card_id:
            target = c
            break
    if target is None:
        print(f"卡片 {card_id} 不存在")
        return 1

    # 反链报告:谁链到了它。删了这些就成了死链,宪法会在 check 里报。
    backlinks = [
        (c.id, link) for c in load_all() for link in c.links
        if link.to == card_id and c.id != card_id
    ]
    print(f"待删: {target.id} {target.title}")
    print(f"位置: {target.path}")
    print(f"出链: {len(target.links)} 条")
    if backlinks:
        print(f"⚠ 有 {len(backlinks)} 张卡链到它(删除后成死链):")
        for src, link in backlinks:
            print(f"   {src}: {link.why[:50]}")
    else:
        print("无反链,删除是干净的。")

    if not confirmed:
        print()
        print("确认删除请重跑并加 --confirm:")
        print(f"  zkt delete {card_id} --confirm")
        return 1

    target.path.unlink()
    log_action("human", "delete", {
        "card_id": card_id, "title": target.title,
        "backlinks_broken": len(backlinks),
    })
    print(f"已删除: {card_id}")
    if backlinks:
        print("提醒: 上面的反链已成死链,zkt check 会报出来,记得清理。")
    return 0


def main() -> int:
    # 命令注册表:名字 -> (处理函数, 一句话说明)
    # 说明取自各 cmd_* 的 docstring 首行,help 里直接用
    commands = {
        "new":     (cmd_new,      "生成带 id 的空卡片到 inbox/"),
        "check":   (cmd_check,    "全盒体检:逐卡校验 + 重复 id 检测"),
        "ingest":  (cmd_ingest,   "抓取 + agent 消化成卡片草稿"),
        "inbox":   (None,         "列出/逐张过目待审卡片"),
        "promote": (cmd_promote,  "人签字:草稿从 inbox 搬进 cards"),
        "delete":  (cmd_delete,   "人签字删除卡片(删前查反链)"),
        "audit":   (cmd_audit,    "看审计日志:谁在何时干了什么"),
        "clusters":(None,         "看卡片簇(哪块熟了)"),
        "outline": (None,         "卡片簇 → 文章大纲"),
        "write":   (None,         "大纲 + 卡片全文 → 文章草稿"),
        "drafts":  (cmd_drafts,   "列出草稿,zkt drafts --open 打开"),
        "home":    (cmd_home,     "查看/设置/重置盒子路径(zkt home <路径>)"),
        "graph":   (None,         "生成星图可视化 HTML 并打开"),
        "guide":   (None,         "生成使用手册页 HTML 并打开"),
        "tui":     (None,         "全屏对话界面(zkt 不带参数时默认进入)"),
    }

    args = sys.argv[1:]
    if not args:
        import tui
        return tui.main()
    if args[0] in ("-h", "--help"):
        # 总帮助:列出全部命令 + 一句话
        print("zkt —— 卢曼卡片盒 CLI")
        print()
        print("用法: zkt <命令> [参数]")
        print("      zkt <命令> -h    查看该命令的详细用法")
        print()
        print("命令:")
        for name, (_, desc) in commands.items():
            print(f"  {name:10s} {desc}")
        return 0

    command, argv = args[0], args[1:]

    # 子命令的 -h/--help:拦在执行前,把 docstring 当帮助
    if argv and argv[0] in ("-h", "--help"):
        entry = commands.get(command)
        fn = entry[0] if entry else None
        if fn is not None:
            if fn.__doc__:
                print(fn.__doc__.strip())
                return 0
            print(f"{command} 暂无帮助说明")
            return 0
        # 外模块命令:导入对应模块,取 cmd_* 的 docstring
        mod_map = {"clusters": "cluster", "outline": "write_agent",
                   "write": "write_agent", "graph": "graph", "guide": "guide",
                   "inbox": "inbox"}
        mod = __import__(mod_map.get(command, ""))
        fn = getattr(mod, "cmd_" + command, None)
        if fn and fn.__doc__:
            print(fn.__doc__.strip())
            return 0
        print(f"未知命令: {command}")
        return 1

    if command not in commands:
        print(f"未知命令: {command}")
        print(f"可用命令: {' | '.join(commands.keys())}")
        return 1

    handler, _ = commands[command]
    if handler is not None:
        return handler(argv)
    # 外模块的命令
    if command == "clusters":
        import cluster
        return cluster.cmd_clusters(argv)
    if command == "outline":
        import write_agent
        return write_agent.cmd_outline(argv)
    if command == "write":
        import write_agent
        return write_agent.cmd_write(argv)
    if command == "inbox":
        import inbox as inbox_mod
        return inbox_mod.cmd_inbox(argv)
    if command == "graph":
        import graph
        return graph.cmd_graph(argv)
    if command == "guide":
        import guide
        return guide.cmd_guide(argv)
    if command == "tui":
        import tui
        return tui.main()
    return 1


if __name__ == "__main__":
    sys.exit(main())
